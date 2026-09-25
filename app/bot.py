"""Beyond The Next store manager: local intake and hidden Fourthwall drafts."""
from pathlib import Path
import hashlib
import os
import queue
import sqlite3
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent
from versione import VERSION
EXTENSIONS = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.webp'}

class Catalog:
    def __init__(self, root):
        self.root = Path(root)
        (self.root / 'FOTO').mkdir(exist_ok=True)
        (self.root / 'DATI').mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / 'DATI' / 'catalogo.sqlite', timeout=15)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS photos (
          sha TEXT PRIMARY KEY, first_name TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP,
          status TEXT NOT NULL DEFAULT 'In attesa del modulo pubblicazione');
        CREATE TABLE IF NOT EXISTS files (
          path TEXT PRIMARY KEY, sha TEXT NOT NULL, size INTEGER, mtime INTEGER,
          present INTEGER DEFAULT 1);
        ''')
        for column in ('image_id','product_id','template_id'):
            try: self.db.execute(f'ALTER TABLE photos ADD COLUMN {column} TEXT')
            except sqlite3.OperationalError: pass
        self.db.commit()
        self.observed = {}

    def scan(self):
        errors = []
        seen = set()
        for path in sorted((self.root / 'FOTO').rglob('*')):
            if path.is_symlink() or not path.is_file() or path.suffix.lower() not in EXTENSIONS:
                continue
            rel = str(path.relative_to(self.root / 'FOTO'))
            seen.add(rel)
            try:
                before = path.stat()
                stamp = (before.st_size, before.st_mtime_ns)
                # Wait for two observations and an old enough timestamp before reading a copy.
                if self.observed.get(rel) != stamp or time.time() - before.st_mtime < 5:
                    self.observed[rel] = stamp
                    continue
                old = self.db.execute('SELECT size, mtime FROM files WHERE path=?', (rel,)).fetchone()
                if old == stamp:
                    self.db.execute('UPDATE files SET present=1 WHERE path=? AND present<>1', (rel,))
                    continue
                digest = hashlib.sha256()
                with path.open('rb') as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        digest.update(chunk)
                after = path.stat()
                if (after.st_size, after.st_mtime_ns) != stamp:
                    continue
                if not before.st_size:
                    errors.append(rel + ': file vuoto')
                    continue
                sha = digest.hexdigest()
                self.db.execute('INSERT OR IGNORE INTO photos(sha, first_name) VALUES (?,?)', (sha, rel))
                self.db.execute('INSERT OR REPLACE INTO files VALUES (?,?,?,?,1)', (rel, sha, *stamp))
            except OSError:
                errors.append(rel + ': lettura non riuscita, riprovo al prossimo ciclo')
        for (rel,) in self.db.execute('SELECT path FROM files').fetchall():
            if rel not in seen:
                self.db.execute('UPDATE files SET present=0 WHERE path=?', (rel,))
        self.db.commit()
        self.observed = {name: stamp for name, stamp in self.observed.items() if name in seen}
        rows = self.db.execute('''SELECT p.sha, MIN(f.path), COUNT(*), p.status
          FROM photos p JOIN files f ON p.sha=f.sha WHERE f.present=1
          GROUP BY p.sha ORDER BY MIN(f.path)''').fetchall()
        return rows, errors


def sync_table(table, rows):
    """Update only changed rows, preserving selection and scroll position."""
    existing = set(table.get_children())
    incoming = {row[0] for row in rows}
    for item in existing - incoming:
        table.delete(item)
    for sha, name, copies, state in rows:
        values = (name, copies, state)
        if sha not in existing:
            table.insert('', 'end', iid=sha, values=values)
        elif tuple(map(str, table.item(sha, 'values'))) != tuple(map(str, values)):
            table.item(sha, values=values)
    order = tuple(row[0] for row in rows)
    if tuple(table.get_children()) != order:
        table.set_children('', *order)


def startup(enable):
    if os.name != 'nt':
        raise RuntimeError('Funzione disponibile solo su Windows.')
    folder = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Startup'
    target = folder / 'BeyondTheNextBot.bat'
    old_target = folder / 'GaetanoBotFoto.bat'
    if enable:
        if '%' in str(ROOT):
            raise RuntimeError('Sposta il bot in una cartella senza il carattere %.')
        target.write_text('@echo off\nchcp 65001 >nul\ncall "' + str(ROOT / 'AVVIA.bat') + '"\n', encoding='utf-8')
        old_target.unlink(missing_ok=True)
    else:
        target.unlink(missing_ok=True)
        old_target.unlink(missing_ok=True)


def main():
    import tkinter as tk
    from tkinter import ttk, messagebox
    root = tk.Tk()
    root.title(f'Beyond The Next | Gestione negozio {VERSION}')
    root.geometry('1000x800')
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Beyond The Next', font=('Segoe UI', 23, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='Direzione automatica del negozio fotografico', font=('Segoe UI', 11, 'bold')).pack(anchor='w')
    ttk.Label(frame, text=f'Versione {VERSION} · Cartella attiva: {ROOT}', wraplength=940).pack(anchor='w')
    ttk.Label(frame, text='Metti le immagini in FOTO. Controllo automatico ogni 15 secondi.').pack(anchor='w', pady=8)
    ttk.Label(frame, text='Coda locale attiva. Puoi creare bozze nascoste manualmente o con la coda automatica; pubblicazione resta separata.').pack(anchor='w')
    from connessione import mount
    mount(frame, root)
    actions = ttk.Frame(frame)
    actions.pack(fill='x', pady=15)
    def open_photos():
        os.startfile(str(ROOT / 'FOTO'))
    ttk.Button(actions, text='Apri FOTO', command=open_photos).pack(side='left')
    def connect():
        subprocess.Popen([sys.executable, str(ROOT / 'collega_fourthwall.py')], cwd=ROOT)
    def set_startup(value):
        try:
            startup(value)
            messagebox.showinfo('Avvio', 'Avvio al login Windows attivato. Mantieni il bot in questa cartella.' if value else 'Avvio automatico disattivato.')
        except Exception as error:
            messagebox.showerror('Avvio', str(error))
    ttk.Button(actions, text='Attiva avvio con Windows', command=lambda:set_startup(True)).pack(side='left')
    ttk.Button(actions, text='Disattiva', command=lambda:set_startup(False)).pack(side='left', padx=8)
    from direzione_negozio import open_manager
    ttk.Button(actions, text='Lista del negozio', command=lambda:open_manager(root, ROOT / 'DATI' / 'catalogo.sqlite', ROOT / 'FOTO')).pack(side='left', padx=8)
    from direttore_autonomo import open_director
    ttk.Button(actions, text='Direttore autonomo', command=lambda:open_director(root, ROOT / 'DATI' / 'catalogo.sqlite')).pack(side='left')
    tools_row = ttk.Frame(frame)
    tools_row.pack(fill='x', pady=(0, 8))
    from consiglio_agenti import open_council
    ttk.Button(tools_row, text='Quattro specialisti', command=lambda:open_council(root, ROOT / 'DATI' / 'catalogo.sqlite')).pack(side='left', padx=8)
    from openai_vision import open_setup
    ttk.Button(tools_row, text='Collega OpenAI', command=lambda:open_setup(root)).pack(side='left', padx=8)
    from analisi_giornaliera import open_report, open_marketing_report
    ttk.Button(tools_row, text='Rapporto giornaliero', command=lambda:open_report(root, ROOT / 'DATI' / 'catalogo.sqlite')).pack(side='left', padx=8)
    ttk.Button(tools_row, text='Studio marketing', command=lambda:open_marketing_report(root, ROOT / 'DATI' / 'catalogo.sqlite')).pack(side='left', padx=8)
    def update_status():
        path = ROOT / 'DATI' / 'AGGIORNAMENTI' / 'stato.txt'
        text = path.read_text(encoding='utf-8') if path.exists() else 'Avvia con AVVIA.bat per controllare gli aggiornamenti.'
        messagebox.showinfo('Aggiornamenti automatici', text + '\nRepository: gae7799/Chat-gpt-1-bot\nIl controllo avviene a ogni avvio con AVVIA.bat.', parent=root)
    ttk.Button(tools_row, text='Aggiornamenti', command=update_status).pack(side='left', padx=4)
    from registro import open_registry
    ttk.Button(tools_row, text='Registro attività', command=lambda:open_registry(root, ROOT / 'DATI' / 'catalogo.sqlite')).pack(side='left', padx=8)
    table = ttk.Treeview(frame, columns=('name', 'copies', 'state'), show='headings')
    for key, label, width in [('name','File',350), ('copies','Copie',60), ('state','Stato',380)]:
        table.heading(key, text=label)
        table.column(key, width=width)
    table.pack(fill='both', expand=True)
    from pubblicazione import mount as mount_publishing
    mount_publishing(frame, root, table, ROOT / 'DATI' / 'catalogo.sqlite', ROOT / 'FOTO')
    status = tk.StringVar(value='Avvio del controllo...')
    ttk.Label(frame, textvariable=status, wraplength=850).pack(anchor='w', pady=12)
    ttk.Label(frame, text='Gli originali restano in FOTO. Le copie identiche vengono raggruppate.\nChiudendo questa finestra il controllo si ferma.').pack(anchor='w')
    stop = threading.Event()
    results = queue.Queue()
    from registro import record, heartbeat, observe, save_texts, logical_review
    db_path = ROOT / 'DATI' / 'catalogo.sqlite'
    last_logged = {}
    actors = {
        'Sessione': 'Supervisore Bot-Foto',
        'Catalogo foto': 'Scanner FOTO',
        'Errore catalogo': 'Scanner FOTO',
        'Analisi AI': 'Direttore AI e specialisti',
        'Errore AI': 'Direttore AI',
        'Limite AI': 'Gestore quota AI',
        'Calendario': 'Direttore autonomo',
        'Errore pubblicazione': 'Direttore autonomo',
        'Rapporto giornaliero': 'Coordinatore rapporto giornaliero',
        'Analisi giornaliera': 'Coordinatore rapporto giornaliero',
    }
    def journal(area, outcome, details=''):
        stamp = time.monotonic()
        key = (area, outcome)
        if (area.startswith('Errore') or area == 'Limite AI') and stamp - last_logged.get(key, -300) < 300:
            return
        try:
            record(db_path, area, 'Bot', outcome, details, actor=actors.get(area, 'Supervisore Bot-Foto'))
            last_logged[key] = stamp
        except (sqlite3.Error, OSError):
            results.put(('error', 'Registro attività non disponibile: controlla accesso e spazio in DATI.'))
    def phase(label):
        try:
            heartbeat(db_path, label)
        except (sqlite3.Error, OSError):
            results.put(('error', 'Impossibile aggiornare il segnale del registro.'))
    def worker():
        catalog = None
        last_store_sync = 0
        last_ai_check = 0
        last_director_check = 0
        last_photo_count = None
        diary_started = False
        try:
            catalog = Catalog(ROOT)
            journal('Sessione', 'Avvio del bot')
            def daily_worker():
                from analisi_giornaliera import run_daily
                previous_stage = None
                while not stop.is_set():
                    try:
                        stage = run_daily(db_path)
                        if stage != previous_stage:
                            journal('Rapporto giornaliero', f'Fase: {stage}',
                                    'La fase è stata eseguita o riletta; consulta Rapporto giornaliero per dati e fonti.')
                            previous_stage = stage
                    except Exception:
                        journal('Analisi giornaliera', 'Rapporto non aggiornato: controllare DATI e connessione')
                    stop.wait(60)
            threading.Thread(target=daily_worker, daemon=True).start()
            def marketing_worker():
                from analisi_giornaliera import marketing_continuo
                while not stop.is_set():
                    try:
                        marketing_continuo(db_path)
                    except (sqlite3.Error, OSError, ValueError):
                        journal('Studio marketing', 'Rapporto non aggiornato: controllare DATI e DOCUMENTI_MARKETING')
                    stop.wait(60)
            threading.Thread(target=marketing_worker, daemon=True).start()
            def diary_worker():
                next_note = time.monotonic()
                while not stop.is_set():
                    try:
                        logical_review(db_path)
                        save_texts(db_path)
                    except (sqlite3.Error, OSError):
                        results.put(('error', 'Diario temporaneamente non disponibile: nuovo tentativo tra 5 secondi.'))
                        next_note = time.monotonic() + 5
                    else:
                        next_note = max(next_note + 60, time.monotonic() + 1)
                    stop.wait(max(0, next_note - time.monotonic()))
            try:
                from direttore_autonomo import generate_plan
                generate_plan(ROOT / 'DATI' / 'catalogo.sqlite')
            except Exception:
                journal('Calendario', 'Piano iniziale non generato: controllare la collezione nel direttore')
            while not stop.is_set():
                try:
                    phase('Controllo della cartella FOTO')
                    rows, errors = catalog.scan()
                    results.put(('ok', (rows, errors)))
                    if len(rows) != last_photo_count:
                        journal('Catalogo foto', f'{len(rows)} fotografie uniche presenti',
                                'Scansione della cartella FOTO completata. Le copie identiche vengono raggruppate. '
                                f'File non leggibili nel ciclo: {len(errors)}.')
                        last_photo_count = len(rows)
                    if not observe(db_path):
                        results.put(('error', 'Registro: acquisizione del catalogo non riuscita.'))
                    if not diary_started:
                        threading.Thread(target=diary_worker, daemon=True).start()
                        diary_started = True
                    if time.monotonic() - last_ai_check >= 60:
                        last_ai_check = time.monotonic()
                        try:
                            from gestione_ai import process_next
                            phase('Controllo coda e disponibilità analisi AI')
                            outcome = process_next(ROOT / 'DATI' / 'catalogo.sqlite', ROOT / 'FOTO')
                            phase('Limite giornaliero AI raggiunto' if outcome and outcome[0] == 'limit' else 'Controllo AI completato')
                            if outcome and outcome[0] == 'analyzed':
                                result = outcome[2]
                                journal('Analisi AI', f'Foto valutata: {outcome[1]}',
                                        f'Titolo proposto: {result["title"]}. Punteggio: {result["score"]}/100. '
                                        f'Selezionata: {"sì" if result["recommended"] else "no"}. '
                                        f'Motivazione: {result["reason"]}. Quattro pareri salvati nel Consiglio degli specialisti.')
                            elif outcome and outcome[0] == 'limit':
                                journal('Limite AI', 'Cinque analisi raggiunte oggi; nuove foto in attesa',
                                        'Nessuna ulteriore chiamata OpenAI per le fotografie fino al prossimo giorno.')
                        except Exception as exc:
                            journal('Errore AI', 'Analisi non completata: verificare chiave, credito e collegamento')
                            results.put(('error', 'Direttore AI: ' + str(exc)))
                    if time.monotonic() - last_director_check >= 60:
                        last_director_check = time.monotonic()
                        try:
                            from direttore_autonomo import schedule_ai_products, publish_due, reconcile_plan, compact_pending_plan
                            phase('Verifica calendario e pubblicazioni in scadenza')
                            if time.monotonic() - last_store_sync >= 300:
                                last_store_sync = time.monotonic()
                                phase('Allineamento prodotti pubblici con Fourthwall')
                                reconcile_plan(ROOT / 'DATI' / 'catalogo.sqlite')
                            moved = compact_pending_plan(ROOT / 'DATI' / 'catalogo.sqlite')
                            scheduled = schedule_ai_products(ROOT / 'DATI' / 'catalogo.sqlite')
                            published = publish_due(ROOT / 'DATI' / 'catalogo.sqlite')
                            if moved or scheduled or published:
                                journal('Calendario', 'Piano aggiornato',
                                        f'Scadenze ricollocate: {moved or 0}; nuove opere pianificate: '
                                        f'{scheduled or 0}; prodotti pubblicati e confermati: {published or 0}. '
                                        'Dettagli delle opere disponibili nel Direttore autonomo.')
                        except Exception as exc:
                            journal('Errore pubblicazione', 'Operazione non completata: verificare stato del negozio')
                            results.put(('error', 'Pubblicazione autonoma: ' + str(exc)))
                    if not observe(db_path):
                        results.put(('error', 'Registro: acquisizione delle decisioni non riuscita.'))
                    phase('Ciclo completato; attesa del prossimo controllo')
                except Exception:
                    journal('Errore catalogo', 'Controllo FOTO o DATI non riuscito')
                    results.put(('error', 'Controllo non riuscito. Verifica accesso a FOTO e DATI; nuovo tentativo fra 15 secondi.'))
                stop.wait(15)
        except Exception:
            results.put(('error', 'Impossibile aprire il catalogo. Estrai tutto lo ZIP in una cartella scrivibile.'))
        finally:
            if catalog:
                catalog.db.close()
    def poll():
        try:
            while True:
                kind, data = results.get_nowait()
                if kind == 'error':
                    status.set(data)
                else:
                    rows, errors = data
                    sync_table(table, rows)
                    status.set(f'{len(rows)} immagini uniche in coda - ultimo controllo {time.strftime("%H:%M:%S")}' + (' | ' + '; '.join(errors[:2]) if errors else ''))
        except queue.Empty:
            pass
        root.after(300, poll)
    def close():
        stop.set()
        journal('Sessione', 'Chiusura richiesta; eventuali operazioni in corso vanno verificate al riavvio')
        root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    def start_ready():
        ready = os.environ.get('BOT_FOTO_READY_FILE')
        if ready:
            from avvia_bot import atomic
            atomic(Path(ready), b'ready')
        threading.Thread(target=worker, daemon=True).start()
    root.after(100, start_ready)
    root.after(300, poll)
    root.mainloop()

if __name__ == '__main__':
    from avvia_bot import lock, state_dir
    with lock(state_dir(ROOT) / 'bot_attivo.lock'):
        main()
