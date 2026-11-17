import socket
import socketserver
import ssl
import tempfile
import threading
import unittest
from pathlib import Path

from executor.egress import EgressBroker, create_tls_material


class Upstream(socketserver.BaseRequestHandler):
    def handle(self):
        if self.request.recv(4096):
            try:
                self.request.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello')
            except OSError:
                pass


class EgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='/workspace/repos/builderbob')
        self.upstream = socketserver.TCPServer(('127.0.0.1', 0), Upstream)
        threading.Thread(target=self.upstream.serve_forever, daemon=True).start()
        self.path = str(Path(self.tmp.name) / 'proxy.sock')

    def tearDown(self):
        self.upstream.shutdown()
        self.upstream.server_close()
        self.tmp.cleanup()

    def resolver(self, host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, '', self.upstream.server_address)]

    def request(self, raw):
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(3)
            s.connect(self.path)
            s.sendall(raw)
            chunks = []
            while True:
                part = s.recv(4096)
                if not part:
                    return b''.join(chunks)
                chunks.append(part)

    def test_allowed_and_redacted(self):
        with EgressBroker(self.path, ['example.test'], 10000, _test_resolver=self.resolver) as broker:
            result = self.request(b'GET http://example.test/private?secret=hidden HTTP/1.1\r\nHost: example.test\r\n\r\n')
            self.assertIn(b'hello', result)
            self.assertGreater(broker.transferred, len(result))
            self.assertNotIn('secret', str(broker.events))
            connected = next(e for e in broker.events if e['status'] == 'connected')
            response = next(e for e in broker.events if e['status'] == 'response')
            self.assertEqual(connected['request_id'], response['request_id'])
            self.assertEqual(response['response_status'], 200)
            self.assertIn('timestamp_utc', response)
            request = next(e for e in broker.events if e['status'] == 'request')
            transfer = next(e for e in broker.events if e['status'] == 'response_transfer')
            self.assertEqual(request['body_bytes'], 0)
            self.assertEqual(transfer['bytes'], len(result))
            self.assertTrue(transfer['upstream_eof'])
            self.assertIsNone(transfer['message_complete'])

    def test_rejected_request_reasons_are_specific_and_redacted(self):
        with EgressBroker(self.path, ['example.test'], 10000, _test_resolver=self.resolver) as broker:
            for header, reason in ((b'Cookie: session=secret', 'denied_header_cookie'),
                                   (b'Authorization: secret', 'denied_header_authorization'),
                                   (b'Transfer-Encoding: chunked', 'denied_header_transfer_encoding')):
                raw = b'GET http://example.test/private?token=secret HTTP/1.1\r\nHost: example.test\r\n' + header + b'\r\n\r\n'
                self.assertIn(b'403 Forbidden', self.request(raw))
                self.assertEqual(broker.events[-1]['reason'], reason)
            self.assertEqual(len({e['request_id'] for e in broker.events}), 3)
            self.assertNotIn('secret', str(broker.events))

    def test_https_publisher_cookie_only(self):
        material = Path(self.tmp.name) / 'tls'
        bundle = create_tls_material(material, ['example.test'])
        class CookieUpstream(socketserver.BaseRequestHandler):
            def handle(self):
                request = self.request.recv(4096)
                if not request:
                    return
                if b'cookie: session=issued' in request.lower():
                    body = b'cookie accepted'
                    self.request.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 15\r\n\r\n' + body)
                else:
                    self.request.sendall(b'HTTP/1.1 103 Early Hints\r\n\r\nHTTP/1.1 200 OK\r\nSet-Cookie: session=issued; Secure\r\nContent-Length: 0\r\n\r\n')
        self.upstream.shutdown()
        self.upstream.server_close()
        self.upstream = socketserver.TCPServer(('127.0.0.1', 0), CookieUpstream)
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(material / 'example.test.pem', material / 'example.test.key')
        self.upstream.socket = server_context.wrap_socket(self.upstream.socket, server_side=True)
        threading.Thread(target=self.upstream.serve_forever, daemon=True).start()
        trust = ssl.create_default_context(cafile=str(bundle))
        def request(cookie=''):
            with socket.socket(socket.AF_UNIX) as raw:
                raw.settimeout(3)
                raw.connect(self.path)
                raw.sendall(b'CONNECT example.test:443 HTTP/1.1\r\nHost: example.test:443\r\n\r\n')
                self.assertIn(b'200 Connection', raw.recv(4096))
                with trust.wrap_socket(raw, server_hostname='example.test') as client:
                    client.sendall(('GET / HTTP/1.1\r\nHost: example.test\r\n' + cookie + '\r\n').encode())
                    return client.recv(4096)
        with EgressBroker(self.path, ['example.test'], 10000, tls_dir=material,
                          _test_resolver=self.resolver, _test_upstream_context=trust,
                          allow_publisher_cookies=True) as broker:
            self.assertIn(b'403', request('Cookie: session=forged\r\n'))
            self.assertIn(b'200 OK', request())
            self.assertIn(b'cookie accepted', request('Cookie: session=issued\r\n'))
            self.assertIn(b'403', request('Cookie: session=issued; other=secret\r\n'))
            self.assertTrue(all(e['response_status'] == 200 for e in broker.events if e['status'] == 'response'))
            self.assertNotIn('issued', str(broker.events))
            self.assertNotIn('secret', str(broker.events))

    def test_denials_and_no_payload(self):
        with EgressBroker(self.path, ['example.test'], 10000, _test_resolver=self.resolver):
            for target, host in [('http://evil.test/x', 'evil.test'), ('http://example.test:81/', 'example.test:81'), ('http://example.test@evil.test/', 'evil.test'), ('http://example.test/', 'evil.test')]:
                result = self.request(f'GET {target} HTTP/1.1\r\nHost: {host}\r\n\r\n'.encode())
                self.assertIn(b'403 Forbidden', result)
                self.assertNotIn(b'hello', result)

    def test_cap_stops_output(self):
        with EgressBroker(self.path, ['example.test'], 80, _test_resolver=self.resolver) as broker:
            result = self.request(b'GET http://example.test/ HTTP/1.1\r\nHost: example.test\r\n\r\n')
            self.assertNotIn(b'hello', result)
            self.assertLessEqual(broker.transferred, 80)

    def test_connect_and_credentials(self):
        with EgressBroker(self.path, ['example.test'], 10000, _test_resolver=self.resolver):
            denied = self.request(b'CONNECT evil.test:443 HTTP/1.1\r\nHost: evil.test:443\r\n\r\n')
            self.assertIn(b'403 Forbidden', denied)
            denied = self.request(b'GET http://example.test/ HTTP/1.1\r\nHost: example.test\r\nAuthorization: secret\r\n\r\n')
            self.assertIn(b'403 Forbidden', denied)
            self.assertNotIn(b'secret', denied)

    def test_mixed_dns_rejected(self):
        from unittest.mock import patch
        public = (socket.AF_INET, socket.SOCK_STREAM, 0, '', ('8.8.8.8', 80))
        with patch('socket.getaddrinfo', return_value=[public, *self.resolver('', 80)]):
            with EgressBroker(self.path, ['example.test'], 10000):
                result = self.request(b'GET http://example.test/ HTTP/1.1\r\nHost: example.test\r\n\r\n')
                self.assertIn(b'403 Forbidden', result)

    def test_tls_matching_and_fronting_and_bad_upstream(self):
        material = Path(self.tmp.name) / 'tls'
        bundle = create_tls_material(material, ['example.test'])
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(material / 'example.test.pem', material / 'example.test.key')
        self.upstream.socket = server_context.wrap_socket(self.upstream.socket, server_side=True)
        trust = ssl.create_default_context(cafile=str(bundle))
        def connect(sni, host, ctx):
            with socket.socket(socket.AF_UNIX) as raw:
                raw.settimeout(3)
                raw.connect(self.path)
                raw.sendall(b'CONNECT example.test:443 HTTP/1.1\r\nHost: example.test:443\r\n\r\n')
                reply = raw.recv(4096)
                if b'200 Connection' not in reply:
                    return reply
                with ctx.wrap_socket(raw, server_hostname=sni) as client:
                    client.sendall(f'GET / HTTP/1.1\r\nHost: {host}\r\n\r\n'.encode())
                    return client.recv(4096)
        child_trust = ssl.create_default_context(cafile=str(bundle))
        with EgressBroker(self.path, ['example.test'], 10000, tls_dir=material, _test_resolver=self.resolver, _test_upstream_context=trust) as broker:
            self.assertIn(b'hello', connect('example.test', 'example.test', child_trust))
            self.assertIn(b'403', connect('example.test', 'forbidden.test', child_trust))
            with self.assertRaises(ssl.SSLError):
                connect('forbidden.test', 'example.test', ssl._create_unverified_context())
            self.assertLessEqual(broker.transferred, broker.max_bytes)
        with EgressBroker(self.path, ['example.test'], 10000, tls_dir=material, _test_resolver=self.resolver):
            self.assertIn(b'403', connect('example.test', 'example.test', child_trust))

    def test_post_and_shared_budget(self):
        request = (b'POST http://example.test/ HTTP/1.1\r\nHost: example.test\r\n'
                   b'Content-Type: application/json\r\nContent-Length: 2\r\n\r\n{}')
        with EgressBroker(self.path, ['example.test'], 250, _test_resolver=self.resolver) as broker:
            self.assertIn(b'hello', self.request(request))
            second = self.request(request)
            self.assertNotIn(b'hello', second)
            self.assertLessEqual(broker.transferred, 250)

    def test_durable_shared_budget_across_broker_restart(self):
        from executor.supervisor import CaseBudget
        ledger = Path(self.tmp.name) / 'budget.sqlite'
        budget = CaseBudget(ledger, network_bytes=250)
        request = (b'POST http://example.test/ HTTP/1.1\r\nHost: example.test\r\n'
                   b'Content-Type: application/json\r\nContent-Length: 2\r\n\r\n{}')
        token = budget.reserve(30, active=True)
        with EgressBroker(self.path, ['example.test'], 10000, _test_resolver=self.resolver, budget=budget):
            self.assertIn(b'hello', self.request(request))
        spent = budget.snapshot()['network_bytes']
        budget.close()
        budget = CaseBudget(ledger, network_bytes=250)
        self.assertEqual(spent, budget.snapshot()['network_bytes'])
        self.assertFalse(budget.transfer_allowed())
        token = budget.reserve(30, active=True)
        with EgressBroker(self.path, ['example.test'], 10000, _test_resolver=self.resolver, budget=budget):
            self.assertNotIn(b'hello', self.request(request))
        self.assertLessEqual(budget.snapshot()['network_bytes'], 250)
        budget.finish(token, 0)
        budget.close()

    def test_pipelined_request_is_not_forwarded(self):
        raw = (b'GET http://example.test/ HTTP/1.1\r\nHost: example.test\r\n\r\n'
               b'GET http://evil.test/ HTTP/1.1\r\nHost: evil.test\r\n\r\n')
        with EgressBroker(self.path, ['example.test'], 10000, _test_resolver=self.resolver):
            self.assertIn(b'403', self.request(raw))

    def test_slow_body_absolute_deadline(self):
        import time
        with EgressBroker(self.path, ['example.test'], 10000, timeout=0.25, _test_resolver=self.resolver):
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(2)
                client.connect(self.path)
                client.sendall(b'POST http://example.test/ HTTP/1.1\r\nHost: example.test\r\nContent-Length: 4\r\n\r\na')
                time.sleep(0.4)
                self.assertIn(b'403', client.recv(4096))

    def test_http_only_rejects_connect_before_upstream(self):
        material = Path(self.tmp.name) / 'tls'
        create_tls_material(material, ['example.test'])
        calls = []
        def resolver(host, port):
            calls.append((host, port))
            return self.resolver(host, port)
        with EgressBroker(self.path, ['example.test'], 10000, tls_dir=material,
                          _test_resolver=resolver, allowed_schemes=('http',)) as broker:
            result = self.request(b'CONNECT example.test:443 HTTP/1.1\r\nHost: example.test:443\r\n\r\n')
            self.assertIn(b'403 Forbidden', result)
            self.assertEqual(calls, [])
            self.assertEqual(broker.events[-1]['phase'], 'request')
            self.assertEqual(broker.events[-1]['error_class'], 'policy')

    def test_event_limit_and_redaction(self):
        broker = EgressBroker(self.path, ['example.test'], 10000)
        for _ in range(10002):
            broker._record('blocked', 'secret-forbidden.test', 'secret-method', phase='request', error_class='policy')
        self.assertEqual(len(broker.events), 10000)
        self.assertEqual(broker.dropped_event_count, 2)
        self.assertNotIn('secret', str(broker.events))

    def test_prepaid_small_cap_and_crash_restart(self):
        from executor.supervisor import CaseBudget
        ledger = Path(self.tmp.name) / 'prepaid.sqlite'
        budget = CaseBudget(ledger, network_bytes=100)
        token = budget.reserve(30, active=True)
        first = EgressBroker(self.path, ['example.test'], 1000, budget=budget)
        self.assertTrue(first._consume(30))
        self.assertEqual(first.reserved_bytes, 100)
        self.assertEqual(first.reserved_unused, 100)
        budget.close()  # Simulate loss of the broker and its unused credit.
        budget = CaseBudget(ledger, network_bytes=100)
        self.assertFalse(budget.transfer_allowed())
        token = budget.reserve(30, active=True)
        second = EgressBroker(self.path, ['example.test'], 1000, budget=budget)
        self.assertFalse(second._consume(1))
        self.assertEqual(budget.snapshot()['network_bytes'], 100)
        budget.finish(token, 0)
        budget.close()

    def test_concurrent_brokers_cannot_overreserve(self):
        from executor.supervisor import CaseBudget
        ledger = Path(self.tmp.name) / 'concurrent.sqlite'
        budget = CaseBudget(ledger, network_bytes=1500000)
        token = budget.reserve(30, active=True)
        first = EgressBroker(self.path, ['example.test'], 2000000, budget=budget)
        second = EgressBroker(self.path, ['example.test'], 2000000, budget=budget)
        barrier = threading.Barrier(2)
        results = []
        def debit(broker):
            barrier.wait()
            results.append(broker._consume(700000))
        threads = [threading.Thread(target=debit, args=(b,)) for b in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(results), 1)
        self.assertLessEqual(budget.snapshot()['network_bytes'], 1500000)
        budget.finish(token, 0)
        budget.close()

    def test_partial_send_reuses_credit_and_checks_live_authorization(self):
        import time
        class Budget:
            allowed = True
            used = 0
            def transfer_allowed(self):
                return self.allowed
            def consume_network(self, count):
                self.used += count
                return True
        class PartialFailure:
            calls = 0
            def settimeout(self, timeout):
                pass
            def send(self, data):
                self.calls += 1
                if self.calls == 1:
                    return 3
                raise BrokenPipeError()
        class Sink:
            def settimeout(self, timeout):
                pass
            def send(self, data):
                return len(data)
        budget = Budget()
        broker = EgressBroker(self.path, ['example.test'], 100, budget=budget)
        with self.assertRaises(BrokenPipeError):
            broker._forward(PartialFailure(), b'1234567890', time.monotonic() + 5)
        self.assertEqual(broker.forwarded, 3)
        self.assertEqual(broker.transferred, 3)
        self.assertEqual(broker.reserved_unused, 1024 * 1024 - 3)
        self.assertTrue(broker._forward(Sink(), b'abcdefg', time.monotonic() + 5))
        self.assertEqual(budget.used, 1024 * 1024)
        self.assertEqual(broker.forwarded, 10)
        budget.allowed = False
        self.assertFalse(broker._forward(Sink(), b'x', time.monotonic() + 5))
        self.assertEqual(broker.forwarded, 10)

    def test_prepaid_credit_expires_with_live_reservation(self):
        import time
        from executor.supervisor import CaseBudget
        budget = CaseBudget(Path(self.tmp.name) / 'expiry.sqlite', network_bytes=100)
        token = budget.reserve(0.1, active=True)
        broker = EgressBroker(self.path, ['example.test'], 100, budget=budget)
        self.assertTrue(broker._consume(1))
        time.sleep(0.15)
        self.assertFalse(broker._consume(1))
        budget.abandon(token)
        budget.close()

    def test_private_dns_denied_without_test_override(self):
        from unittest.mock import patch
        with patch('socket.getaddrinfo', return_value=self.resolver('', 80)):
            with EgressBroker(self.path, ['example.test'], 10000):
                result = self.request(b'GET http://example.test/ HTTP/1.1\r\nHost: example.test\r\n\r\n')
                self.assertIn(b'403 Forbidden', result)
                self.assertNotIn(b'hello', result)


if __name__ == '__main__':
    unittest.main()
