"""Local shop direction and safe professional-draft replacement workflow."""
import queue
import re
import sqlite3
import threading
import time
from pathlib import Path

BRAND = 'Beyond The Next'
LAUNCH_TITLES = ('Sotto la volta','Radici elettriche','Me and Sea','Shara','Vita nell’acquario')

PROFESSIONAL = {
    'caserta  1752': ('Sotto la volta', 'Una prospettiva verticale attraversa l’architettura barocca e conduce lo sguardo verso la luce. Opera fotografica selezionata da Beyond The Next.'),
    'dsc_0216': ('Radici elettriche', 'Il paesaggio naturale si trasforma in una trama elettrica di viola, luce e materia. Opera fotografica selezionata da Beyond The Next.'),
    'dsc_07155': ('Icona napoletana', 'Un volto diventato simbolo collettivo emerge come un’icona contemporanea. Opera fotografica selezionata da Beyond The Next.'),
    'dsc_10511': ('Ramo di luce', 'Un frammento vegetale affiora dal buio e diventa segno, ritmo e superficie. Opera fotografica selezionata da Beyond The Next.'),
    'dsc_1088': ('Natura inversa', 'Foglie, ombre e colore alterato costruiscono una natura sospesa tra realtà e visione. Opera fotografica selezionata da Beyond The Next.'),
    'dsc_11822': ('Due presenze', 'Due fiori si fronteggiano nel verde come presenze silenziose. Opera fotografica selezionata da Beyond The Next.'),
    'dsc_1388': ('Nel campo', 'Una presenza minima interrompe la distesa naturale e ne rivela la scala. Opera fotografica selezionata da Beyond The Next.'),
    'dsc_1395': ('Distesa', 'Il paesaggio si apre in una superficie continua di luce, verde e giallo. Opera fotografica selezionata da Beyond The Next.'),
    'dsc_1471': ('Attraversamento', 'Il movimento dissolve il bosco e trasforma il passaggio in memoria visiva. Opera fotografica selezionata da Beyond The Next.'),
    'dsc_2784': ('Fioritura bianca', 'Il colore floreale emerge da un fondo luminoso in una composizione netta e vibrante. Opera fotografica selezionata da Beyond The Next.'),
    'edith blue': ('Edith Blue', 'Una superficie blu profonda trattiene grana, luce e silenzio. Opera fotografica selezionata da Beyond The Next.'),
    'me and sea': ('Me and Sea', 'Figure lontane abitano un paesaggio marino trasformato da una luce rosa irreale. Opera fotografica selezionata da Beyond The Next.'),
    'rosa shocking': ('Rosa Shocking', 'Una vibrazione cromatica occupa l’immagine e trasforma il colore in materia. Opera fotografica selezionata da Beyond The Next.'),
    'shara': ('Shara', 'L’orizzonte marino incontra una luce magenta intensa, tra paesaggio e astrazione. Opera fotografica selezionata da Beyond The Next.'),
    'pesc acquario maria giulia': ('Vita nell’acquario', 'Un organismo luminoso galleggia nel blu come una presenza fragile e misteriosa. Opera fotografica selezionata da Beyond The Next.'),
}

def _metadata(filename):
    base=filename.replace('\\','/').rsplit('/',1)[-1]
    stem=Path(base).stem.strip().lower()
    return PROFESSIONAL.get(stem,(f'{BRAND} — Opera fotografica','Una visione fotografica selezionata da Beyond The Next.'))

def _choose_size(template,image_width,image_height):
    choices=[]
    for color in template.get('colorVariants',[]):
        for variant in color.get('sizeVariants',[]):
            label=str(variant.get('size',''))
            if not variant.get('available',True) or not label: continue
            nums=[float(x.replace(',','.')) for x in re.findall(r'\d+(?:[.,]\d+)?',label)]
            if len(nums)>=2: choices.append((label,nums[0],nums[1]))
    unique={row[0]:row for row in choices}; choices=list(unique.values())
    if not choices: raise RuntimeError('Fourthwall non ha restituito formati utilizzabili.')
    ratio=max(image_width,image_height)/min(image_width,image_height)
    landscape=image_width>image_height
    if landscape:
        candidates=[row for row in choices if row[1]>row[2]]
        if not candidates: candidates=[row for row in choices if abs(row[1]-row[2])<0.01]
    else:
        candidates=[row for row in choices if row[2]>row[1]]
        if not candidates: candidates=[row for row in choices if abs(row[1]-row[2])<0.01]
    if not candidates: candidates=choices
    return min(candidates,key=lambda row:(abs(max(row[1],row[2])/min(row[1],row[2])-ratio),abs(max(row[1],row[2])-14)))[0]

