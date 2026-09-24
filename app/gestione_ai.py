"""Autonomous analysis queue for new local photographs."""
from datetime import date
from pathlib import Path
import sqlite3
from consiglio_agenti import init as init_council, save as save_council, validate

MAX_DAILY_ANALYSES = 5


def _connect(db_path):
    db = sqlite3.connect(db_path, timeout=15)
    cols = {row[1] for row in db.execute('PRAGMA table_info(photos)')}
    for name, definition in [
        ('ai_status', 'TEXT'), ('ai_title', 'TEXT'), ('ai_description', 'TEXT'),
        ('ai_theme', 'TEXT'), ('ai_score', 'INTEGER'), ('ai_recommended', 'INTEGER'),
        ('ai_reason', 'TEXT'), ('ai_analyzed_at', 'TEXT'), ('ai_started_at', 'TEXT')]:
        if name not in cols:
            db.execute(f'ALTER TABLE photos ADD COLUMN {name} {definition}')
    db.execute('''CREATE TABLE IF NOT EXISTS ai_usage(
      day TEXT PRIMARY KEY, analyses INTEGER NOT NULL DEFAULT 0)''')
    init_council(db)
    db.commit(); return db


def process_next(db_path, photos_root, analyzer=None, key_loader=None):
    from openai_vision import OpenAIVault, analyze_photo
    analyzer = analyzer or analyze_photo
    key_loader = key_loader or (lambda: OpenAIVault().load())
    db = _connect(db_path)
    try:
        db.execute('BEGIN IMMEDIATE')
        # Expired calls are exposed for manual retry, never recharged silently.
        db.execute("""UPDATE photos SET ai_status='Errore analisi',
            status='Analisi interrotta: usa Riprova analisi nella finestra specialisti'
            WHERE ai_status='Analisi in corso' AND
            (ai_started_at IS NULL OR ai_started_at < datetime('now','-10 minutes'))""")
        db.commit()
        db.execute('BEGIN IMMEDIATE')
        enabled = db.execute("SELECT value FROM bot_settings WHERE key='director_auto_enabled'").fetchone()
        if not enabled or enabled[0] != '1': return None
        today = date.today().isoformat()
        used = db.execute('SELECT analyses FROM ai_usage WHERE day=?', (today,)).fetchone()
        if used and used[0] >= MAX_DAILY_ANALYSES: return ('limit', MAX_DAILY_ANALYSES)
        row = db.execute('''SELECT p.sha,f.path FROM photos p JOIN files f ON p.sha=f.sha
          WHERE f.present=1 AND COALESCE(p.product_id,'')='' AND COALESCE(p.ai_status,'')=''
          AND (LOWER(f.path) LIKE '%.jpg' OR LOWER(f.path) LIKE '%.jpeg' OR LOWER(f.path) LIKE '%.png')
          ORDER BY p.created,f.path LIMIT 1''').fetchone()
        if not row: return None
        sha, rel = row
        pair = key_loader()
        if not pair:
            raise RuntimeError('Collega prima la chiave OpenAI.')
        # Reserve attempts before network I/O: failures also consume the quota.
        db.execute('''INSERT INTO ai_usage(day,analyses) VALUES (?,1)
          ON CONFLICT(day) DO UPDATE SET analyses=analyses+1''', (today,))
        db.execute("UPDATE photos SET ai_status='Analisi in corso',ai_started_at=CURRENT_TIMESTAMP,status='Valutazione artistica OpenAI...' WHERE sha=?", (sha,))
        db.commit()
    finally: db.close()
    from registro import observe
    observe(db_path)
    try:
        result = validate(analyzer(Path(photos_root) / rel, pair[1]))
    except Exception:
        db = _connect(db_path)
        try:
            db.execute("UPDATE photos SET ai_status='Errore analisi',status='Analisi OpenAI non riuscita; controlla la chiave' WHERE sha=?", (sha,))
            db.commit()
        finally: db.close()
        observe(db_path)
        raise
    db = _connect(db_path)
    try:
        save_council(db, sha, result)
        status = 'Selezionata dal direttore; pronta per la bozza' if result['recommended'] else 'Non selezionata dal direttore artistico'
        db.execute('''UPDATE photos SET ai_status='Analizzata',ai_title=?,ai_description=?,ai_theme=?,
          ai_score=?,ai_recommended=?,ai_reason=?,ai_analyzed_at=CURRENT_TIMESTAMP,status=? WHERE sha=?''',
          (result['title'], result['description'], result['theme'], result['score'],
           int(result['recommended']), result['reason'], status, sha))
        db.commit()
    finally: db.close()
    observe(db_path)
    return ('analyzed', rel, result)
