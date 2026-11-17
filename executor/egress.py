"""Allowlisted HTTP proxy with an instrumented, locally trusted TLS hop.

The broker private CA key must remain outside the executor. A proxy socket and
combined public trust bundle are the only broker resources exposed to a child.
"""
from __future__ import annotations

import argparse
import datetime
import ipaddress
import os
import selectors
import socket
import socketserver
import ssl
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

_MAX_HEADER = 16384
_MAX_BODY = 1024 * 1024
_CREDIT_QUANTUM = 1024 * 1024
_METHODS = {'GET', 'HEAD', 'POST'}


def create_tls_material(directory, hosts):
    """Create fresh private CA/leaf keys and public combined roots in directory."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Disposable pilot proxy CA')])
    ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
          .not_valid_after(now + datetime.timedelta(days=2))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(True, False, False, False, False, True, True, False, False), critical=True)
          .sign(ca_key, hashes.SHA256()))
    ca_pem = ca.public_bytes(serialization.Encoding.PEM)
    (directory / 'ca.pem').write_bytes(ca_pem)
    roots = ssl.get_default_verify_paths().openssl_cafile
    if not roots:
        raise ValueError('system CA bundle unavailable')
    (directory / 'client-bundle.pem').write_bytes(Path(roots).read_bytes() + b'\n' + ca_pem)
    for host in hosts:
        if not _valid_host(host):
            raise ValueError('invalid host')
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
                .not_valid_after(now + datetime.timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .sign(ca_key, hashes.SHA256()))
        (directory / (host + '.pem')).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        path = directory / (host + '.key')
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        path.chmod(0o600)
    return directory / 'client-bundle.pem'


class _Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


class EgressBroker:
    def __init__(self, socket_path, allowed_hosts, max_bytes, timeout=15, *, tls_dir=None,
                 _test_resolver=None, _test_upstream_context=None, budget=None,
                 allowed_schemes=("http", "https")):
        self.socket_path = str(socket_path)
        self.allowed_hosts = frozenset(h.lower() for h in allowed_hosts)
        if not self.allowed_hosts or any(not _valid_host(h) for h in self.allowed_hosts):
            raise ValueError('invalid allowlist')
        if max_bytes <= 0 or timeout <= 0:
            raise ValueError('limits must be positive')
        self.allowed_schemes = frozenset(allowed_schemes)
        if not self.allowed_schemes or not self.allowed_schemes <= {"http", "https"}:
            raise ValueError("invalid allowed schemes")
        self.max_bytes, self.timeout = max_bytes, timeout
        self.tls_dir = Path(tls_dir) if tls_dir else None
        self._test_resolver, self._test_upstream_context = _test_resolver, _test_upstream_context
        self.budget = budget
        self._lock = threading.Lock()
        self._transfer_lock = threading.Lock()
        self.transferred = 0  # Bytes admitted before a send; legacy counter.
        self.forwarded = 0  # Bytes confirmed by socket.send.
        self.reserved_bytes = 0
        self._credit = 0
        self.events = []
        self.dropped_event_count = 0
        self.server = None

    def _record(self, status, host=None, method=None, *, phase=None, error_class=None):
        with self._lock:
            if len(self.events) >= 10000:
                self.dropped_event_count += 1
                return
            event = {'status': status, 'host': host if host in self.allowed_hosts else None,
                     'method': method if method in _METHODS | {'CONNECT'} else None}
            if phase is not None:
                event.update(phase=phase, error_class=error_class)
            self.events.append(event)

    @property
    def reserved_unused(self):
        with self._lock:
            return self.reserved_bytes - self.forwarded if self.budget is not None else None

    def _consume(self, count):
        with self._lock:
            if self.transferred + count > self.max_bytes:
                return False
            if self.budget is not None:
                try:
                    if not self.budget.transfer_allowed():
                        return False
                    if count > self._credit:
                        needed = count - self._credit
                        reserve = max(_CREDIT_QUANTUM, needed)
                        if not self.budget.consume_network(reserve):
                            # Another broker may race this snapshot. The ledger
                            # transaction remains authoritative; fail closed.
                            snapshot = self.budget.snapshot()
                            reserve = snapshot['network_limit'] - snapshot['network_bytes']
                            if reserve < needed or not self.budget.consume_network(reserve):
                                return False
                        self.reserved_bytes += reserve
                        self._credit += reserve
                    self._credit -= count
                except Exception:
                    return False
            self.transferred += count
            return True

    def _send_counted(self, stream, data, deadline):
        view = memoryview(data)
        while view:
            if self.budget is not None:
                try:
                    allowed = self.budget.transfer_allowed()
                except Exception:
                    allowed = False
                if not allowed:
                    raise TimeoutError("transfer authorization expired")
            _set_deadline(stream, deadline)
            sent = stream.send(view)
            if not sent:
                raise OSError('socket closed')
            with self._lock:
                self.forwarded += sent
            view = view[sent:]

    def _forward(self, stream, data, deadline):
        # Serialize admission and sending, returning unsent bytes to the same
        # broker credit without ever refunding the durable reservation.
        with self._transfer_lock:
            if not self._consume(len(data)):
                return False
            before = self.forwarded
            try:
                self._send_counted(stream, data, deadline)
            except OSError:
                with self._lock:
                    unsent = len(data) - (self.forwarded - before)
                    self.transferred -= unsent
                    if self.budget is not None:
                        self._credit += unsent
                raise
            return True

    def start(self):
        broker = self
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                broker._handle(self.request)
        self.server = _Server(self.socket_path, Handler)
        os.chmod(self.socket_path, 0o600)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def close(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join()
            try:
                os.unlink(self.socket_path)
            except FileNotFoundError:
                pass
            self.server = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.close()

    def _resolve(self, host, port, deadline):
        result = []
        def lookup():
            try:
                result.append(self._test_resolver(host, port) if self._test_resolver else
                              socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
            except OSError:
                pass
        worker = threading.Thread(target=lookup, daemon=True)
        worker.start()
        worker.join(max(0, deadline - time.monotonic()))
        if worker.is_alive():
            raise TimeoutError('DNS timeout')
        if not result or not result[0]:
            raise OSError('DNS failure')
        for info in result[0]:
            if not ipaddress.ip_address(info[4][0]).is_global and self._test_resolver is None:
                raise ValueError('non-public address')
        return result[0][0]

    def _handle(self, client):
        deadline = time.monotonic() + self.timeout
        client.settimeout(self.timeout)
        host = method = None
        upstream = None
        tls_client = None
        phase = "request"
        try:
            first, rest = _read_header(client, deadline)
            method, target, version, headers = _parse(first)
            if method == 'CONNECT':
                if 'https' not in self.allowed_schemes:
                    raise ValueError('scheme denied')
                if not target.endswith(':443') or target.count(':') != 1 or rest:
                    raise ValueError('invalid CONNECT')
                host = target[:-4].lower()
                _check_host(host, headers, 443, self.allowed_hosts)
                if any(k in ('content-length', 'transfer-encoding') for k, _ in headers) or not self.tls_dir:
                    raise ValueError('CONNECT body or TLS unavailable')
                # Resolve and connect before accepting TLS; verify the remote certificate
                # against the original host, with the validated IP used directly.
                phase = "upstream_connect"
                upstream = self._connect(host, 443, tls=True, deadline=deadline)
                phase = "client_tls"
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                context.set_alpn_protocols(['http/1.1'])
                context.load_cert_chain(self.tls_dir / (host + '.pem'), self.tls_dir / (host + '.key'))
                def check_sni(_sock, name, _ctx):
                    if name != host:
                        return ssl.ALERT_DESCRIPTION_UNRECOGNIZED_NAME
                context.set_servername_callback(check_sni)
                client.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                _set_deadline(client, deadline)
                tls_client = context.wrap_socket(client, server_side=True)
                phase = "inner_request"
                first, rest = _read_header(tls_client, deadline)
                method, target, version, headers = _parse(first)
                if method not in _METHODS or not target.startswith('/') or target.startswith('//') or '#' in target:
                    raise ValueError('invalid inner request')
                _check_host(host, headers, 443, self.allowed_hosts)
                client_stream = tls_client
            else:
                if 'http' not in self.allowed_schemes:
                    raise ValueError('scheme denied')
                if method not in _METHODS:
                    raise ValueError('method')
                parsed = urlsplit(target)
                if parsed.scheme != 'http' or parsed.username is not None or parsed.password is not None or parsed.fragment or parsed.port not in (None, 80):
                    raise ValueError('invalid URI')
                host = (parsed.hostname or '').lower()
                if parsed.netloc.lower() not in (host, host + ':80'):
                    raise ValueError('authority')
                _check_host(host, headers, 80, self.allowed_hosts)
                target = parsed.path or '/'
                if parsed.query:
                    target += '?' + parsed.query
                phase = "upstream_connect"
                upstream = self._connect(host, 80, tls=False, deadline=deadline)
                client_stream = client
            phase = "request_body"
            if not target.startswith('/') or target.startswith('//') or any(ord(c) < 33 or ord(c) > 126 for c in target):
                raise ValueError('invalid path')
            lengths = [v for k, v in headers if k == 'content-length']
            if any(k in ('transfer-encoding', 'authorization', 'proxy-authorization', 'cookie', 'upgrade', 'expect') for k, _ in headers):
                raise ValueError('unsupported header')
            if len(lengths) > 1 or (lengths and (not lengths[0].isdigit() or len(lengths[0]) > 8)):
                raise ValueError('ambiguous length')
            size = int(lengths[0]) if lengths else 0
            if size > _MAX_BODY or (method != 'POST' and size) or len(rest) > size:
                raise ValueError('unsupported body')
            body = rest
            while len(body) < size:
                _set_deadline(client_stream, deadline)
                chunk = client_stream.recv(min(16384, size - len(body)))
                if not chunk:
                    raise ValueError('truncated body')
                body += chunk
            excluded = {'proxy-connection', 'connection', 'host', 'content-length'}
            outbound = f'{method} {target} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n'.encode()
            if lengths:
                outbound += f'Content-Length: {size}\r\n'.encode()
            outbound += b''.join(f'{k}: {v}\r\n'.encode('ascii') for k, v in headers if k not in excluded) + b'\r\n' + body
            phase = "upstream_transfer"
            for offset in range(0, len(outbound), _CREDIT_QUANTUM):
                part = outbound[offset:offset + _CREDIT_QUANTUM]
                if not self._forward(upstream, part, deadline):
                    raise ValueError('byte cap')
            self._record('connected', host, method)
            while True:
                _set_deadline(upstream, deadline)
                chunk = upstream.recv(16384)
                if not chunk:
                    break
                if not self._forward(client_stream, chunk, deadline):
                    self._record('byte_cap', host, method)
                    break
        except (OSError, ValueError, UnicodeError, ssl.SSLError) as error:
            error_class = ('timeout' if isinstance(error, TimeoutError) else
                           'tls' if isinstance(error, ssl.SSLError) else
                           'connection' if isinstance(error, OSError) else 'policy')
            self._record('blocked', host, method, phase=phase, error_class=error_class)
            try:
                (tls_client or client).sendall(b'HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n')
            except OSError:
                pass
        finally:
            if upstream:
                upstream.close()
            if tls_client:
                tls_client.close()

    def _connect(self, host, port, tls, deadline):
        family, socktype, proto, _, address = self._resolve(host, port, deadline)
        sock = socket.socket(family, socktype, proto)
        _set_deadline(sock, deadline)
        try:
            sock.connect(address)
            if tls:
                context = self._test_upstream_context or ssl.create_default_context(
                    cafile=ssl.get_default_verify_paths().openssl_cafile)
                context.set_alpn_protocols(['http/1.1'])
                _set_deadline(sock, deadline)
                sock = context.wrap_socket(sock, server_hostname=host)
            return sock
        except Exception:
            sock.close()
            raise


def _set_deadline(stream, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("request deadline exceeded")
    stream.settimeout(remaining)


def _read_header(stream, deadline):
    data = b''
    while b'\r\n\r\n' not in data:
        _set_deadline(stream, deadline)
        chunk = stream.recv(min(4096, _MAX_HEADER + 1 - len(data)))
        if not chunk:
            raise ValueError('incomplete header')
        data += chunk
        if len(data) > _MAX_HEADER:
            raise ValueError('header too large')
    return data.split(b'\r\n\r\n', 1)


def _parse(header):
    lines = header.decode('ascii').split('\r\n')
    method, target, version = lines[0].split(' ')
    if version not in ('HTTP/1.0', 'HTTP/1.1'):
        raise ValueError('version')
    headers = []
    for line in lines[1:]:
        if not line or line[0].isspace() or ':' not in line:
            raise ValueError('header')
        name, value = line.split(':', 1)
        if not name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-' for c in name):
            raise ValueError('header name')
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('header value')
        headers.append((name.lower(), value.strip()))
    return method, target, version, headers


def _check_host(host, headers, port, allowlist):
    if not _valid_host(host) or host not in allowlist:
        raise ValueError('host')
    values = [v.lower() for k, v in headers if k == 'host']
    if len(values) != 1 or values[0] not in (host, f'{host}:{port}'):
        raise ValueError('host header')


def _valid_host(host):
    if not host or len(host) > 253 or host.endswith('.'):
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return all(0 < len(part) <= 63 and part[0] != '-' and part[-1] != '-' and all(c in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in part) for part in host.split('.'))


def _relay(a, b, consume, timeout):
    sel = selectors.DefaultSelector()
    try:
        sel.register(a, selectors.EVENT_READ, b)
        sel.register(b, selectors.EVENT_READ, a)
        while sel.get_map():
            events = sel.select(timeout)
            if not events:
                return
            for key, _ in events:
                data = key.fileobj.recv(16384)
                if not data or not consume(len(data)):
                    return
                key.data.sendall(data)
    finally:
        sel.close()


def forward(socket_path, port):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as upstream:
                upstream.settimeout(15)
                upstream.connect(socket_path)
                self.request.settimeout(15)
                _relay(self.request, upstream, lambda _: True, 15)
    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
    with Server(('127.0.0.1', port), Handler) as server:
        server.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['forward'])
    parser.add_argument('--socket', required=True)
    parser.add_argument('--port', required=True, type=int)
    args = parser.parse_args()
    forward(args.socket, args.port)
