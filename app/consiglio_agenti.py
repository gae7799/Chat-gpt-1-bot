"""Four specialized advisors feeding the local shop director."""
import sqlite3

ROLES = (
    ('fotografia', 'Esperto di fotografia'),
    ('marketing', 'Responsabile marketing'),
    ('progetto', 'Analista del progetto'),
    ('critica', 'Critico indipendente'),
)

REVIEW_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {
        'assessment': {'type': 'string'},
        'action': {'type': 'string'},
    },
    'required': ['assessment', 'action'],
}


def schema():
    return {
        'type': 'object', 'additionalProperties': False,
        'properties': {
            **{role: REVIEW_SCHEMA for role, _ in ROLES},
            'critica_bloccante': {'type': 'boolean'},
        },
        'required': [role for role, _ in ROLES] + ['critica_bloccante'],
    }


def instructions():
    return (
        'Il Direttore di Beyond The Next consulta quattro specialisti sulla fotografia. '
        'Fotografia: giudica composizione, risoluzione apparente, taglio e leggibilità come stampa; '
        'non dichiarare idonea la risoluzione di stampa senza misure reali. '
        'Marketing: individua un pubblico e una proposta organica concreta; non proporre campagne '
        'a pagamento, il budget pubblicitario è 0 euro. '
        'Progetto: valuta la coerenza con una bottega di fotografia manipolata, colore intenso, '
        'ombre, identità e principio less is more; suggerisci il ruolo dell’opera nella collezione. '
        'Critica: cerca difetti visivi, promessa commerciale eccessiva, diritti o qualità dubbi; '
        'se una criticità seria impedisce di proporre la stampa, imposta critica_bloccante=true. '
        'Per ogni ruolo scrivi assessment e action specifici e verificabili, brevi e in italiano; '
        'non inventare vendite, dati di pubblico, autorizzazioni, qualità del file o fatti non visibili. '
        'Il Direttore deve tenere conto del dissenso del critico nella decisione finale.'
    )


def validate(result):
    if not isinstance(result, dict):
        raise RuntimeError('Analisi AI non valida.')
    for field in ('title', 'description', 'theme', 'reason'):
        if not isinstance(result.get(field), str) or not result[field].strip():
            raise RuntimeError('Analisi AI incompleta: ' + field)
    if type(result.get('recommended')) is not bool or type(result.get('score')) is not int or not 0 <= result['score'] <= 100:
        raise RuntimeError('Punteggio o selezione AI non validi.')
    reviews = result.get('consiglio')
    if not isinstance(reviews, dict) or type(reviews.get('critica_bloccante')) is not bool:
        raise RuntimeError('Il consiglio degli specialisti non è completo.')
    cleaned = {'critica_bloccante': reviews['critica_bloccante']}
    for role, _ in ROLES:
        review = reviews.get(role)
        if not isinstance(review, dict):
            raise RuntimeError('Manca il parere dello specialista: ' + role)
        assessment, action = review.get('assessment'), review.get('action')
        if not isinstance(assessment, str) or not assessment.strip() or not isinstance(action, str) or not action.strip():
            raise RuntimeError('Parere incompleto dello specialista: ' + role)
        cleaned[role] = {'assessment': assessment.strip()[:800], 'action': action.strip()[:800]}
    result['consiglio'] = cleaned
    if cleaned['critica_bloccante']:
        result['recommended'] = False
        result['reason'] = ('Bloccata dal critico: ' + cleaned['critica']['assessment'])[:300]
    return result


def init(db):
    db.execute('''CREATE TABLE IF NOT EXISTS advisor_reviews(
        sha TEXT NOT NULL, role TEXT NOT NULL, assessment TEXT NOT NULL,
        action TEXT NOT NULL, blocks INTEGER NOT NULL DEFAULT 0,
        created TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(sha,role))''')


def save(db, sha, result):
    reviews = result.get('consiglio')
    validate(result)
    for role, _ in ROLES:
        review = reviews[role]
        db.execute('''INSERT OR REPLACE INTO advisor_reviews(sha,role,assessment,action,blocks)
                      VALUES (?,?,?,?,?)''',
                   (sha, role, review['assessment'], review['action'],
                    int(role == 'critica' and reviews['critica_bloccante'])))
    return len(ROLES)


