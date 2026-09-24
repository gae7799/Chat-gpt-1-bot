from datetime import datetime
from pathlib import Path
import sqlite3
import tempfile
import unittest

from direttore_autonomo import compact_pending_plan, generate_plan, publish_due, reconcile_plan


class DirectorTests(unittest.TestCase):
    def _scheduled(self, path):
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE director_plan (id INTEGER PRIMARY KEY, product_id TEXT, title TEXT, position INTEGER, proposed_at TEXT, reason TEXT, status TEXT)")
        db.execute("INSERT INTO director_plan VALUES (1,'fw-radici','Radici elettriche',1,'2026-09-25T18:30','', 'Approvata')")
        db.execute("CREATE TABLE bot_settings (key TEXT PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO bot_settings VALUES ('director_auto_enabled','1')")
        db.commit(); db.close()

    def test_already_public_is_not_republished(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalogo.sqlite'
            self._scheduled(path)
            changes = []
            getter = lambda user, password, product_id: 'PUBLIC'
            self.assertEqual(reconcile_plan(path, getter, lambda: ('user','pass')), 1)
            self.assertEqual(publish_due(path, datetime(2026,9,25,19),
                             product_setter=lambda *args: changes.append(args),
                             product_getter=getter, credential_loader=lambda: ('user','pass')), 0)
            self.assertFalse(changes)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('SELECT status FROM director_plan').fetchone()[0], 'Già pubblica')

    def test_hidden_product_publishes_only_after_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalogo.sqlite'
            self._scheduled(path)
            access = {'value':'HIDDEN'}
            def publish(*args): access['value'] = 'PUBLIC'
            self.assertEqual(publish_due(path, datetime(2026,9,25,19),
                             product_setter=publish,
                             product_getter=lambda *args: access['value'],
                             credential_loader=lambda: ('user','pass')), 1)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('SELECT status FROM director_plan').fetchone()[0], 'Pubblicata')

    def test_unknown_access_blocks_publish(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalogo.sqlite'
            self._scheduled(path)
            with self.assertRaisesRegex(RuntimeError,'stato Fourthwall'):
                publish_due(path, datetime(2026,9,25,19),
                            product_setter=lambda *args: self.fail('unexpected publish'),
                            product_getter=lambda *args: 'PRIVATE',
                            credential_loader=lambda: ('user','pass'))
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('SELECT status FROM director_plan').fetchone()[0], 'Approvata')

    def test_builds_safe_five_item_plan(self):
        names = ['Caserta  1752.jpg','DSC_0216.jpg','Me and Sea.jpg','Shara.jpg','pesc acquario maria giulia.jpg']
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalogo.sqlite'
            db = sqlite3.connect(path)
            db.execute('CREATE TABLE photos(first_name TEXT,product_id TEXT,metadata_version INTEGER)')
            db.executemany('INSERT INTO photos VALUES (?,?,1)', [(name, f'id-{index}') for index, name in enumerate(names)])
            db.commit(); db.close()
            count, created = generate_plan(path, now=datetime(2026, 9, 18, 12, 0))
            self.assertTrue(created)
            self.assertEqual(count, 5)
            db = sqlite3.connect(path)
            rows = db.execute('SELECT title,proposed_at,status FROM director_plan ORDER BY position').fetchall()
            db.close()
            self.assertEqual(rows[0][0], 'Radici elettriche')
            self.assertTrue(all(row[2] == 'Proposta' for row in rows))
            self.assertEqual((datetime.fromisoformat(rows[1][1]) - datetime.fromisoformat(rows[0][1])).days, 7)

    def test_reuses_vacated_slots_without_touching_public_products(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalogo.sqlite'
            self._scheduled(path)
            with sqlite3.connect(path) as db:
                db.execute("UPDATE director_plan SET status='Già pubblica' WHERE id=1")
                db.executemany('INSERT INTO director_plan VALUES (?,?,?,?,?,?,?)', [
                    (2,'fw-shara','Shara',2,'2026-10-02T18:30','', 'Già pubblica'),
                    (3,'fw-sotto','Sotto la volta',3,'2026-10-09T18:30','', 'Approvata'),
                    (4,'fw-sea','Me and Sea',4,'2026-10-16T18:30','', 'Approvata'),
                    (5,'fw-vita','Vita nell’acquario',5,'2026-10-23T18:30','', 'Già pubblica'),
                ])
            now = datetime(2026,9,22,12)
            self.assertEqual(compact_pending_plan(path, now=now), 2)
            self.assertEqual(compact_pending_plan(path, now=now), 0)
            with sqlite3.connect(path) as db:
                rows = db.execute('SELECT proposed_at,status FROM director_plan ORDER BY id').fetchall()
                events = db.execute("SELECT COUNT(*) FROM director_runs WHERE outcome='rescheduled'").fetchone()[0]
            self.assertEqual([row[0] for row in rows], [
                '2026-09-25T18:30','2026-10-02T18:30',
                '2026-09-25T18:30','2026-10-02T18:30','2026-10-23T18:30'])
            self.assertEqual([row[1] for row in rows],
                             ['Già pubblica','Già pubblica','Approvata','Approvata','Già pubblica'])
            self.assertEqual(events, 2)

    def test_overdue_proposal_is_not_rescheduled(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalogo.sqlite'
            self._scheduled(path)
            self.assertEqual(compact_pending_plan(path, now=datetime(2026,9,26,12)), 0)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('SELECT proposed_at FROM director_plan').fetchone()[0],
                                 '2026-09-25T18:30')


if __name__ == '__main__':
    unittest.main()
