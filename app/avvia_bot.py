"""Stable Windows launcher: GitHub releases, verified code-only updates and rollback."""
from contextlib import contextmanager
from pathlib import Path
from urllib import request, error, parse
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile

REPO = 'gae7799/Chat-gpt-1-bot'
API = 'https://api.github.com/repos/' + REPO
PROTOCOL = 1
MAX_PACKAGE = 8 * 1024 * 1024
MAX_EXPANDED = 16 * 1024 * 1024
ROOT = Path(__file__).resolve().parent
ALLOWED = {'bot.py','collega_fourthwall.py','connessione.py','consiglio_agenti.py',
           'direttore_autonomo.py','direzione_negozio.py','fourthwall_api.py',
           'gestione_ai.py','openai_vision.py','pubblicazione.py','registro.py',
           'analisi_giornaliera.py','versione.py','VERSION.txt'}


def version(text):
    if not isinstance(text,str) or not re.fullmatch(r'\d+\.\d+\.\d+',text):
        raise ValueError('Versione non valida')
    return tuple(map(int,text.split('.')))


def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,suffix='.tmp')
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def state_dir(root):
    folder=Path(root)/'DATI'/'AGGIORNAMENTI'
    folder.mkdir(parents=True,exist_ok=True)
    return folder


def log(root,message):
    folder=state_dir(root)
    # No URLs, response bodies, credentials or photos are logged.
    text=time.strftime('%Y-%m-%d %H:%M:%S')+' '+message
    atomic(folder/'stato.txt',text.encode('utf-8'))
    with (folder/'storico.txt').open('a',encoding='utf-8') as f:f.write(text+'\n')