def open_council(parent, db_path):
    import tkinter as tk
    from tkinter import ttk, messagebox
    window = tk.Toplevel(parent)
    window.title('Beyond The Next | Consiglio degli specialisti')
    window.geometry('1000x680')
    body = ttk.Frame(window, padding=16)
    body.pack(fill='both', expand=True)
    ttk.Label(body, text='Consiglio degli specialisti', font=('Segoe UI', 18, 'bold')).pack(anchor='w')
    ttk.Label(body, text='Quattro pareri per ogni nuova foto analizzata; il critico può bloccare la proposta.').pack(anchor='w', pady=(2, 10))
    project_state = tk.StringVar(value='Lettura dello stato del progetto...')
    ttk.Label(body, textvariable=project_state, wraplength=940).pack(anchor='w', pady=(0, 8))
    list_frame = ttk.Frame(body)
    list_frame.pack(fill='both', expand=True)
    table = ttk.Treeview(list_frame, columns=('foto', 'ruolo', 'stato'), show='headings')
    for col, width in [('foto', 390), ('ruolo', 250), ('stato', 170)]:
        table.heading(col, text=col.title()); table.column(col, width=width)
    scroll = ttk.Scrollbar(list_frame, orient='vertical', command=table.yview)
    table.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right', fill='y')
    table.pack(side='left', fill='both', expand=True)
    details = tk.Text(body, wrap='word', height=10, state='disabled')
    details.pack(fill='x', pady=10)
    cache = {}
    retry_ids = {}
    timer = None

    def selected(event=None):
        ids = table.selection()
        if ids:
            details.configure(state='normal'); details.delete('1.0', 'end')
            details.insert('end', cache.get(ids[0], '')); details.configure(state='disabled')

    def refresh():
        nonlocal timer
        if timer:
            window.after_cancel(timer)
            timer = None
        selection = table.selection()
        scroll_position = table.yview()[0]
        with sqlite3.connect(db_path, timeout=15) as db:
            init(db)
            rows = db.execute('''SELECT a.sha,p.first_name,a.role,a.assessment,a.action,a.blocks
                                 FROM advisor_reviews a JOIN photos p ON p.sha=a.sha
                                 ORDER BY a.created DESC,p.first_name,a.role''').fetchall()
            columns = {row[1] for row in db.execute('PRAGMA table_info(photos)')}
            total = db.execute('SELECT COUNT(*) FROM photos').fetchone()[0]
            analyzed = db.execute("SELECT COUNT(*) FROM photos WHERE ai_status='Analizzata'").fetchone()[0] if 'ai_status' in columns else 0
            products = db.execute("SELECT COUNT(*) FROM photos WHERE COALESCE(product_id,'')<>''").fetchone()[0] if 'product_id' in columns else 0
            blocked = db.execute('SELECT COUNT(*) FROM advisor_reviews WHERE blocks=1').fetchone()[0]
            failed = db.execute("SELECT sha,first_name,status FROM photos WHERE ai_status='Errore analisi'").fetchall() if 'ai_status' in columns else []
        project_state.set(f'Progetto: {total} foto, {analyzed or 0} analizzate, '
                          f'{products or 0} prodotti registrati, {blocked} pareri critici bloccanti. '
                          'Le opere già nel catalogo restano invariate; i quattro ruoli valutano le nuove foto.')
        if table.get_children():
            table.delete(*table.get_children())
        cache.clear()
        retry_ids.clear()
        labels = dict(ROLES)
        for i, (sha, filename, role, assessment, action, blocks) in enumerate(rows):
            iid = sha + ':' + role
            table.insert('', 'end', iid=iid, values=(filename, labels.get(role, role), 'Criticità bloccante' if blocks else 'Parere registrato'))
            cache[iid] = f'Foto: {filename}\nRuolo: {labels.get(role, role)}\n\nValutazione: {assessment}\n\nAzione proposta: {action}'
        for sha, filename, state in failed:
            iid = sha + ':retry'
            table.insert('', 'end', iid=iid, values=(filename, 'Analisi da riprovare', 'Errore'))
            cache[iid] = state + '\nPuoi rimettere la foto in coda con Riprova analisi. La richiesta OpenAI può avere un costo.'
            retry_ids[iid] = sha
        if selection and table.exists(selection[0]):
            table.selection_set(selection[0])
            selected()
        table.yview_moveto(scroll_position)
        timer = window.after(3000, refresh)

    def retry():
        ids = table.selection()
        sha = retry_ids.get(ids[0]) if ids else None
        if not sha:
            messagebox.showinfo('Riprova', 'Seleziona una riga con stato Errore.', parent=window)
            return
        if not messagebox.askyesno('Riprova analisi', 'Rimettere questa foto in coda? La nuova richiesta OpenAI può avere un costo e rientra nel limite giornaliero.', parent=window):
            return
        with sqlite3.connect(db_path, timeout=15) as db:
            db.execute("UPDATE photos SET ai_status='',status='In coda per una nuova analisi' WHERE sha=? AND ai_status='Errore analisi' AND COALESCE(product_id,'')=''", (sha,))
        from registro import observe
        observe(db_path)
        refresh()

    def close():
        if timer:
            window.after_cancel(timer)
        window.destroy()

    table.bind('<<TreeviewSelect>>', selected)
    controls = ttk.Frame(body); controls.pack(fill='x')
    ttk.Button(controls, text='Aggiorna', command=refresh).pack(side='left')
    from analisi_giornaliera import open_marketing_report
    ttk.Button(controls, text='Studio marketing e documenti',
               command=lambda:open_marketing_report(window, db_path)).pack(side='left', padx=8)
    ttk.Button(controls, text='Riprova analisi', command=retry).pack(side='left', padx=8)
    window.protocol('WM_DELETE_WINDOW', close)
    refresh()