BASE_TASKS = (
    (1, 'Identità', 'Usare Beyond The Next come nome pubblico del negozio'),
    (2, 'Catalogo', 'Controllare titoli, descrizioni e ritaglio delle bozze'),
    (3, 'Linea', 'Scegliere 5 opere principali per il lancio'),
    (4, 'Linea', 'Creare le collezioni Stampe, Edizioni limitate e Nuove opere'),
    (5, 'Negozio', 'Preparare pagina Chi siamo senza nome e cognome'),
    (6, 'Negozio', 'Inserire email pubblica di assistenza'),
    (7, 'Vendite', 'Controllare prezzi finali, spedizione e margine'),
    (8, 'Lancio', 'Pubblicare solo dopo il controllo finale'),
    (9, 'Pubblicità', 'Definire canali e budget prima di attivare campagne'),
)

def _connect(db_path):
    db=sqlite3.connect(db_path,timeout=15)
    cols={row[1] for row in db.execute('PRAGMA table_info(photos)')}
    for name,definition in [('metadata_version','INTEGER DEFAULT 0'),('legacy_product_id','TEXT'),('replacement_product_id','TEXT'),('replacement_title','TEXT'),('formatted_product_id','TEXT'),('formatted_size','TEXT')]:
        if name not in cols: db.execute(f'ALTER TABLE photos ADD COLUMN {name} {definition}')
    db.execute('''CREATE TABLE IF NOT EXISTS shop_tasks(
      id INTEGER PRIMARY KEY, priority INTEGER NOT NULL, area TEXT NOT NULL,
      task TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'Da fare',
      updated TEXT DEFAULT CURRENT_TIMESTAMP)''')
    for priority,area,task in BASE_TASKS:
        db.execute('INSERT OR IGNORE INTO shop_tasks(priority,area,task) VALUES (?,?,?)',(priority,area,task))
    count=db.execute("SELECT COUNT(*) FROM photos WHERE COALESCE(product_id,'')<>'' AND COALESCE(metadata_version,0)=0").fetchone()[0]
    if count:
        task=f'Aggiornare la descrizione delle {count} bozze già create con il testo Beyond The Next'
        db.execute('INSERT OR IGNORE INTO shop_tasks(priority,area,task) VALUES (?,?,?)',(1,'Catalogo',task))
    db.commit()
    return db