@contextmanager
def lock(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    f=path.open('a+b')
    f.seek(0,2)
    if f.tell()==0:f.write(b'0');f.flush()
    f.seek(0)
    acquired=False
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        acquired=True
        yield
    finally:
        if acquired:
            f.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(f.fileno(),fcntl.LOCK_UN)
        f.close()


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def download(url,limit):
    opener=request.build_opener(NoRedirect())
    for _ in range(5):
        p=parse.urlsplit(url)
        if p.scheme!='https' or p.username or p.password or p.port not in (None,443):
            raise ValueError('Indirizzo aggiornamento non valido')
        if p.hostname not in {'api.github.com','github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'}:
            raise ValueError('Origine aggiornamento non consentita')
        req=request.Request(url,headers={'User-Agent':'BeyondTheNext-Updater/1','Accept':'application/vnd.github+json' if p.hostname=='api.github.com' else 'application/octet-stream'})
        try:
            with opener.open(req,timeout=12) as r:
                data=r.read(limit+1)
                if len(data)>limit:raise ValueError('Pacchetto troppo grande')
                return data
        except error.HTTPError as exc:
            if exc.code not in (301,302,303,307,308):raise
            url=parse.urljoin(url,exc.headers.get('Location',''))
    raise ValueError('Troppi reindirizzamenti')


def asset_url(release,name):
    matches=[a for a in release.get('assets',[]) if a.get('name')==name]
    if len(matches)!=1:raise ValueError('Allegato release mancante o duplicato')
    url=matches[0].get('browser_download_url','')
    prefix='https://github.com/'+REPO+'/releases/download/'+release['tag_name']+'/'
    if url!=prefix+name:raise ValueError('Allegato di origine non valida')
    return url


def check_release(root,fetch=download):
    release=json.loads(fetch(API+'/releases/latest',1024*1024))
    if release.get('draft') or release.get('prerelease'):return None
    tag=release.get('tag_name','')
    if not tag.startswith('v'):raise ValueError('Tag non valido')
    remote=tag[1:];version(remote)
    current=(Path(root)/'VERSION.txt').read_text().strip()
    if version(remote)<=version(current):return None
    blocked=state_dir(root)/'versione_bloccata.txt'
    if blocked.exists() and blocked.read_text().strip()==remote:return None
    manifest=json.loads(fetch(asset_url(release,'manifest.json'),65536))
    if manifest.get('version')!=remote or manifest.get('protocol')!=PROTOCOL:
        raise ValueError('Aggiornamento incompatibile con questo avvio')
    if manifest.get('min_python',[3,9])>list(sys.version_info[:2]):
        raise ValueError('Versione Python insufficiente')
    package=fetch(asset_url(release,'bot-foto-update.zip'),MAX_PACKAGE)
    if hashlib.sha256(package).hexdigest()!=manifest.get('sha256'):
        raise ValueError('Integrità aggiornamento non valida')
    return manifest,package


def verified_files(manifest,package):
    files=manifest.get('files')
    if not isinstance(files,dict) or not files or set(files)-ALLOWED or 'VERSION.txt' not in files:
        raise ValueError('File non consentiti nel pacchetto')
    result={};names=set();expanded=0
    with zipfile.ZipFile(io.BytesIO(package)) as z:
        for info in z.infolist():
            name=info.filename
            if name not in files or name.casefold() in names or info.is_dir():
                raise ValueError('Percorso o duplicato non consentito')
            names.add(name.casefold())
            if stat.S_ISLNK(info.external_attr>>16):raise ValueError('Collegamenti non consentiti')
            expanded+=info.file_size
            if expanded>MAX_EXPANDED:raise ValueError('Archivio espanso troppo grande')
            data=z.read(info)
            if hashlib.sha256(data).hexdigest()!=files[name]:raise ValueError('File corrotto')
            if name.endswith('.py'):compile(data,name,'exec')
            result[name]=data
    if set(result)!=set(files):raise ValueError('File mancanti')
    if result['VERSION.txt'].decode().strip()!=manifest['version']:raise ValueError('Versione discordante')
    return result


def restore(root):
    root=Path(root);folder=state_dir(root);journal=folder/'transazione.json'
    if not journal.exists():return False
    data=json.loads(journal.read_text())
    backup_name=data['backup']
    if not re.fullmatch(r'backup-[a-f0-9]{32}',backup_name):raise ValueError('Backup non valido')
    backup=folder/backup_name
    for name,existed in data['originals'].items():
        if name not in ALLOWED:raise ValueError('Ripristino non consentito')
        target=root/name
        if target.is_symlink():raise ValueError('Destinazione non valida')
        if existed:atomic(target,(backup/name).read_bytes())
        else:target.unlink(missing_ok=True)
    atomic(folder/'versione_bloccata.txt',data['version'].encode())
    journal.unlink()
    log(root,'Versione precedente ripristinata. Aggiornamento fallito escluso dai nuovi tentativi.')
    return True


def install(root,manifest,package,writer=atomic):
    root=Path(root);folder=state_dir(root)
    if (folder/'transazione.json').exists():raise ValueError('Ripristino necessario prima di aggiornare')
    files=verified_files(manifest,package)
    backup=folder/('backup-'+uuid.uuid4().hex);backup.mkdir()
    originals={}
    for name in files:
        target=root/name
        if target.is_symlink() or (target.exists() and not target.is_file()):raise ValueError('Destinazione non valida')
        originals[name]=target.exists()
        if target.exists():atomic(backup/name,target.read_bytes())
    record={'backup':backup.name,'version':manifest['version'],'originals':originals}
    atomic(folder/'transazione.json',json.dumps(record).encode())
    try:
        for name,data in files.items():writer(root/name,data)
    except Exception:
        restore(root)
        raise
    log(root,'Installata versione '+manifest['version']+'. Verifica avvio in corso.')


def confirm(root):
    (state_dir(root)/'transazione.json').unlink(missing_ok=True)
    log(root,'Avvio verificato. Versione '+(Path(root)/'VERSION.txt').read_text().strip()+' attiva.')


def start_child(root):
    ready=state_dir(root)/('pronto-'+uuid.uuid4().hex)
    env=os.environ.copy();env['BOT_FOTO_READY_FILE']=str(ready)
    child=subprocess.Popen([sys.executable,'-B',str(Path(root)/'bot.py')],cwd=root,env=env)
    deadline=time.monotonic()+40
    while time.monotonic()<deadline and child.poll() is None:
        if ready.exists():
            ready.unlink(missing_ok=True)
            return child,True
        time.sleep(.1)
    if child.poll() is None:
        child.terminate()
        try:child.wait(timeout=10)
        except subprocess.TimeoutExpired:child.kill();child.wait()
    ready.unlink(missing_ok=True)
    return child,False


def main(root=ROOT):
    root=Path(root);folder=state_dir(root)
    with lock(folder/'avvio.lock'):
        with lock(folder/'bot_attivo.lock'):
            restore(root) # recover any power loss before applying another version
            try:
                found=check_release(root)
                if found:install(root,*found)
                else:log(root,'Nessuna nuova versione installabile. Avvio del bot.')
            except Exception:
                if (folder/'transazione.json').exists():
                    restore(root) # if rollback fails, abort; never start mixed code
                log(root,'Aggiornamento non disponibile o non valido. Uso la versione installata.')
        child,healthy=start_child(root)
        if healthy:
            if (folder/'transazione.json').exists():confirm(root)
            return child.wait()
        if (folder/'transazione.json').exists():
            with lock(folder/'bot_attivo.lock'):restore(root)
            child,healthy=start_child(root)
            if healthy:return child.wait()
        log(root,'Avvio non riuscito. Consulta il registro; nessun dato personale è stato ripristinato o cancellato.')
        return 1


if __name__=='__main__':
    try:sys.exit(main())
    except OSError:
        print('Bot già aperto o cartella non accessibile. Chiudi le altre finestre e riprova.')
        sys.exit(1)
