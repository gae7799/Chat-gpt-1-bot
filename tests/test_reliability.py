from datetime import date, datetime
from pathlib import Path
import sqlite3
import tempfile
import unittest

from gestione_ai import process_next, _connect
from openai_vision import _output_text
from test_council import sample
import test_director
from direttore_autonomo import publish_due


class ReliabilityTests(unittest.TestCase):
    def catalog(self, path):
        with sqlite3.connect(path) as db:
            db.executescript('''
                CREATE TABLE photos(sha TEXT PRIMARY KEY,first_name TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP,status TEXT,product_id TEXT);
                CREATE TABLE files(path TEXT PRIMARY KEY,sha TEXT,present INTEGER);
                CREATE TABLE bot_settings(key TEXT PRIMARY KEY,value TEXT);
                INSERT INTO photos VALUES ('sha','new.jpg',CURRENT_TIMESTAMP,'In attesa','');
                INSERT INTO files VALUES ('new.jpg','sha',1);
                INSERT INTO bot_settings VALUES ('director_auto_enabled','1');
            ''')
        _connect(path).close()

    def test_invalid_selection_is_not_saved_as_success(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalogo.sqlite'
            self.catalog(path)
            answer = sample(False); answer['recommended'] = 'true'
            with self.assertRaises(RuntimeError):
                process_next(path, folder, analyzer=lambda *args: answer, key_loader=lambda: ('u','k'))
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('SELECT ai_status FROM photos').fetchone()[0], 'Errore analisi')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM advisor_reviews').fetchone()[0], 0)

    def test_interrupted_call_is_recoverable_without_extra_charge(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalogo.sqlite'
            self.catalog(path)
            with sqlite3.connect(path) as db:
                db.execute("UPDATE photos SET ai_status='Analisi in corso',ai_started_at='2000-01-01 00:00:00'")
                db.execute('INSERT INTO ai_usage VALUES (?,5)', (date.today().isoformat(),))
            self.assertEqual(process_next(path, folder, analyzer=lambda *args: self.fail('Extra AI call')), ('limit', 5))
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('SELECT ai_status FROM photos').fetchone()[0], 'Errore analisi')
                self.assertEqual(db.execute('SELECT analyses FROM ai_usage').fetchone()[0], 5)

    def test_pause_during_visibility_check_blocks_publish(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalogo.sqlite'
            test_director.DirectorTests()._scheduled(path)
            def getter(*args):
                with sqlite3.connect(path) as db:
                    db.execute("UPDATE bot_settings SET value='0' WHERE key='director_auto_enabled'")
                return 'HIDDEN'
            result = publish_due(path, datetime(2026,9,26),
                product_getter=getter, product_setter=lambda *args: self.fail('Published after pause'),
                credential_loader=lambda: ('u','k'))
            self.assertEqual(result, 0)

    def test_truncated_response_rejected_even_if_text_exists(self):
        with self.assertRaisesRegex(RuntimeError, 'incompleta'):
            _output_text({'status':'incomplete','output':[{'type':'message','content':[{'type':'output_text','text':'{}'}]}]})


if __name__ == '__main__':
    unittest.main()
