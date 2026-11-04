"""Verified torrent pieces must be visible to the HTTP reader before HAVE is set."""
import errno
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from idm_linux.p2p.bencode import bencode
from idm_linux.p2p.bt_native import NativeTorrentSession, PieceManager, Storage, parse_torrent_bytes


class TorrentStorageVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.data = bytes((i * 37 + 11) % 251 for i in range(5000))
        info = {b'name':b'piece.bin', b'piece length':4096, b'length':len(self.data), b'pieces':b''.join(hashlib.sha1(self.data[i:i+4096]).digest() for i in range(0,len(self.data),4096))}
        self.torrent = bencode({b'info':info})
        self.storage = Storage(Path(self.tmp.name), parse_torrent_bytes(self.torrent))
        self.addCleanup(self.storage.close_all)
        self.path = self.storage.paths[0]

    def test_small_write_visible_to_independent_reader_before_close(self):
        self.storage.write(0, self.data[:51])
        self.assertEqual(self.path.read_bytes()[:51], self.data[:51])

    def test_last_partial_piece_visible_before_close(self):
        self.storage.write(0, self.data[:4096]); self.storage.write(4096, self.data[4096:])
        self.assertEqual(self.path.read_bytes(), self.data)

    def test_failed_write_does_not_silently_succeed(self):
        class Broken:
            def seek(self, offset): pass
            def write(self, data): raise OSError(errno.ENOSPC, 'disk full fixture')
            def close(self): pass
        with patch.object(self.storage, '_get_handle', return_value=Broken()):
            with self.assertRaises(OSError): self.storage.write(0, self.data[:51])

    def test_unopenable_file_does_not_silently_succeed(self):
        with patch.object(self.storage, '_get_handle', return_value=None):
            with self.assertRaises(OSError): self.storage.write(0, self.data[:51])

    def test_zero_write_is_failure_not_verified_piece(self):
        class Zero:
            def seek(self, offset): pass
            def write(self, data): return 0
            def close(self): pass
        with patch.object(self.storage, '_get_handle', return_value=Zero()):
            with self.assertRaises(OSError): self.storage.write(0, self.data[:51])

    def test_short_writes_are_retried_until_complete(self):
        with self.path.open('r+b', buffering=0) as target:
            class Short:
                def seek(self, offset): target.seek(offset)
                def write(self, data): return target.write(data[:7])
                def close(self): pass
            with patch.object(self.storage, '_get_handle', return_value=Short()):
                self.storage.write(0, self.data[:51])
        self.assertEqual(self.path.read_bytes()[:51], self.data[:51])

    def test_disk_error_does_not_publish_have_or_complete(self):
        session = NativeTorrentSession(Path(self.tmp.name) / 'session', torrent_bytes=self.torrent, enable_dht=False)
        session.pieces = PieceManager(session.meta)
        session.storage = self.storage
        with patch.object(self.storage, 'write', side_effect=OSError(errno.ENOSPC, 'disk full fixture')):
            session._on_piece_downloaded(0, self.data[:4096])
        self.assertEqual(session.pieces.completed_bytes(), 0)
        self.assertEqual(session.pieces.contiguous(), 0)
        self.assertFalse(session.all_done)
        self.assertTrue(session.error_message)
        self.assertTrue(session.stopping)

    def test_have_is_published_only_with_independently_readable_bytes(self):
        session = NativeTorrentSession(Path(self.tmp.name) / 'session', torrent_bytes=self.torrent, enable_dht=False)
        session.pieces = PieceManager(session.meta)
        session.storage = self.storage
        session._on_piece_downloaded(0, self.data[:4096])
        self.assertEqual(session.pieces.completed_bytes(), 4096)
        self.assertEqual(self.path.read_bytes()[:4096], self.data[:4096])
        session._on_piece_downloaded(1, self.data[4096:])
        self.assertTrue(session.all_done)
        self.assertEqual(self.path.read_bytes(), self.data)

    def test_piece_spanning_two_files_visible_to_independent_readers(self):
        info = {b'name':b'bundle', b'piece length':4096,
                b'pieces':b''.join(hashlib.sha1(self.data[i:i+4096]).digest() for i in range(0,len(self.data),4096)),
                b'files':[{b'length':31,b'path':[b'a.bin']},{b'length':4969,b'path':[b'b.bin']}]}
        storage = Storage(Path(self.tmp.name)/'multi', parse_torrent_bytes(bencode({b'info':info})))
        self.addCleanup(storage.close_all)
        storage.write(0, self.data[:4096]); storage.write(4096, self.data[4096:])
        self.assertEqual(b''.join(p.read_bytes() for p in storage.paths), self.data)

if __name__ == '__main__':unittest.main()
