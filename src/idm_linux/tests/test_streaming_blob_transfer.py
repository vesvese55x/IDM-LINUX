import unittest, tempfile, base64, hashlib
from pathlib import Path
from idm_linux.blob_transfer import BlobTransferStore

class StreamingBlobTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=BlobTransferStore(Path(self.tmp.name)/'staging');self.store.MAX_BYTES=1024*1024;self.store.STREAM_MAX_BYTES=1024*1024;self.addCleanup(lambda:[self.store.cancel(k) for k in list(self.store._jobs)])
    def test_unknown_length_needs_explicit_opt_in(self):
        for flag in [False, 'true', 1]:
            with self.assertRaises(ValueError):self.store.begin('qa.zip','application/zip',None,streaming=flag)
    def test_stream_requires_exact_positive_final_size_and_hashes_bytes(self):
        key=self.store.begin('qa.zip','application/zip',None,streaming=True)['transferId'];data=b'one-shot transfer'
        self.store.chunk(key,0,base64.b64encode(data).decode())
        for bad in [None,True,0,len(data)-1,len(data)+1]:
            with self.assertRaises(ValueError):self.store.finish(key,final_size=bad)
        out=self.store.finish(key,final_size=len(data));self.assertEqual(out['size'],len(data));self.assertEqual(out['path'].read_bytes(),data);self.assertEqual(out['sha256'],hashlib.sha256(data).hexdigest())
    def test_unknown_stream_still_obeys_maximum_bytes(self):
        self.store.STREAM_MAX_BYTES=4;key=self.store.begin('qa.bin','',None,streaming=True)['transferId']
        with self.assertRaises(ValueError):self.store.chunk(key,0,base64.b64encode(b'12345').decode())
        self.store.cancel(key);self.assertFalse(list(self.store.directory.glob('*.part')))
    def test_known_length_cannot_be_shortened_by_final_size(self):
        key=self.store.begin('qa.bin','',20)['transferId'];self.store.chunk(key,0,base64.b64encode(b'123').decode())
        with self.assertRaises(ValueError):self.store.finish(key,final_size=3)
    def test_page_content_bridge_preserves_streaming_opt_in(self):
        root=Path(__file__).resolve().parents[1]/'extension'
        for browser in ['chromium','firefox']:
            self.assertIn('streaming: d.streaming',(root/browser/'content.js').read_text())
            self.assertIn('streaming: msg.streaming',(root/browser/'background.js').read_text())
    def test_empty_stream_cannot_publish(self):
        key=self.store.begin('qa.bin','',None,streaming=True)['transferId']
        with self.assertRaises(ValueError):self.store.finish(key,final_size=0)
        self.store.cancel(key)
