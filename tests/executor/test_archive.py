import io
import os
from pathlib import Path
import tarfile
import tempfile
import unittest

from executor.archive import stage_archive
from executor.sandbox import run

BASE = '/workspace/repos/builderbob'


def make_tar(path, entries):
    with tarfile.open(path, 'w') as archive:
        for name, kind, data in entries:
            info = tarfile.TarInfo(name)
            if kind == 'file':
                content = data.encode()
                info.size, info.mode = len(content), 0o755
                archive.addfile(info, io.BytesIO(content))
            elif kind == 'link':
                info.type, info.linkname = tarfile.SYMTYPE, data
                archive.addfile(info)
            elif kind == 'hardlink':
                info.type, info.linkname = tarfile.LNKTYPE, data
                archive.addfile(info)


class ArchiveTests(unittest.TestCase):
    def test_guest_links_alias_and_repeated_commands(self):
        with tempfile.TemporaryDirectory(dir=BASE) as tmp:
            base = Path(tmp)
            scratch = base/'scratch'
            scratch.mkdir()
            source = base/'runtime.tar'
            make_tar(source, [('r/file', 'file', 'visible'), ('r/relative', 'link', 'file'),
                              ('r/absolute', 'link', '/workspace/fake/r/file')])
            stage_archive(source, scratch/'runtime', guest_root='/work/runtime',
                          allowed_guest_roots=['/workspace/fake/r'])
            aliases = {'/workspace/fake/r': 'runtime/r', '/data0/mrf-pricing-research': 'data0'}
            code = "import json; print(json.dumps([open('/work/runtime/r/relative').read(),open('/work/runtime/r/absolute').read()])); open('/data0/mrf-pricing-research/w','w').write('ok')"
            first = run(['/usr/bin/python3','-c',code], scratch=scratch, timeout=5, aliases=aliases)
            self.assertEqual(first['returncode'], 0, first)
            self.assertIn('["visible", "visible"]', first['stdout'])
            second = run(['/usr/bin/cat','/data0/mrf-pricing-research/w'], scratch=scratch, timeout=5, aliases=aliases)
            self.assertEqual(second['stdout'], 'ok', second)

    def test_rejects_path_link_and_parent_injection(self):
        attempts = [('../escape','file','x'), ('/absolute','file','x'),
                    ('link','link','/home/builderbob/secret'), ('link','link','../../outside'),
                    ('hard','hardlink','file')]
        with tempfile.TemporaryDirectory(dir=BASE) as tmp:
            base = Path(tmp)
            for i, item in enumerate(attempts):
                source = base/f'{i}.tar'
                make_tar(source, [item])
                with self.assertRaises((ValueError, OSError)):
                    stage_archive(source, base/f'out{i}', guest_root='/work/runtime')
            source = base/'parent.tar'
            make_tar(source, [('path','link','/work/runtime/other'), ('path/file','file','bad')])
            with self.assertRaises((ValueError, OSError)):
                stage_archive(source, base/'outparent', guest_root='/work/runtime')
            self.assertFalse((base/'escape').exists())

    def test_alias_sources_never_follow_symlinks(self):
        with tempfile.TemporaryDirectory(dir=BASE) as tmp:
            base = Path(tmp)
            scratch = base/'scratch'
            scratch.mkdir()
            (scratch/'escape').symlink_to(base)
            with self.assertRaises(OSError):
                run(['/usr/bin/true'], scratch=scratch, timeout=5,
                    aliases={'/workspace/fake/r':'escape/child'})
            self.assertFalse((base/'child').exists())
