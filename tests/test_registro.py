import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from bot import Catalog
from registro import capture, connect, record, heartbeat, export_json


class JournalTests(unittest.TestCase):
    def test_persistence_dedup_changes_export_and_private_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = Catalog(folder)
            path = Path(folder) / 'DATI' / 'catalogo.sqlite'
            catalog.db.execute("INSERT INTO photos(sha,first_name,status) VALUES ('s','foto.jpg','Pronta')")
            catalog.db.execute('CREATE TABLE bot_settings(key TEXT PRIMARY KEY,value TEXT)')
            catalog.db.execute("INSERT INTO bot_settings VALUES ('api_key','SECRET-SHOULD-NOT-APPEAR')")
            catalog.db.commit()
            capture(path); capture(path)
            db = connect(path)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],1)
            self.assertIn('Prima rilevazione',db.execute('SELECT details FROM events').fetchone()[0])
            catalog.db.execute("UPDATE photos SET status='Bozza creata'")
            catalog.db.commit()
            capture(path)
            record(path,'Sessione','Bot','Avvio')
            heartbeat(path,'Attesa')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],3)
            self.assertEqual(db.execute('SELECT phase FROM live').fetchone()[0],'Attesa')
            db.close()
            out = Path(folder) / 'export.json'
            export_json(path,out)
            content = out.read_text(encoding='utf-8')
            self.assertNotIn('SECRET-SHOULD-NOT-APPEAR',content)
            rows = json.loads(content)
            self.assertEqual(len(rows),3)
            self.assertEqual(rows[1]['outcome'],'Bozza creata')
            self.assertTrue(rows[0]['at'].endswith('+00:00'))
            catalog.db.close()

    def test_ai_start_and_result_are_both_archived(self):
        from gestione_ai import process_next
        with tempfile.TemporaryDirectory() as folder:
            catalog = Catalog(folder)
            path = Path(folder) / 'DATI' / 'catalogo.sqlite'
            catalog.db.execute("INSERT INTO photos(sha,first_name,status) VALUES ('s','foto.jpg','Pronta')")
            catalog.db.execute("INSERT INTO files VALUES ('foto.jpg','s',1,1,1)")
            catalog.db.execute('CREATE TABLE bot_settings(key TEXT PRIMARY KEY,value TEXT)')
            catalog.db.execute("INSERT INTO bot_settings VALUES ('director_auto_enabled','1')")
            catalog.db.commit()
            result = dict(title='Luce',description='Una descrizione fotografica.',theme='Natura',
                          score=80,recommended=True,reason='Composizione equilibrata')
            from test_council import sample
            result['consiglio'] = sample(False)['consiglio']
            process_next(path,Path(folder)/'FOTO',analyzer=lambda *a:result,key_loader=lambda:('u','SECRET'))
            db = connect(path)
            rows = db.execute("SELECT details FROM events WHERE area='Fotografie' ORDER BY id").fetchall()
            self.assertEqual(len(rows),2)
            self.assertIn('Analisi in corso',rows[0][0])
            self.assertIn('Composizione equilibrata',rows[1][0])
            self.assertNotIn('SECRET',str(rows))
            db.close(); catalog.db.close()
