"""Fourthwall hidden-draft creation, manual and autonomous queue."""
import queue, sqlite3, threading, time
from pathlib import Path
from fourthwall_api import ApiError,list_templates,template_details,upload_image,create_hidden_draft
from connessione import Vault

AUTO_INTERVAL = 20
RETRY_SECONDS = 300

BRAND_NAME = 'Beyond The Next'

def _title(filename):
    text=Path(filename).stem.replace('_',' ').strip()
    if text.lower().startswith(('dsc ', 'img ')):
        text=f'{BRAND_NAME} — Opera {text.split()[-1]}'
    return text[:120] or f'{BRAND_NAME} — Opera fotografica'

def _description():
    return ('Opera fotografica selezionata da Beyond The Next. '
            'Stampa artistica realizzata su richiesta.')

def _db_connect(path):
    db=sqlite3.connect(path,timeout=15)
    db.execute('CREATE TABLE IF NOT EXISTS bot_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    db.execute('''CREATE TABLE IF NOT EXISTS operation_log(
      id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT DEFAULT CURRENT_TIMESTAMP,
      sha TEXT, action TEXT NOT NULL, outcome TEXT NOT NULL, message TEXT)''')
    cols={r[1] for r in db.execute('PRAGMA table_info(photos)')}
    for name,definition in [('image_id','TEXT'),('product_id','TEXT'),('template_id','TEXT'),('retry_count','INTEGER DEFAULT 0'),('next_retry','INTEGER DEFAULT 0'),('metadata_version','INTEGER DEFAULT 0'),('legacy_product_id','TEXT'),('replacement_product_id','TEXT'),('replacement_title','TEXT'),('formatted_product_id','TEXT'),('formatted_size','TEXT'),('ai_status','TEXT'),('ai_title','TEXT'),('ai_description','TEXT'),('ai_theme','TEXT'),('ai_score','INTEGER'),('ai_recommended','INTEGER'),('ai_reason','TEXT'),('ai_analyzed_at','TEXT')]:
        if name not in cols: db.execute(f'ALTER TABLE photos ADD COLUMN {name} {definition}')
    db.commit(); return db

def _get_setting(db,key,default=None):
    row=db.execute('SELECT value FROM bot_settings WHERE key=?',(key,)).fetchone()
    return row[0] if row else default

def _set_setting(db,key,value):
    db.execute('INSERT OR REPLACE INTO bot_settings(key,value) VALUES (?,?)',(key,str(value)))

def _log(db,sha,action,outcome,message=''):
    db.execute('INSERT INTO operation_log(sha,action,outcome,message) VALUES (?,?,?,?)',(sha,action,outcome,str(message)[:500]))

def _create_one(db_path,photos_root,sha,rel,template_id,margin):
    from registro import observe
    path=Path(photos_root)/rel
    if not path.is_file(): raise ApiError('La fotografia non è più presente.')
    pair=Vault().load()
    if not pair: raise ApiError('Credenziali Fourthwall non trovate: usa Collega e salva.')
    db=_db_connect(db_path)
    try:
        row=db.execute('SELECT image_id,product_id,ai_title,ai_description FROM photos WHERE sha=?',(sha,)).fetchone()
        if not row: raise ApiError('Fotografia non presente nel catalogo.')
        if row[1]: return ('already',rel,row[1])
        image_id=row[0]; ai_title=row[2]; ai_description=row[3]
        db.execute('UPDATE photos SET status=? WHERE sha=?',('Caricamento su Fourthwall...',sha)); db.commit()
    finally: db.close()
    observe(db_path)
    if not image_id:
        image_id=upload_image(path,*pair)
        db=_db_connect(db_path)
        try:
            db.execute('UPDATE photos SET image_id=?,status=? WHERE sha=?',(image_id,'Immagine caricata; creazione bozza...',sha)); db.commit()
        finally: db.close()
        observe(db_path)
    _,region=template_details(template_id)
    product_id=create_hidden_draft(*pair,template_id,region,image_id,ai_title or _title(rel),ai_description or _description(),margin)
    db=_db_connect(db_path)
    try:
        db.execute('''UPDATE photos SET image_id=?,product_id=?,template_id=?,status=?,retry_count=0,next_retry=0,metadata_version=1 WHERE sha=?''',
          (image_id,product_id,template_id,'Bozza professionale nascosta creata su Fourthwall',sha))
        _log(db,sha,'create_hidden_draft','success',product_id); db.commit()
    finally: db.close()
    observe(db_path)
    return ('created',rel,product_id)

def mount(parent,root,table,db_path,photos_root):
    import tkinter as tk
    from tkinter import ttk,messagebox
    db=_db_connect(db_path); db.close()
    panel=ttk.LabelFrame(parent,text='Prodotti Fourthwall - bozze nascoste',padding=10)
    panel.pack(fill='x',pady=8,before=table)
    ttk.Label(panel,text='Modalità manuale o coda automatica. I prodotti restano nascosti.').grid(row=0,column=0,columnspan=5,sticky='w')
    ttk.Label(panel,text='Modello').grid(row=1,column=0,sticky='w',pady=(8,2))
    model=tk.StringVar(); combo=ttk.Combobox(panel,textvariable=model,state='readonly',width=55); combo.grid(row=2,column=0,columnspan=2,sticky='ew')
    ttk.Label(panel,text='Guadagno aggiunto (USD)').grid(row=1,column=2,sticky='w',padx=8,pady=(8,2))
    margin=tk.StringVar(value='10.00'); ttk.Entry(panel,textvariable=margin,width=12).grid(row=2,column=2,sticky='w',padx=8)
    state=tk.StringVar(value='Carica i modelli oppure attiva la coda usando il modello della prima bozza.')
    ttk.Label(panel,textvariable=state,wraplength=900).grid(row=5,column=0,columnspan=5,sticky='w',pady=(7,0))
    auto_state=tk.StringVar()
    ttk.Label(panel,textvariable=auto_state,font=('Segoe UI',9,'bold')).grid(row=4,column=0,columnspan=5,sticky='w',pady=(7,0))
    results=queue.Queue(); models={}; busy=[False]; next_auto=[0]
    buttons=[]

    def read_auto():
        db=_db_connect(db_path)
        try: return _get_setting(db,'auto_enabled','0')=='1'
        finally: db.close()
    def refresh_auto_label(): auto_state.set('Coda automatica: ATTIVA' if read_auto() else 'Coda automatica: in pausa')
    def run(fn,automatic=False):
        if busy[0]: return False
        busy[0]=True
        for b in buttons: b.configure(state='disabled')
        def worker():
            try: results.put(('ok',fn(),automatic))
            except Exception as e: results.put(('error',str(e) if isinstance(e,ApiError) else 'Operazione non riuscita; nessuna credenziale mostrata.',automatic))
        threading.Thread(target=worker,daemon=True).start(); return True
    def load_models():
        state.set('Caricamento modelli Fourthwall...'); run(lambda:('models',list_templates()))
    def selected_photo():
        sel=table.selection()
        if len(sel)!=1: raise ApiError('Seleziona una sola fotografia nella tabella.')
        sha=sel[0]; db=_db_connect(db_path)
        try: row=db.execute('SELECT path FROM files WHERE sha=? AND present=1 ORDER BY path LIMIT 1',(sha,)).fetchone()
        finally: db.close()
        if not row: raise ApiError('Il file selezionato non è più presente.')
        return sha,row[0]
    def parse_margin():
        try: value=float(margin.get().replace(',','.'))
        except ValueError: raise ApiError('Inserisci un guadagno valido.')
        if value<0 or value>1000: raise ApiError('Inserisci un guadagno tra 0 e 1000 USD.')
        return value
    def prepare_manual():
        try:
            sha,rel=selected_photo(); choice=models.get(model.get()); value=parse_margin()
            if not choice: raise ApiError('Carica e scegli un modello poster.')
        except ApiError as e: messagebox.showerror('Dati mancanti',str(e),parent=root); return
        if not messagebox.askyesno('Crea bozza nascosta',f'Caricare “{rel}” e creare una bozza nascosta?\n\nModello: {choice["name"]}\nGuadagno: {value:.2f} USD',parent=root): return
        state.set('Creazione bozza in corso. Non chiudere il programma...')
        run(lambda:_create_one(db_path,photos_root,sha,rel,choice['productId'],value))
    def enable_auto():
        try: value=parse_margin()
        except ApiError as e: messagebox.showerror('Guadagno',str(e),parent=root); return
        db=_db_connect(db_path)
        try:
            row=db.execute("SELECT template_id FROM photos WHERE product_id IS NOT NULL AND template_id IS NOT NULL ORDER BY rowid DESC LIMIT 1").fetchone()
            template_id=row[0] if row else None
        finally: db.close()
        if not template_id:
            messagebox.showerror('Modello mancante','Crea prima una bozza manuale riuscita.',parent=root); return
        if not messagebox.askyesno('Attiva coda automatica',f'Il bot creerà automaticamente bozze NASCOSTE per le foto in attesa.\n\nIntervallo minimo: {AUTO_INTERVAL} secondi\nGuadagno: {value:.2f} USD\n\nNon pubblicherà prodotti.',parent=root): return
        db=_db_connect(db_path)
        try:
            _set_setting(db,'auto_enabled','1'); _set_setting(db,'auto_template_id',template_id); _set_setting(db,'auto_margin',value); _log(db,None,'auto_queue','enabled'); db.commit()
        finally: db.close()
        next_auto[0]=0; refresh_auto_label(); state.set('Coda automatica attiva: preparo la prossima foto in attesa.')
    def pause_auto():
        db=_db_connect(db_path)
        try: _set_setting(db,'auto_enabled','0'); _log(db,None,'auto_queue','paused'); db.commit()
        finally: db.close()
        refresh_auto_label(); state.set('Coda automatica in pausa. L’operazione già iniziata terminerà.')
    def next_candidate():
        now=int(time.time()); db=_db_connect(db_path)
        try:
            template_id=_get_setting(db,'auto_template_id'); value=float(_get_setting(db,'auto_margin','10'))
            autonomous=_get_setting(db,'director_auto_enabled','0')=='1'
            condition="AND p.ai_status='Analizzata' AND COALESCE(p.ai_recommended,0)=1" if autonomous else ''
            rows=db.execute(f'''SELECT p.sha,f.path FROM photos p JOIN files f ON p.sha=f.sha
              WHERE f.present=1 AND (p.product_id IS NULL OR p.product_id='') AND COALESCE(p.next_retry,0)<=?
              {condition} ORDER BY p.created,f.path''',(now,)).fetchall()
            for sha,rel in rows:
                if Path(rel).suffix.lower() in ('.jpg','.jpeg','.png'): return sha,rel,template_id,value
            return None
        finally: db.close()
    def auto_action(item):
        sha,rel,template_id,value=item
        try:
            if not template_id: raise ApiError('Modello automatico mancante.')
            return _create_one(db_path,photos_root,sha,rel,template_id,value)
        except Exception as exc:
            message=str(exc) if isinstance(exc,ApiError) else 'Operazione automatica non riuscita.'
            db=_db_connect(db_path)
            try:
                row=db.execute('SELECT COALESCE(retry_count,0) FROM photos WHERE sha=?',(sha,)).fetchone()
                retries=(row[0] if row else 0)+1
                delay=min(3600,RETRY_SECONDS*(2**min(retries-1,3)))
                db.execute('UPDATE photos SET retry_count=?,next_retry=?,status=? WHERE sha=?',
                  (retries,int(time.time()+delay),'Errore temporaneo; nuovo tentativo programmato',sha))
                _log(db,sha,'create_hidden_draft','error',message); db.commit()
            finally: db.close()
            raise ApiError(message)
    def auto_tick():
        if read_auto() and not busy[0] and time.time()>=next_auto[0]:
            item=next_candidate()
            if item:
                state.set('Coda automatica: elaborazione di '+item[1]); run(lambda:auto_action(item),True)
            else: state.set('Coda automatica attiva: nessuna foto JPG/PNG pronta.')
        root.after(2000,auto_tick)
    load=ttk.Button(panel,text='Carica modelli poster',command=load_models); load.grid(row=2,column=3,sticky='e')
    create=ttk.Button(panel,text='Crea bozza dalla foto selezionata',command=prepare_manual); create.grid(row=3,column=0,columnspan=2,sticky='w',pady=(8,0))
    enable=ttk.Button(panel,text='Attiva coda automatica',command=enable_auto); enable.grid(row=3,column=2,sticky='w',padx=8,pady=(8,0))
    pause=ttk.Button(panel,text='Metti in pausa',command=pause_auto); pause.grid(row=3,column=3,sticky='w',pady=(8,0))
    buttons.extend([load,create,enable,pause])
    def poll():
        try:
            while True:
                kind,data,automatic=results.get_nowait(); busy[0]=False
                for b in buttons: b.configure(state='normal')
                if kind=='error':
                    state.set(('Coda automatica: ' if automatic else '')+data)
                    if automatic:
                        next_auto[0]=time.time()+RETRY_SECONDS
                        # Retry delay is global; row remains eligible after restart.
                    continue
                if data[0]=='models':
                    rows=data[1]; preferred=[r for r in rows if any(k in (str(r.get('name',''))+' '+str(r.get('category',''))).lower() for k in ('poster','print','wall art'))]
                    use=preferred or rows; models.clear()
                    for r in use:
                        price=r.get('basePrice') or {}; label=f"{r['name']} — {r.get('category','')} — {price.get('amount','?')} {price.get('currency','')}"; models[label]=r
                    combo['values']=list(models)
                    if models: combo.current(0)
                    state.set(f'{len(use)} modelli adatti trovati.')
                elif data[0] in ('created','already'):
                    state.set(('Coda automatica: ' if automatic else '')+('bozza nascosta creata per ' if data[0]=='created' else 'bozza già registrata per ')+data[1])
                    if automatic: next_auto[0]=time.time()+AUTO_INTERVAL
        except queue.Empty: pass
        root.after(250,poll)
    refresh_auto_label(); root.after(250,poll); root.after(2000,auto_tick)
