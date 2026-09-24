from pathlib import Path
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from avvia_bot import (install,restore,confirm,verified_files,check_release,lock,
                       state_dir,REPO,PROTOCOL,atomic,start_child)


def package(files=None,version='2.0.1'):
    files=files or {'bot.py':b'print("new")\n','VERSION.txt':(version+'\n').encode()}
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:
        for name,data in files.items():z.writestr(name,data)
    data=buf.getvalue()
    return {'version':version,'protocol':PROTOCOL,'min_python':[3,9],
            'sha256':hashlib.sha256(data).hexdigest(),
            'files':{k:hashlib.sha256(v).hexdigest() for k,v in files.items()}},data


class UpdaterTests(unittest.TestCase):
    def root(self,folder):
        root=Path(folder)
        (root/'VERSION.txt').write_text('2.0.0\n')
        (root/'bot.py').write_text('print("old")\n')
        (root/'FOTO').mkdir();(root/'FOTO/originale.jpg').write_bytes(b'photo')
        (root/'DATI').mkdir();(root/'DATI/catalogo.sqlite').write_bytes(b'private database')
        return root

    def test_install_confirm_preserves_personal_data(self):
        with tempfile.TemporaryDirectory() as f:
            root=self.root(f);install(root,*package());confirm(root)
            self.assertEqual((root/'VERSION.txt').read_text().strip(),'2.0.1')
            self.assertEqual((root/'FOTO/originale.jpg').read_bytes(),b'photo')
            self.assertEqual((root/'DATI/catalogo.sqlite').read_bytes(),b'private database')
            self.assertFalse((state_dir(root)/'transazione.json').exists())

    def test_write_failure_rolls_back_every_file(self):
        with tempfile.TemporaryDirectory() as f:
            root=self.root(f)
            def fail(path,data):
                if path.name=='VERSION.txt':raise OSError('disk full')
                atomic(path,data)
            with self.assertRaises(OSError):install(root,*package(),writer=fail)
            self.assertEqual((root/'bot.py').read_text(),'print("old")\n')
            self.assertEqual((root/'VERSION.txt').read_text(),'2.0.0\n')
            self.assertEqual((state_dir(root)/'versione_bloccata.txt').read_text(),'2.0.1')

    def test_power_loss_recovered_from_journal(self):
        with tempfile.TemporaryDirectory() as f:
            root=self.root(f);install(root,*package())
            self.assertTrue(restore(root));self.assertFalse(restore(root))
            self.assertEqual((root/'VERSION.txt').read_text().strip(),'2.0.0')

    def test_archive_cannot_touch_data_or_escape(self):
        for name in ('../bot.py','DATI/catalogo.sqlite','FOTO/a.jpg','avvia_bot.py','C:\\bot.py'):
            manifest,data=package({name:b'evil','VERSION.txt':b'2.0.1\n'})
            with self.assertRaises(ValueError):verified_files(manifest,data)

    def test_hash_and_syntax_validation_before_changes(self):
        m,d=package();m['files']['bot.py']='0'*64
        with self.assertRaises(ValueError):verified_files(m,d)
        m,d=package({'bot.py':b'this is invalid syntax!','VERSION.txt':b'2.0.1\n'})
        with self.assertRaises(SyntaxError):verified_files(m,d)

    def test_release_version_and_digest_verified(self):
        with tempfile.TemporaryDirectory() as f:
            root=self.root(f);m,d=package()
            base='https://github.com/'+REPO+'/releases/download/v2.0.1/'
            release={'tag_name':'v2.0.1','assets':[{'name':n,'browser_download_url':base+n} for n in ('manifest.json','bot-foto-update.zip')]}
            def fetch(url,limit):
                if url.endswith('/latest'):return json.dumps(release).encode()
                if url.endswith('manifest.json'):return json.dumps(m).encode()
                return d
            self.assertEqual(check_release(root,fetch)[0]['version'],'2.0.1')
            m['sha256']='0'*64
            with self.assertRaises(ValueError):check_release(root,fetch)
            (root/'VERSION.txt').write_text('2.0.2')
            self.assertIsNone(check_release(root,fetch))

    def test_lock_prevents_concurrent_launcher(self):
        with tempfile.TemporaryDirectory() as f:
            path=Path(f)/'lock'
            with lock(path):
                with self.assertRaises(OSError):
                    with lock(path):pass
            with lock(path):pass

    def test_startup_handshake_and_crash(self):
        with tempfile.TemporaryDirectory() as f:
            root=Path(f)
            (root/'bot.py').write_text('import os,time\nfrom pathlib import Path\nPath(os.environ["BOT_FOTO_READY_FILE"]).write_text("ready")\ntime.sleep(1)\n')
            child,ok=start_child(root)
            self.assertTrue(ok);child.wait(timeout=5)
            (root/'bot.py').write_text('raise SystemExit(1)\n')
            child,ok=start_child(root)
            self.assertFalse(ok)


if __name__=='__main__':unittest.main()
