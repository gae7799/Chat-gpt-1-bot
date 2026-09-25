"""Build only allowlisted program files; never include FOTO, DATI or credentials."""
from pathlib import Path
import hashlib
import json
import shutil
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from avvia_bot import ALLOWED, PROTOCOL, version


def build():
    app=ROOT/'app'; out=ROOT/'dist';out.mkdir(exist_ok=True)
    release=(app/'VERSION.txt').read_text().strip();version(release)
    files={}
    for name in sorted(ALLOWED):
        path=app/name
        if not path.is_file():raise RuntimeError('File mancante: '+name)
        data=path.read_bytes()
        if name.endswith('.py'):compile(data,name,'exec')
        files[name]=hashlib.sha256(data).hexdigest()
    archive=out/'bot-foto-update.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):z.write(app/name,name)
    manifest={'protocol':PROTOCOL,'version':release,'min_python':[3,9],
              'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':files}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    # A one-time installer also supplies the stable launcher and Windows shortcut.
    bundle=out/('Aggiornamento-Automatico-'+release)
    if bundle.exists():shutil.rmtree(bundle)
    payload=bundle/'NUOVI_FILE';payload.mkdir(parents=True)
    for name in sorted(ALLOWED|{'avvia_bot.py','AVVIA.bat'}):shutil.copy2(app/name,payload/name)
    for name in ('installa.ps1','INSTALLA_AGGIORNAMENTO.bat','ISTRUZIONI.txt'):
        shutil.copy2(ROOT/'installer'/name,bundle/name)
    with zipfile.ZipFile(out/('Aggiornamento-Automatico-'+release+'.zip'),'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(bundle.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(out))
    installer_zip=out/('Aggiornamento-Automatico-'+release+'.zip')
    # Single BAT for the existing Bot-Foto directory, pinned to the exact release bytes.
    launcher=(ROOT/'installer'/'AGGIORNA_E_AVVIA.bat.in').read_text()
    launcher=launcher.replace('__VERSION__',release).replace('__SHA256__',hashlib.sha256(installer_zip.read_bytes()).hexdigest())
    (out/'AGGIORNA_E_AVVIA.bat').write_bytes(launcher.replace('\n','\r\n').encode('ascii'))
    print('Pacchetti pronti in dist; versione '+release)


if __name__=='__main__':build()
