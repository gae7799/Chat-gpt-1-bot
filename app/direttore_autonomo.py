from contextlib import closing
"""Shop director: reconcile Fourthwall visibility before scheduled releases."""
from datetime import datetime, timedelta
import sqlite3
from registro import observe

BRAND = 'Beyond The Next'
from versione import VERSION

PROFILES = {
    'Radici elettriche': ('astrazione naturale', 'verticale', 100,
        'Apre la linea con un impatto cromatico forte e definisce subito l’identità visiva.'),
    'Shara': ('paesaggio marino', 'quadrato', 92,
        'Prosegue con un’immagine ampia e riconoscibile, cambiando ritmo e formato.'),
    'Sotto la volta': ('architettura', 'verticale', 86,
        'Introduce struttura e profondità dopo due opere dominate dal colore.'),
    'Me and Sea': ('paesaggio e figure', 'orizzontale', 82,
        'Porta una presenza umana e amplia il racconto della collezione.'),
    'Vita nell’acquario': ('organico', 'verticale', 78,
        'Chiude il primo ciclo con un soggetto fragile e misterioso, adatto a riaprire l’attenzione.'),
}


def _connect(db_path):
    db = sqlite3.connect(db_path, timeout=15)
    db.execute('CREATE TABLE IF NOT EXISTS bot_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    db.execute('''CREATE TABLE IF NOT EXISTS director_plan(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      product_id TEXT NOT NULL, title TEXT NOT NULL, position INTEGER NOT NULL,
      proposed_at TEXT NOT NULL, reason TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'Proposta',
      created TEXT DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(product_id, proposed_at))''')
    db.execute('''CREATE TABLE IF NOT EXISTS director_runs(
      id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT DEFAULT CURRENT_TIMESTAMP,
      mode TEXT NOT NULL, outcome TEXT NOT NULL, message TEXT)''')
    db.commit()
    return db


def _next_friday_evening(now):
    candidate = now.replace(hour=18, minute=30, second=0, microsecond=0)
    days = (4 - candidate.weekday()) % 7
    candidate += timedelta(days=days)
    if candidate <= now + timedelta(days=2):
        candidate += timedelta(days=7)
    return candidate


def _catalog_products(db):
    from direzione_negozio import _metadata
    rows = db.execute("""SELECT first_name,product_id,COALESCE(metadata_version,0)
      FROM photos WHERE COALESCE(product_id,'')<>''""").fetchall()
    products = []
    for filename, product_id, version in rows:
        title = _metadata(filename)[0]
        if version >= 1 and title in PROFILES:
            products.append((title, product_id))
    return products


def generate_plan(db_path, force=False, now=None):
    """Create a local proposal. It never calls Fourthwall or publishes products."""
    now = now or datetime.now()
    db = _connect(db_path)
    try:
        existing = db.execute("SELECT COUNT(*) FROM director_plan WHERE status<>'Sostituita'").fetchone()[0]
        if existing and not force:
            return existing, False
        products = _catalog_products(db)
        if len(products) < 5 and not existing:
            raise RuntimeError('La collezione di lancio non contiene ancora tutte le cinque opere registrate.')
        if force:
            finished = {row[0] for row in db.execute("SELECT DISTINCT product_id FROM director_plan WHERE status IN ('Pubblicata','Già pubblica')")}
            products = [item for item in products if item[1] not in finished]
            db.execute("UPDATE director_plan SET status='Sostituita' WHERE status IN ('Proposta','Approvata')")
        if not products:
            db.commit()
            return 0, False
        ordered = sorted(products, key=lambda row: (-PROFILES[row[0]][2], row[0]))
        start = _next_friday_evening(now)
        for position, (title, product_id) in enumerate(ordered, 1):
            theme, orientation, score, reason = PROFILES[title]
            proposed = start + timedelta(days=7 * (position - 1))
            full_reason = f'{reason} Tema: {theme}; formato: {orientation}; distanza: 7 giorni.'
            db.execute('''INSERT INTO director_plan(product_id,title,position,proposed_at,reason,status)
              VALUES (?,?,?,?,?,'Proposta')''',
              (product_id, title, position, proposed.isoformat(timespec='minutes'), full_reason))
        db.execute("INSERT INTO director_runs(mode,outcome,message) VALUES ('simulazione','success',?)",
                   (f'Creato piano locale di {len(ordered)} opere; nessuna pubblicazione.',))
        db.execute("INSERT OR REPLACE INTO bot_settings(key,value) VALUES ('director_mode','simulation')")
        db.commit()
        observe(db_path)
        return len(ordered), True
    except Exception as exc:
        db.execute("INSERT INTO director_runs(mode,outcome,message) VALUES ('simulazione','error',?)", (str(exc)[:500],))
        db.commit()
        raise
    finally:
        db.close()


def schedule_ai_products(db_path, now=None):
    """Append AI-selected hidden products to the calendar without duplicates."""
    now = now or datetime.now()
    db = _connect(db_path)
    try:
        cols = {row[1] for row in db.execute('PRAGMA table_info(photos)')}
        if 'ai_status' not in cols: return 0
        rows = db.execute('''SELECT product_id,ai_title,ai_theme,ai_reason FROM photos
          WHERE COALESCE(product_id,'')<>'' AND ai_status='Analizzata' AND COALESCE(ai_recommended,0)=1
          AND product_id NOT IN (SELECT product_id FROM director_plan) ORDER BY ai_score DESC,created''').fetchall()
        if not rows: return 0
        last = db.execute("SELECT MAX(proposed_at) FROM director_plan WHERE status IN ('Proposta','Approvata')").fetchone()[0]
        start = datetime.fromisoformat(last) + timedelta(days=7) if last else _next_friday_evening(now)
        auto = db.execute("SELECT value FROM bot_settings WHERE key='director_auto_enabled'").fetchone()
        status = 'Approvata' if auto and auto[0] == '1' else 'Proposta'
        position = db.execute("SELECT COALESCE(MAX(position),0) FROM director_plan WHERE status<>'Sostituita'").fetchone()[0]
        for offset, (product_id, title, theme, reason) in enumerate(rows):
            proposed = start + timedelta(days=7 * offset)
            db.execute('''INSERT INTO director_plan(product_id,title,position,proposed_at,reason,status)
              VALUES (?,?,?,?,?,?)''',
              (product_id, title, position + offset + 1, proposed.isoformat(timespec='minutes'),
               f'{reason} Tema: {theme}. Inserita automaticamente dopo le opere già programmate.', status))
        db.commit()
        observe(db_path)
        return len(rows)
    finally: db.close()


def compact_pending_plan(db_path, now=None):
    """Fill freed Friday slots without moving any approved release later."""
    now = now or datetime.now()
    db = _connect(db_path)
    try:
        enabled = db.execute("SELECT value FROM bot_settings WHERE key='director_auto_enabled'").fetchone()
        if not enabled or enabled[0] != '1': return 0
        rows = db.execute("""SELECT id,title,proposed_at FROM director_plan
          WHERE status IN ('Proposta','Approvata') ORDER BY proposed_at,position""").fetchall()
        if not rows: return 0
        # Never rewrite an overdue decision: publish_due handles it separately.
        if any(datetime.fromisoformat(row[2]) <= now for row in rows): return 0
        slot = _next_friday_evening(now)
        moved = 0
        for plan_id, title, old_text in rows:
            old = datetime.fromisoformat(old_text)
            new = min(old, slot)
            if new < old:
                db.execute("UPDATE director_plan SET proposed_at=? WHERE id=?", (new.isoformat(timespec='minutes'),plan_id))
                db.execute("INSERT INTO director_runs(mode,outcome,message) VALUES ('calendario','rescheduled',?)",
                           (f'{title}: da {old_text} a {new.isoformat(timespec="minutes")}; slot liberato da opere già pubbliche.',))
                moved += 1
            slot = new + timedelta(days=7)
        db.commit()
    finally: db.close()
    if moved: observe(db_path)
    return moved


def _mark_already_public(db_path, plan_id, title):
    db = _connect(db_path)
    try:
        db.execute("UPDATE director_plan SET status='Già pubblica' WHERE id=? AND status IN ('Proposta','Approvata')", (plan_id,))
        if db.execute('SELECT changes()').fetchone()[0]:
            db.execute("INSERT INTO director_runs(mode,outcome,message) VALUES ('allineamento','already_public',?)",
                       (f'Già pubblica su Fourthwall: {title}',))
        db.commit()
    finally: db.close()
    observe(db_path)


def reconcile_plan(db_path, product_getter=None, credential_loader=None):
    """Recognize products already public, matching exact Fourthwall IDs."""
    db = _connect(db_path)
    try:
        enabled = db.execute("SELECT value FROM bot_settings WHERE key='director_auto_enabled'").fetchone()
        if not enabled or enabled[0] != '1': return 0
        rows = db.execute("""SELECT id,product_id,title FROM director_plan
          WHERE status IN ('Proposta','Approvata') ORDER BY position""").fetchall()
    finally: db.close()
    if not rows: return 0
    if product_getter is None or credential_loader is None:
        from connessione import Vault
        from fourthwall_api import get_product_access
        product_getter = product_getter or get_product_access
        credential_loader = credential_loader or (lambda: Vault().load())
    pair = credential_loader()
    if not pair: raise RuntimeError('Credenziali Fourthwall non trovate.')
    found = 0
    for plan_id, product_id, title in rows:
        if product_getter(*pair,product_id) == 'PUBLIC':
            _mark_already_public(db_path,plan_id,title)
            found += 1
    return found


def publish_due(db_path, now=None, product_setter=None, collection_setter=None, credential_loader=None, product_getter=None):
    """Publish due approved products only when full autonomy was explicitly enabled."""
    now = now or datetime.now()
    db = _connect(db_path)
    try:
        enabled = db.execute("SELECT value FROM bot_settings WHERE key='director_auto_enabled'").fetchone()
        if not enabled or enabled[0] != '1': return 0
        rows = db.execute("""SELECT id,product_id,title FROM director_plan
          WHERE status='Approvata' AND proposed_at<=? ORDER BY proposed_at""",
          (now.isoformat(timespec='minutes'),)).fetchall()
        collection = db.execute("SELECT value FROM bot_settings WHERE key='launch_collection_id'").fetchone()
    finally: db.close()
    if not rows: return 0
    if product_setter is None or credential_loader is None or product_getter is None:
        from connessione import Vault
        from fourthwall_api import get_product_access, set_product_public, set_collection_available
        product_setter = product_setter or set_product_public
        collection_setter = collection_setter or set_collection_available
        product_getter = product_getter or get_product_access
        credential_loader = credential_loader or (lambda: Vault().load())
    pair = credential_loader()
    if not pair: raise RuntimeError('Credenziali Fourthwall non trovate.')
    published = 0
    def still_enabled():
        with closing(sqlite3.connect(db_path, timeout=15)) as current:
            setting = current.execute("SELECT value FROM bot_settings WHERE key='director_auto_enabled'").fetchone()
            return bool(setting and setting[0] == '1')
    for plan_id, product_id, title in rows:
        if not still_enabled(): break
        access = product_getter(*pair, product_id)
        if access == 'PUBLIC':
            _mark_already_public(db_path,plan_id,title)
            continue
        if access != 'HIDDEN':
            raise RuntimeError(f'{title}: stato Fourthwall {access}; pubblicazione sospesa.')
        if not still_enabled(): break
        product_setter(*pair, product_id)
        if product_getter(*pair, product_id) != 'PUBLIC':
            raise RuntimeError(f'{title}: pubblicazione non confermata da Fourthwall; verifica lo shop.')
        db = _connect(db_path)
        try:
            db.execute("UPDATE director_plan SET status='Pubblicata' WHERE id=?", (plan_id,))
            db.execute("INSERT INTO director_runs(mode,outcome,message) VALUES ('autonomo','published',?)",
                       (f'Pubblicata: {title}',))
            db.commit()
        finally: db.close()
        from registro import observe
        observe(db_path)
        published += 1
    if published and collection and collection[0] and collection_setter and still_enabled():
        collection_setter(*pair, collection[0], True)
    return published


def open_director(parent, db_path):
    import tkinter as tk
    from tkinter import ttk, messagebox

    window = tk.Toplevel(parent)
    window.title(f'{BRAND} | Direttore autonomo {VERSION}')
    window.geometry('1080x620')
    frame = ttk.Frame(window, padding=18)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Direttore autonomo', font=('Segoe UI', 20, 'bold')).pack(anchor='w')
    mode_state = tk.StringVar(value='Controllo dello stato della gestione autonoma...')
    mode_label = ttk.Label(frame, textvariable=mode_state, font=('Segoe UI', 10, 'bold'))
    mode_label.pack(anchor='w', pady=(2, 12))
    from analisi_giornaliera import open_report, retry_report
    ttk.Button(frame, text='Rapporto e proposta editoriale', command=lambda:open_report(window, db_path)).pack(anchor='w', pady=4)
    ttk.Button(frame, text='Riprova rapporto', command=lambda:retry_report(window, db_path)).pack(anchor='w', pady=4)
    table = ttk.Treeview(frame, columns=('position','title','date','status','reason'), show='headings')
    for key, label, width in [
        ('position','Ordine',60), ('title','Opera',170), ('date','Momento consigliato',160),
        ('status','Stato',105), ('reason','Motivazione',520)]:
        table.heading(key, text=label)
        table.column(key, width=width, anchor='w')
    table.pack(fill='both', expand=True)
    info = tk.StringVar(value='Il piano viene conservato sul PC e aggiornato senza modificare Fourthwall.')
    ttk.Label(frame, textvariable=info, wraplength=1000).pack(anchor='w', pady=(10, 0))

    def refresh():
        for item in table.get_children():
            table.delete(item)
        db = _connect(db_path)
        try:
            rows = db.execute("""SELECT id,position,title,proposed_at,status,reason FROM director_plan
              WHERE status<>'Sostituita' ORDER BY position""").fetchall()
            enabled = db.execute("SELECT value FROM bot_settings WHERE key='director_auto_enabled'").fetchone()
            budget = db.execute("SELECT value FROM bot_settings WHERE key='advertising_budget_eur'").fetchone()
        finally:
            db.close()
        for row_id, position, title, proposed_at, status, reason in rows:
            shown = datetime.fromisoformat(proposed_at).strftime('%d/%m/%Y alle %H:%M')
            table.insert('', 'end', iid=str(row_id), values=(position, title, shown, status, reason))
        if enabled and enabled[0] == '1':
            mode_state.set(f'GESTIONE AUTONOMA: ATTIVA — Pubblicità: {budget[0] if budget else "0"} €')
            mode_label.configure(foreground='#087830')
        else:
            mode_state.set('GESTIONE AUTONOMA: SOSPESA — Nessuna pubblicazione automatica')
            mode_label.configure(foreground='#9a4e00')
        published = sum(1 for row in rows if row[4] == 'Pubblicata')
        already = sum(1 for row in rows if row[4] == 'Già pubblica')
        info.set(f'{len(rows)} opere nel piano; {published} pubblicate dal bot, {already} già online.')

    def build(force=False):
        if force and not messagebox.askyesno('Nuovo piano','Sostituire il piano attuale con una nuova simulazione?',parent=window):
            return
        try:
            count, created = generate_plan(db_path, force=force)
            refresh()
            messagebox.showinfo('Direttore autonomo',
                f'Piano di {count} opere pronto.' if created else 'Il piano attuale è già pronto.', parent=window)
        except Exception as exc:
            messagebox.showerror('Piano non creato', str(exc), parent=window)

    def approve():
        selected = table.selection()
        if len(selected) != 1:
            messagebox.showinfo('Approva','Seleziona una proposta.',parent=window)
            return
        db = _connect(db_path)
        try:
            db.execute("UPDATE director_plan SET status='Approvata' WHERE id=?", (int(selected[0]),))
            db.commit()
        finally:
            db.close()
        refresh()
        info.set('Proposta approvata localmente. Il prodotto è ancora nascosto su Fourthwall.')
        observe(db_path)

    def enable_full():
        try:
            from openai_vision import OpenAIVault
            if not OpenAIVault().load():
                messagebox.showerror('OpenAI mancante','Prima usa Collega OpenAI nella schermata principale.',parent=window); return
        except Exception as exc:
            messagebox.showerror('OpenAI',str(exc),parent=window); return
        warning = ('Attivare la gestione autonoma completa?\n\nIl bot analizzerà fino a 5 nuove foto al giorno, '
                   'creerà bozze selezionate e renderà pubbliche le opere approvate alle date indicate.\n\n'
                   'Pubblicità e spesa pubblicitaria restano bloccate a 0 € senza eccezioni.')
        if not messagebox.askyesno('Gestione autonoma completa',warning,parent=window): return
        db = _connect(db_path)
        try:
            template = db.execute("SELECT template_id FROM photos WHERE COALESCE(template_id,'')<>'' ORDER BY rowid DESC LIMIT 1").fetchone()
            if not template:
                messagebox.showerror('Modello mancante','Non trovo un modello poster già usato.',parent=window); return
            db.execute("INSERT OR REPLACE INTO bot_settings(key,value) VALUES ('director_auto_enabled','1')")
            db.execute("INSERT OR REPLACE INTO bot_settings(key,value) VALUES ('advertising_budget_eur','0')")
            db.execute("INSERT OR REPLACE INTO bot_settings(key,value) VALUES ('auto_enabled','1')")
            db.execute("INSERT OR REPLACE INTO bot_settings(key,value) VALUES ('auto_template_id',?)",(template[0],))
            db.commit()
        finally: db.close()
        refresh()
        info.set('Il bot lavorerà quando il PC è acceso. Pubblicità e spesa pubblicitaria: 0 €.')
        observe(db_path)
        messagebox.showinfo('Beyond The Next','Gestione autonoma completa attivata. Le date già approvate restano valide.',parent=window)

    def disable_full():
        db = _connect(db_path)
        try:
            db.execute("INSERT OR REPLACE INTO bot_settings(key,value) VALUES ('director_auto_enabled','0')")
            db.execute("INSERT OR REPLACE INTO bot_settings(key,value) VALUES ('auto_enabled','0')")
            db.commit()
        finally: db.close()
        observe(db_path)
        refresh()
        info.set('Gestione autonoma sospesa. Nessuna nuova analisi o pubblicazione automatica.')

    actions = ttk.Frame(frame)
    actions.pack(fill='x', pady=(10, 0))
    ttk.Button(actions, text='Genera piano', command=lambda:build(False)).pack(side='left')
    ttk.Button(actions, text='Rigenera piano', command=lambda:build(True)).pack(side='left', padx=8)
    ttk.Button(actions, text='Approva proposta selezionata', command=approve).pack(side='left')
    ttk.Button(actions, text='Attiva gestione completa', command=enable_full).pack(side='left', padx=(16,8))
    ttk.Button(actions, text='Sospendi automazione', command=disable_full).pack(side='left')
    ttk.Button(actions, text='Chiudi', command=window.destroy).pack(side='right')
    refresh()
