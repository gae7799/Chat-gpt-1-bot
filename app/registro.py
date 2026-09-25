"""Persistent local activity journal; stores outcomes, never prompts or credentials."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sqlite3
import os
import tempfile


def text_folder(catalog):
    folder = Path(catalog).parent / 'DIARIO_LOGICO'
    folder.mkdir(exist_ok=True)
    return folder


def save_texts(catalog):
    """Durable per-event text files; retry safely after a partial export."""
    folder = text_folder(catalog)
    with closing(connect(catalog)) as db:
        previous = db.execute("SELECT value FROM snapshots WHERE key='text_export_cursor'").fetchone()
        cursor = int(previous[0]) if previous else 0
        rows = db.execute('SELECT id,at,area,subject,outcome,details FROM events WHERE id>? ORDER BY id LIMIT 500', (cursor,)).fetchall()
        for event_id, at, area, subject, outcome, details in rows:
            destination = folder / f'evento-{event_id:09d}.txt'
            rendered = details
            prefix, sep, tail = details.partition('\n')
            try:
                value = json.loads(details if details.startswith('{') else tail)
                labels = {'ai_title':'Titolo prodotto', 'ai_description':'Descrizione prodotta',
                          'ai_theme':'Tema', 'ai_score':'Punteggio', 'ai_reason':'Motivazione',
                          'ai_recommended':'Selezionata (1=sì, 0=no)', 'proposed_at':'Data prevista',
                          'reason':'Motivazione', 'status':'Stato', 'first_name':'Foto'}
                rendered = (prefix + '\n' if sep and not details.startswith('{') else '') + '\n'.join(
                    f'{labels.get(k,k)}: {v}' for k,v in value.items() if v is not None)
            except (ValueError, AttributeError):
                pass
            content = (f'BEYOND THE NEXT — EVENTO {event_id}\nData UTC: {at}\nArea: {area}\n'
                       f'Oggetto: {subject}\nEsito: {outcome}\n\n{rendered}\n\n'
                       'Registro di dati, azioni e spiegazioni disponibili; non ragionamento interno del modello.\n')
            fd, temporary = tempfile.mkstemp(prefix='diario-', suffix='.tmp', dir=folder)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, destination)
            finally:
                if os.path.exists(temporary): os.unlink(temporary)
            cursor = event_id
        if rows:
            with db:
                db.execute("INSERT INTO snapshots(key,value) VALUES ('text_export_cursor',?) ON CONFLICT(key) DO UPDATE SET value=CAST(MAX(CAST(value AS INTEGER),CAST(excluded.value AS INTEGER)) AS TEXT)", (str(cursor),))
    return len(rows)


def logical_review(catalog, moment=None):
    """About five factual notes in five minutes, at most 50 per rolling window."""
    moment = moment or datetime.now(timezone.utc)
    with closing(connect(catalog)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        previous = db.execute("SELECT value FROM snapshots WHERE key='review_time'").fetchone()
        if previous and 0 <= moment.timestamp() - float(previous[0]) < 60:
            return False
        window_start = (moment - timedelta(minutes=5)).isoformat(timespec='seconds')
        recent = db.execute("""SELECT COUNT(*) FROM events
            WHERE area='Diario logico' AND outcome='Riepilogo periodico' AND at>?""",
            (window_start,)).fetchone()[0]
        if recent >= 50:
            return False
        seq_row = db.execute("SELECT value FROM snapshots WHERE key='review_sequence'").fetchone()
        seq = int(seq_row[0]) if seq_row else 0
        items = db.execute("SELECT key,value FROM snapshots WHERE key LIKE 'photo:%' OR key LIKE 'plan:%' OR key='setting:director_auto_enabled'").fetchall()
        photos = [json.loads(v) for k,v in items if k.startswith('photo:')]
        plans = [json.loads(v) for k,v in items if k.startswith('plan:')]
        enabled = any(k=='setting:director_auto_enabled' and json.loads(v).get('valore')=='1' for k,v in items)
        awaiting = [p for p in plans if p.get('status')=='Approvata']
        next_date = min((p.get('proposed_at','') for p in awaiting), default='nessuna')
        role = ('fotografia','marketing','progetto','critica')[seq % 4]
        specialist = db.execute("SELECT value FROM snapshots WHERE key LIKE 'advisor:%:' || ? ORDER BY key DESC LIMIT 1", (role,)).fetchone()
        if specialist:
            review = json.loads(specialist[0])
            specialist_note = (f'Specialista {role}: ho riletto il parere già registrato per '
                               f'{review.get("first_name", "foto")}. Valutazione: '
                               f'{review.get("assessment", "non disponibile")}. '
                               f'Azione proposta allora: {review.get("action", "nessuna azione proposta")}.'
                               + (' Criticità bloccante: non proporre la stampa.' if review.get('blocks') else ''))
        else:
            specialist_note = f'Specialista {role}: non ci sono pareri già registrati da rileggere; nessuna nuova analisi AI.'
        recent_actions = db.execute("""SELECT at,area,subject,outcome FROM events
            WHERE area<>'Diario logico' ORDER BY id DESC LIMIT 3""").fetchall()
        actions = ('\n'.join(f'- {at}: {area} / {subject}: {outcome}'
                             for at,area,subject,outcome in recent_actions)
                   if recent_actions else '- Nessuna azione separata registrata.')
        signal = db.execute('SELECT at,phase FROM live WHERE id=1').fetchone()
        live = f'{signal[1]} (segnale delle {signal[0]})' if signal else 'non ancora disponibile'
        text = (f'CONTROLLO ESEGUITO: ho letto lo stato salvato del catalogo, del calendario e dei pareri degli specialisti.\n'
                f'Ultima fase segnalata dal programma: {live}.\n\n'
                f'ESITO CATALOGO: {len(photos)} fotografie registrate; '
                f'{sum(p.get("ai_status")=="Analizzata" for p in photos)} analisi AI completate; '
                f'{sum(p.get("ai_recommended")==1 for p in photos)} selezioni AI; '
                f'{sum(bool(p.get("product_id")) for p in photos)} prodotti collegati.\n'
                f'ESITO CALENDARIO: gestione {"attiva" if enabled else "sospesa o non configurata"}; '
                f'{len(awaiting)} proposte approvate in attesa; prima data prevista {next_date}; '
                f'{sum(p.get("status")=="Pubblicata" for p in plans)} pubblicazioni registrate dal bot.\n\n'
                f'PARERE CONSULTATO: {specialist_note}\n\n'
                f'ULTIME AZIONI EFFETTIVE NEL REGISTRO:\n{actions}\n\n'
                'Lettura dello stato locale: questa voce non è una nuova analisi artistica, '
                'non verifica Fourthwall e non pubblica o modifica prodotti.')
        db.execute('INSERT INTO events(at,area,subject,outcome,details) VALUES (?,?,?,?,?)',
                   (moment.isoformat(timespec='seconds'),'Diario logico','Stato del lavoro','Riepilogo periodico',text))
        db.execute("INSERT OR REPLACE INTO snapshots VALUES ('review_time',?)",(str(moment.timestamp()),))
        db.execute("INSERT OR REPLACE INTO snapshots VALUES ('review_sequence',?)",(str(seq + 1),))
    return True


def connect(catalog):
    path = Path(catalog).with_name('registro_attivita.sqlite')
    db = sqlite3.connect(path, timeout=2)
    db.executescript('''
      CREATE TABLE IF NOT EXISTS events(
        id INTEGER PRIMARY KEY, at TEXT NOT NULL, area TEXT NOT NULL,
        subject TEXT NOT NULL, outcome TEXT NOT NULL, details TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS snapshots(key TEXT PRIMARY KEY, value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS live(id INTEGER PRIMARY KEY CHECK(id=1), at TEXT, phase TEXT);
    ''')
    return db


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def record(catalog, area, subject, outcome, details=''):
    with closing(connect(catalog)) as db, db:
        db.execute('INSERT INTO events(at,area,subject,outcome,details) VALUES (?,?,?,?,?)',
                   (now(), area, subject, outcome, details))
        db.execute('INSERT OR REPLACE INTO live VALUES (1,?,?)', (now(), outcome))


def heartbeat(catalog, phase):
    with closing(connect(catalog)) as db, db:
        db.execute('INSERT OR REPLACE INTO live VALUES (1,?,?)', (now(), phase))


def capture(catalog):
    """Archive only changes; existing data is explicitly labeled as a first snapshot."""
    observations = []
    with closing(sqlite3.connect(catalog, timeout=2)) as source:
        source.row_factory = sqlite3.Row
        tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'photos' in tables:
            allowed = ('sha','first_name','status','product_id','ai_status','ai_title',
                       'ai_description','ai_theme','ai_score','ai_recommended','ai_reason','ai_analyzed_at')
            columns = {r[1] for r in source.execute('PRAGMA table_info(photos)')}
            selected = [c for c in allowed if c in columns]
            for row in source.execute('SELECT ' + ','.join(selected) + ' FROM photos'):
                item = dict(row)
                if not item.get('sha'):
                    continue
                observations.append(('photo:' + item['sha'], 'Fotografie',
                    item.get('ai_title') or item['first_name'], item.get('status') or '', item))
        if 'director_plan' in tables:
            for row in source.execute('SELECT id,title,product_id,proposed_at,reason,status FROM director_plan'):
                item = dict(row)
                observations.append(('plan:' + str(item['id']), 'Calendario', item['title'], item['status'], item))
        if 'advisor_reviews' in tables and 'photos' in tables:
            for row in source.execute('''SELECT a.sha,p.first_name,a.role,a.assessment,a.action,a.blocks
                FROM advisor_reviews a JOIN photos p ON p.sha=a.sha'''):
                item = dict(row)
                observations.append(('advisor:' + item['sha'] + ':' + item['role'],
                    'Specialisti', item['first_name'] + ' — ' + item['role'],
                    'Criticità bloccante' if item['blocks'] else 'Valutazione', item))
        if 'bot_settings' in tables:
            for key, value in source.execute("SELECT key,value FROM bot_settings WHERE key IN ('director_auto_enabled','auto_enabled','advertising_budget_eur')"):
                observations.append(('setting:' + key, 'Impostazioni', key, value, {'valore':value}))
        if 'ai_usage' in tables:
            for day, count in source.execute('SELECT day,analyses FROM ai_usage'):
                observations.append(('usage:' + day, 'Consumo AI', day, f'{count} tentativi', {'tentativi':count}))
    with closing(connect(catalog)) as db, db:
        for key, area, subject, outcome, item in observations:
            value = json.dumps(item, ensure_ascii=False, sort_keys=True)
            previous = db.execute('SELECT value FROM snapshots WHERE key=?', (key,)).fetchone()
            if previous and previous[0] == value:
                continue
            details = ('Prima rilevazione; non indica la data originale della decisione.\n' if not previous else '') + value
            db.execute('INSERT INTO events(at,area,subject,outcome,details) VALUES (?,?,?,?,?)',
                       (now(),area,subject,outcome,details))
            db.execute('INSERT OR REPLACE INTO snapshots VALUES (?,?)', (key,value))


def export_json(catalog, destination):
    with closing(connect(catalog)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute('SELECT * FROM events ORDER BY id')
        with open(destination, 'w', encoding='utf-8') as output:
            output.write('[\n')
            separator = ''
            for row in rows:
                output.write(separator + json.dumps(dict(row), ensure_ascii=False))
                separator = ',\n'
            output.write('\n]\n')


def observe(catalog):
    """Logging failure must not change the result of a remote operation."""
    try:
        capture(catalog)
        return True
    except (sqlite3.Error, OSError):
        return False


def open_registry(parent, catalog):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    window = tk.Toplevel(parent)
    window.title('Beyond The Next | Registro attività')
    window.geometry('1080x720')
    body = ttk.Frame(window, padding=16); body.pack(fill='both', expand=True)
    ttk.Label(body, text='Registro attività', font=('Segoe UI',20,'bold')).pack(anchor='w')
    status = tk.StringVar(value='Caricamento...')
    ttk.Label(body, textvariable=status, wraplength=1000).pack(anchor='w', pady=8)
    ttk.Label(body, text='Circa 5 riepiloghi in 5 minuti (massimo 50 in 5 minuti); le azioni reali sono sempre registrate. Orari UTC.').pack(anchor='w')
    search = tk.StringVar()
    controls = ttk.Frame(body); controls.pack(fill='x', pady=8)
    ttk.Label(controls, text='Cerca:').pack(side='left')
    ttk.Entry(controls, textvariable=search, width=40).pack(side='left', padx=8)
    def export():
        path = filedialog.asksaveasfilename(parent=window, defaultextension='.json', initialfile='registro-attivita.json')
        if path:
            try:
                export_json(catalog,path)
                messagebox.showinfo('Registro','Storico completo esportato.',parent=window)
            except (OSError,sqlite3.Error):
                messagebox.showerror('Registro','Esportazione non riuscita.',parent=window)
    ttk.Button(controls,text='Esporta tutto (JSON)',command=export).pack(side='left')
    def open_texts():
        try:
            os.startfile(str(text_folder(catalog)))
        except (OSError, AttributeError):
            messagebox.showinfo('Diario',str(Path(catalog).parent / 'DIARIO_LOGICO'),parent=window)
    ttk.Button(controls,text='Apri diario TXT',command=open_texts).pack(side='left',padx=8)
    table = ttk.Treeview(body,columns=('at','area','subject','outcome'),show='headings',height=15)
    for col,label,width in [('at','Data UTC',180),('area','Area',110),('subject','Opera / attività',270),('outcome','Esito',350)]:
        table.heading(col,text=label); table.column(col,width=width)
    scroll = ttk.Scrollbar(body,orient='vertical',command=table.yview)
    table.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right',fill='y'); table.pack(fill='both',expand=True)
    details = tk.Text(body,height=9,wrap='word',state='disabled'); details.pack(fill='x',pady=8)
    cache = {}
    def selected(event=None):
        ids = table.selection()
        if ids:
            details.configure(state='normal'); details.delete('1.0','end')
            details.insert('end',cache.get(ids[0],'')); details.configure(state='disabled')
    table.bind('<<TreeviewSelect>>', selected)
    timer = None
    def refresh():
        nonlocal timer
        try:
            with closing(connect(catalog)) as db:
                term = search.get().strip()
                rows = db.execute('''SELECT id,at,area,subject,outcome,details FROM events
                    WHERE instr(lower(subject || ' ' || outcome || ' ' || details || ' ' || area),lower(?))>0
                    ORDER BY id DESC LIMIT 50''',(term,)).fetchall()
                live = db.execute('SELECT at,phase FROM live WHERE id=1').fetchone()
            wanted = {str(row[0]) for row in rows}
            for iid in table.get_children():
                if iid not in wanted: table.delete(iid)
            cache.clear()
            for event_id,at,area,subject,outcome,detail in rows:
                iid = str(event_id); cache[iid] = detail
                if not table.exists(iid): table.insert('','end',iid=iid,values=(at,area,subject,outcome))
            order = tuple(str(row[0]) for row in rows)
            if table.get_children() != order: table.set_children('',*order)
            status.set((f'Ultimo segnale: {live[0]} — {live[1]}. ' if live else 'Nessun segnale registrato. ') +
                       f'{len(rows)} eventi visualizzati (massimo 50); esportazione dello storico completo.')
        except sqlite3.Error:
            status.set('Registro temporaneamente occupato: nuovo tentativo tra 2 secondi.')
        timer = window.after(2000,refresh)
    def close():
        if timer: window.after_cancel(timer)
        window.destroy()
    window.protocol('WM_DELETE_WINDOW',close)
    refresh()