def open_manager(parent,db_path,photos_root):
    import tkinter as tk
    from tkinter import ttk,messagebox
    window=tk.Toplevel(parent)
    window.title(f'{BRAND} | Lista del negozio')
    window.geometry('940x620')
    frame=ttk.Frame(window,padding=18); frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='Lista del negozio',font=('Segoe UI',20,'bold')).pack(anchor='w')
    ttk.Label(frame,text='Il bot aggiorna questa lista in base al catalogo. Nessuna voce pubblica o spende denaro da sola.').pack(anchor='w',pady=(2,12))
    table=ttk.Treeview(frame,columns=('priority','area','task','status'),show='headings')
    for key,label,width in [('priority','Priorità',65),('area','Area',100),('task','Cosa serve',545),('status','Stato',110)]:
        table.heading(key,text=label); table.column(key,width=width,anchor='w')
    table.pack(fill='both',expand=True)
    progress=tk.StringVar(value='Le vecchie bozze restano intatte finché non confermi l’archiviazione.')
    ttk.Label(frame,textvariable=progress,wraplength=880).pack(anchor='w',pady=(10,0))
    events=queue.Queue(); busy=[False]

    def refresh():
        for item in table.get_children(): table.delete(item)
        db=_connect(db_path)
        try:
            rows=db.execute('SELECT id,priority,area,task,status FROM shop_tasks ORDER BY CASE status WHEN \'Da fare\' THEN 0 ELSE 1 END,priority,id').fetchall()
        finally: db.close()
        for row in rows: table.insert('', 'end', iid=str(row[0]), values=row[1:])

    def set_status(value):
        selected=table.selection()
        if not selected:
            messagebox.showinfo('Lista','Seleziona una voce.',parent=window); return
        db=_connect(db_path)
        try:
            db.execute("UPDATE shop_tasks SET status=?,updated=CURRENT_TIMESTAMP WHERE id=?",(value,int(selected[0]))); db.commit()
        finally: db.close()
        refresh()

    def legacy_rows():
        db=_connect(db_path)
        try:
            return db.execute("""SELECT sha,first_name,image_id,product_id,template_id,replacement_product_id
              FROM photos WHERE COALESCE(product_id,'')<>'' AND COALESCE(metadata_version,0)=0
              ORDER BY first_name""").fetchall()
        finally: db.close()

    def start_job(kind,worker):
        if busy[0]: return
        busy[0]=True
        prepare.configure(state='disabled'); format_button.configure(state='disabled'); archive.configure(state='disabled'); collection_button.configure(state='disabled')
        def run():
            try: events.put(('done',kind,worker()))
            except Exception as exc: events.put(('error',kind,str(exc)))
        threading.Thread(target=run,daemon=True).start()

    def prepare_replacements():
        rows=legacy_rows(); pending=[row for row in rows if not row[5]]
        if not rows:
            messagebox.showinfo('Bozze','Non ci sono vecchie bozze da sostituire.',parent=window); return
        if not pending:
            messagebox.showinfo('Bozze','Le nuove bozze professionali sono già pronte. Controllale su Fourthwall.',parent=window); return
        if not messagebox.askyesno('Prepara nuove bozze',f'Creare {len(pending)} nuove bozze NASCOSTE con titoli e descrizioni professionali?\n\nLe vecchie non saranno ancora archiviate.',parent=window): return
        def worker():
            from connessione import Vault
            from fourthwall_api import create_hidden_draft,template_details
            pair=Vault().load()
            if not pair: raise RuntimeError('Credenziali Fourthwall non trovate.')
            db=_connect(db_path)
            try:
                setting=db.execute("SELECT value FROM bot_settings WHERE key='auto_margin'").fetchone()
                margin=float(setting[0]) if setting else 10.0
            finally: db.close()
            regions={}; created=0
            for index,(sha,name,image_id,old_id,template_id,replacement_id) in enumerate(pending,1):
                if not image_id or not template_id: raise RuntimeError(f'Dati Fourthwall mancanti per {name}.')
                title,description=_metadata(name)
                events.put(('progress','prepare',f'Creazione {index}/{len(pending)}: {title}'))
                if template_id not in regions: regions[template_id]=template_details(template_id)[1]
                new_id=create_hidden_draft(*pair,template_id,regions[template_id],image_id,title,description,margin)
                db=_connect(db_path)
                try:
                    db.execute('UPDATE photos SET replacement_product_id=?,replacement_title=?,status=? WHERE sha=?',
                      (new_id,title,'Nuova bozza professionale pronta; vecchia ancora conservata',sha)); db.commit()
                finally: db.close()
                created+=1
                if index<len(pending): time.sleep(13)
            return f'{created} nuove bozze professionali create. Controllale su Fourthwall prima di archiviare le vecchie.'
        progress.set('Preparazione delle nuove bozze...'); start_job('prepare',worker)

    def format_rows():
        db=_connect(db_path)
        try:
            return db.execute("""SELECT sha,first_name,image_id,product_id,template_id,
              replacement_product_id,formatted_product_id,formatted_size
              FROM photos WHERE COALESCE(product_id,'')<>'' AND COALESCE(metadata_version,0)=0
              ORDER BY first_name""").fetchall()
        finally: db.close()

    def prepare_formats():
        rows=format_rows()
        if not rows or any(not row[5] for row in rows):
            messagebox.showerror('Bozze mancanti','Prima completa Prepara bozze professionali.',parent=window); return
        pending=[row for row in rows if not row[6]]
        if not pending:
            messagebox.showinfo('Formati','Le bozze con formato corretto sono già pronte.',parent=window); return
        if not messagebox.askyesno('Correggi formati',f'Creare {len(pending)} bozze NASCOSTE scegliendo automaticamente formato verticale, orizzontale o quadrato?\n\nLe versioni precedenti resteranno conservate.',parent=window): return
        def worker():
            from connessione import Vault
            from fourthwall_api import create_hidden_draft,image_dimensions,template_details
            pair=Vault().load()
            if not pair: raise RuntimeError('Credenziali Fourthwall non trovate.')
            db=_connect(db_path)
            try:
                setting=db.execute("SELECT value FROM bot_settings WHERE key='auto_margin'").fetchone()
                margin=float(setting[0]) if setting else 10.0
            finally: db.close()
            templates={}; created=0
            for index,(sha,name,image_id,old_id,template_id,replacement_id,formatted_id,formatted_size) in enumerate(pending,1):
                clean_name=name.replace('\\','/')
                path=Path(photos_root)/clean_name
                width,height=image_dimensions(path)
                if template_id not in templates: templates[template_id]=template_details(template_id)
                details,region=templates[template_id]
                size=_choose_size(details,width,height)
                title,description=_metadata(name)
                events.put(('progress','format',f'Formato {index}/{len(pending)}: {title} — {size}'))
                new_id=create_hidden_draft(*pair,template_id,region,image_id,title,description,margin,[size])
                db=_connect(db_path)
                try:
                    db.execute('UPDATE photos SET formatted_product_id=?,formatted_size=?,status=? WHERE sha=?',
                      (new_id,size,f'Bozza finale pronta nel formato {size}; versioni precedenti conservate',sha)); db.commit()
                finally: db.close()
                created+=1
                if index<len(pending): time.sleep(13)
            return f'{created} bozze con formato corretto create. Controllale su Fourthwall prima dell’archiviazione.'
        progress.set('Scelta automatica dei formati...'); start_job('format',worker)

    def archive_legacy():
        rows=format_rows()
        if not rows:
            messagebox.showinfo('Archivio','Le vecchie bozze risultano già archiviate.',parent=window); return
        missing=[row for row in rows if not row[6]]
        if missing:
            messagebox.showerror('Prima correggi i formati',f'Mancano ancora {len(missing)} bozze con formato corretto.',parent=window); return
        warning=(f'Archiviare le {len(rows)} vecchie bozze?\n\n'
                 'Le nuove bozze resteranno nascoste. L’archiviazione non è annullabile dal bot. '
                 'Fallo soltanto dopo aver controllato le nuove su Fourthwall.')
        if not messagebox.askyesno('Conferma archiviazione',warning,parent=window): return
        if not messagebox.askyesno('Ultima conferma','Hai controllato titoli, immagini e descrizioni delle nuove bozze?',parent=window): return
        def worker():
            from connessione import Vault
            from fourthwall_api import archive_product
            pair=Vault().load()
            if not pair: raise RuntimeError('Credenziali Fourthwall non trovate.')
            archived=0
            for index,(sha,name,image_id,old_id,template_id,replacement_id,formatted_id,formatted_size) in enumerate(rows,1):
                events.put(('progress','archive',f'Archiviazione {index}/{len(rows)}: {_metadata(name)[0]}'))
                archive_product(*pair,old_id)
                archive_product(*pair,replacement_id)
                db=_connect(db_path)
                try:
                    db.execute('''UPDATE photos SET legacy_product_id=product_id,product_id=formatted_product_id,
                      replacement_product_id=NULL,formatted_product_id=NULL,metadata_version=1,status=? WHERE sha=?''',
                      (f'Bozza professionale nascosta attiva — formato {formatted_size}',sha)); db.commit()
                finally: db.close()
                archived+=1
            db=_connect(db_path)
            try:
                db.execute("UPDATE shop_tasks SET status='Completato',updated=CURRENT_TIMESTAMP WHERE task LIKE 'Aggiornare la descrizione delle %'"); db.commit()
            finally: db.close()
            return f'{archived} vecchie bozze archiviate. Le nuove bozze professionali sono nascoste e pronte per il controllo finale.'
        progress.set('Archiviazione delle vecchie bozze...'); start_job('archive',worker)

    def create_launch_collection():
        db=_connect(db_path)
        try:
            rows=db.execute("SELECT first_name,product_id,COALESCE(metadata_version,0) FROM photos WHERE COALESCE(product_id,'')<>''").fetchall()
            found={_metadata(name)[0]:product_id for name,product_id,version in rows if version>=1}
            product_ids=[found.get(title) for title in LAUNCH_TITLES]
            saved=db.execute("SELECT value FROM bot_settings WHERE key='launch_collection_id'").fetchone()
            collection_id=saved[0] if saved else None
        finally: db.close()
        missing=[title for title,product_id in zip(LAUNCH_TITLES,product_ids) if not product_id]
        if missing:
            messagebox.showerror('Opere mancanti','Non trovo: '+', '.join(missing),parent=window); return
        if not messagebox.askyesno('Collezione di lancio','Creare una collezione NASCOSTA con queste cinque opere?\n\n• '+'\n• '.join(LAUNCH_TITLES)+'\n\nNessun prodotto sarà pubblicato.',parent=window): return
        def worker():
            from connessione import Vault
            from fourthwall_api import create_collection,set_collection_available,set_collection_products
            pair=Vault().load()
            if not pair: raise RuntimeError('Credenziali Fourthwall non trovate.')
            current_id=collection_id
            if not current_id:
                current_id,slug=create_collection(*pair,'Beyond The Next — Selezione di lancio',
                  'Cinque visioni tra paesaggio, materia e trasformazione. La selezione inaugurale di Beyond The Next.')
                db=_connect(db_path)
                try:
                    db.execute("INSERT OR REPLACE INTO bot_settings(key,value) VALUES ('launch_collection_id',?)",(current_id,))
                    db.execute("INSERT OR REPLACE INTO bot_settings(key,value) VALUES ('launch_collection_slug',?)",(slug,)); db.commit()
                finally: db.close()
            set_collection_available(*pair,current_id,False)
            set_collection_products(*pair,current_id,product_ids)
            db=_connect(db_path)
            try:
                db.execute("UPDATE shop_tasks SET status='Completato',updated=CURRENT_TIMESTAMP WHERE task='Scegliere 5 opere principali per il lancio'")
                db.commit()
            finally: db.close()
            return 'Collezione di lancio creata con 5 opere e mantenuta nascosta.'
        progress.set('Creazione della collezione di lancio nascosta...'); start_job('collection',worker)

    buttons=ttk.Frame(frame); buttons.pack(fill='x',pady=(10,0))
    ttk.Button(buttons,text='Segna completato',command=lambda:set_status('Completato')).pack(side='left')
    ttk.Button(buttons,text='Rimetti da fare',command=lambda:set_status('Da fare')).pack(side='left',padx=8)
    ttk.Button(buttons,text='Aggiorna lista',command=refresh).pack(side='left')
    prepare=ttk.Button(buttons,text='Prepara bozze professionali',command=prepare_replacements); prepare.pack(side='left',padx=(16,6))
    format_button=ttk.Button(buttons,text='Correggi formati',command=prepare_formats); format_button.pack(side='left',padx=(0,6))
    archive=ttk.Button(buttons,text='Archivia versioni precedenti',command=archive_legacy); archive.pack(side='left')
    ttk.Button(buttons,text='Chiudi',command=window.destroy).pack(side='right')
    collection_actions=ttk.Frame(frame); collection_actions.pack(fill='x',pady=(8,0))
    collection_button=ttk.Button(collection_actions,text='Crea collezione di lancio (nascosta)',command=create_launch_collection)
    collection_button.pack(side='left')
    def poll():
        try:
            while True:
                event=events.get_nowait()
                if event[0]=='progress': progress.set(event[2])
                else:
                    busy[0]=False; prepare.configure(state='normal'); format_button.configure(state='normal'); archive.configure(state='normal'); collection_button.configure(state='normal')
                    progress.set(event[2])
                    if event[0]=='error': messagebox.showerror('Operazione non completata',event[2],parent=window)
                    else: messagebox.showinfo('Beyond The Next',event[2],parent=window)
                    refresh()
        except queue.Empty: pass
        if window.winfo_exists(): window.after(300,poll)
    refresh()
    window.after(300,poll)
