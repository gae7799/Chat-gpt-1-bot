from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from consiglio_agenti import ROLES
from gestione_ai import process_next
from openai_vision import analyze_photo


def sample(block):
    return {
        'title': 'Luce in movimento',
        'description': 'Paesaggio manipolato con una luce intensa e un taglio netto.',
        'theme': 'paesaggio', 'score': 83, 'recommended': True,
        'reason': 'Opera visivamente coerente e interessante.',
        'consiglio': {
            **{role: {'assessment': 'Osservazione ' + role, 'action': 'Verificare ' + role}
               for role, _ in ROLES},
            'critica_bloccante': block,
        },
    }


class CouncilTests(unittest.TestCase):
    def test_four_roles_share_one_request_and_critic_can_veto(self):
        with tempfile.TemporaryDirectory() as directory:
            photo = Path(directory) / 'picture.jpg'
            photo.write_bytes(b'local test image')
            calls = []
            def fake_api(path, key, payload, method, timeout):
                calls.append(payload)
                return {'output': [{'type': 'message', 'content': [
                    {'type': 'output_text', 'text': json.dumps(sample(True))}]}]}
            answer = analyze_photo(photo, 'sk-fake', caller=fake_api)
            self.assertEqual(len(calls), 1)
            for role, _ in ROLES:
                self.assertIn(role, calls[0]['text']['format']['schema']['properties']['consiglio']['properties'])
            self.assertFalse(answer['recommended'])
            self.assertIn('Bloccata dal critico', answer['reason'])

    def test_reviews_persist_and_are_recorded_before_director_schedules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photos = root / 'FOTO'; photos.mkdir()
            (photos / 'new.jpg').write_bytes(b'test')
            catalog = root / 'catalogo.sqlite'
            with closing(sqlite3.connect(catalog)) as db, db:
                db.execute('CREATE TABLE photos(sha TEXT PRIMARY KEY,first_name TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP,status TEXT,product_id TEXT)')
                db.execute('CREATE TABLE files(path TEXT PRIMARY KEY,sha TEXT,present INTEGER)')
                db.execute('CREATE TABLE bot_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
                db.execute("INSERT INTO photos VALUES ('hash','new.jpg',CURRENT_TIMESTAMP,'In attesa','')")
                db.execute("INSERT INTO files VALUES ('new.jpg','hash',1)")
                db.execute("INSERT INTO bot_settings VALUES ('director_auto_enabled','1')")
            result = process_next(catalog, photos, analyzer=lambda *args: sample(True),
                                  key_loader=lambda: ('openai','sk-fake'))
            self.assertEqual(result[0], 'analyzed')
            with closing(sqlite3.connect(catalog)) as db, db:
                self.assertEqual(db.execute('SELECT ai_recommended FROM photos').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM advisor_reviews').fetchone()[0], 4)
                self.assertEqual(db.execute("SELECT blocks FROM advisor_reviews WHERE role='critica'").fetchone()[0], 1)
            from registro import save_texts
            self.assertGreaterEqual(save_texts(catalog), 4)
            entries = list((root / 'DIARIO_LOGICO').glob('evento-*.txt'))
            self.assertTrue(any('Specialisti' in entry.read_text(encoding='utf-8') for entry in entries))


if __name__ == '__main__':
    unittest.main()
