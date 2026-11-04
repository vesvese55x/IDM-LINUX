import importlib.util
import json
import os
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('publisher',Path(__file__).resolve().parents[1]/'publish_existing_release.py')
publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)


def package_bytes(name, value):
    data=bytearray([value]*2048)
    if name.endswith('.exe'):
        data[:2]=b'MZ';struct.pack_into('<I',data,0x3c,128);data[128:132]=b'PE\0\0';struct.pack_into('<H',data,132,0x8664);struct.pack_into('<H',data,128+24+68,2)
    elif name.endswith('.deb'): data[:8]=b'!<arch>\n'
    elif name.endswith('.rpm'): data[:4]=b'\xed\xab\xee\xdb'
    elif name.endswith('.zst'): data[:4]=b'\x28\xb5\x2f\xfd'
    else: data[:4]=b'\x7fELF'
    return bytes(data)

class ReleaseGateTests(unittest.TestCase):
    def scenario(self, fail=False):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        directory=Path(tmp.name)/'assets';directory.mkdir();backup=Path(tmp.name)/'backup'
        remote={n:package_bytes(n,1) for n in publisher.NAMES};original=dict(remote)
        for name in publisher.NAMES: (directory/name).write_bytes(package_bytes(name,2))
        def run(*args,output=False):
            if args[:2]==('gh','api'):
                return json.dumps({'assets':[{'name':n,'size':len(b)} for n,b in remote.items()]})
            if args[1:3]==('release','download'):
                name=args[args.index('--pattern')+1];target=Path(args[args.index('--dir')+1]);target.mkdir(exist_ok=True);(target/name).write_bytes(remote[name]);return 0
            if args[1:3]==('release','upload'):
                path=Path(args[4]);name=path.name
                if fail and path.parent==directory and name==publisher.NAMES[1]:
                    remote.pop(name,None)
                    raise subprocess.CalledProcessError(1,args)
                remote[name]=path.read_bytes();return 0
            self.fail('Unexpected publication command')
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':publisher.REPOSITORY}),patch.object(publisher,'run',side_effect=run),patch('builtins.print'):
            if fail:
                with self.assertRaises(subprocess.CalledProcessError): publisher.publish(directory,backup)
                self.assertEqual(remote,original)
            else:
                publisher.publish(directory,backup)
                self.assertEqual(remote,{n:package_bytes(n,2) for n in publisher.NAMES})
        self.assertEqual({n:(backup/n).read_bytes() for n in publisher.NAMES},original)

    def test_failed_second_upload_restores_both_attempted_assets(self): self.scenario(True)
    def test_all_five_updated_and_redownload_verified(self): self.scenario(False)
    def test_missing_package_blocks_publication_before_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError): publisher.verify(Path(tmp))

if __name__=='__main__':unittest.main(verbosity=2)
