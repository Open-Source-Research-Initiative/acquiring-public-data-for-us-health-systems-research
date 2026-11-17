"""Constrained tar staging into a fresh directory on quota-backed scratch.

Archive contents are data. Never run extracted code without separate review and
qualification. Host filesystem writes never follow archive-provided links.
"""
import os
from pathlib import Path, PurePosixPath
import posixpath
import tarfile


def _guest_allowed(path, roots):
    return any(path == r or path.startswith(r + '/') for r in roots)


def stage_archive(archive, destination, *, guest_root, allowed_guest_roots=(),
                  max_bytes=48 * 1024**3, max_members=250000):
    """Extract regular files, directories and safe guest symlinks, without following links.

    Destination must be new and beneath the trusted caller's quota scratch.
    Absolute links refer solely to explicit guest paths and are never traversed
    by this extractor. Hardlinks, devices, FIFOs and duplicate files fail closed.
    """
    guest = PurePosixPath(guest_root)
    if not guest.is_absolute() or '..' in guest.parts or str(guest) == '/':
        raise ValueError('invalid guest root')
    roots = [str(guest)]
    for item in allowed_guest_roots:
        root = PurePosixPath(item)
        if not root.is_absolute() or '..' in root.parts or str(root) == '/':
            raise ValueError('invalid allowed guest root')
        roots.append(str(root))
    destination = Path(destination)
    destination.mkdir(mode=0o700)  # caller provides a fresh parent
    rootfd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    entries = {}
    total = 0
    try:
        with tarfile.open(archive, 'r:*') as tf:
            for index, member in enumerate(tf):
                if index >= max_members:
                    raise ValueError('archive member limit exceeded')
                name = PurePosixPath(member.name)
                if name.is_absolute() or not name.parts or '..' in name.parts:
                    raise ValueError('invalid archive path')
                parts = name.parts
                if name in entries:
                    if member.isdir() and entries[name] == 'dir':
                        continue
                    raise ValueError('duplicate archive path')
                if member.isdir():
                    kind = 'dir'
                elif member.isfile():
                    kind = 'file'
                    total += member.size
                    if member.size < 0 or total > max_bytes:
                        raise ValueError('archive content limit exceeded')
                elif member.issym():
                    kind = 'symlink'
                    link = member.linkname
                    if not link or '\0' in link:
                        raise ValueError('invalid symbolic link')
                    target = posixpath.normpath(link if link.startswith('/') else posixpath.join(str(guest), *parts[:-1], link))
                    if not _guest_allowed(target, roots):
                        raise ValueError('symbolic link escapes allowed guest roots')
                else:
                    raise ValueError('unsupported archive member')
                entries[name] = kind
                fd = os.dup(rootfd)
                try:
                    for component in parts[:-1]:
                        try:
                            os.mkdir(component, 0o700, dir_fd=fd)
                        except FileExistsError:
                            pass
                        child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                        os.close(fd)
                        fd = child
                    if kind == 'dir':
                        try:
                            os.mkdir(parts[-1], member.mode & 0o777, dir_fd=fd)
                        except FileExistsError:
                            probe = os.open(parts[-1], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                            os.close(probe)
                    elif kind == 'symlink':
                        os.symlink(member.linkname, parts[-1], dir_fd=fd)
                    else:
                        out = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                      member.mode & 0o777, dir_fd=fd)
                        try:
                            source = tf.extractfile(member)
                            if source is None:
                                raise ValueError('archive file has no content')
                            with os.fdopen(out, 'wb') as target_file, source:
                                out = -1
                                while True:
                                    chunk = source.read(1024 * 1024)
                                    if not chunk:
                                        break
                                    target_file.write(chunk)
                        finally:
                            if out != -1:
                                os.close(out)
                finally:
                    os.close(fd)
        return {'members': len(entries), 'unpacked_bytes': total}
    finally:
        os.close(rootfd)
