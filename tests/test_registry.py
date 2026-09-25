from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import tempfile
import unittest

from registro import connect, logical_review


class RegistryCadenceTests(unittest.TestCase):
    def test_five_notes_per_five_minutes_and_rolling_ceiling(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = Path(folder) / 'catalogo.sqlite'
            start = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
            with closing(connect(catalog)) as db, db:
                db.execute("INSERT INTO snapshots VALUES (?,?)", ('advisor:photo:marketing', json.dumps({
                    'first_name':'foto.jpg', 'action':'Controllare la proposta organica', 'blocks':0})))
            for minute in range(5):
                moment = start + timedelta(minutes=minute)
                self.assertTrue(logical_review(catalog, moment))
                self.assertFalse(logical_review(catalog, moment + timedelta(seconds=15)))
            with closing(connect(catalog)) as db, db:
                notes = db.execute("SELECT details FROM events WHERE area='Diario logico' ORDER BY id").fetchall()
                self.assertEqual(len(notes), 5)
                self.assertIn('Controllare la proposta organica', notes[1][0])
                for _ in range(46):
                    db.execute("INSERT INTO events(at,area,subject,outcome,details) VALUES (?,?,?,?,?)",
                        ((start + timedelta(minutes=4,seconds=30)).isoformat(timespec='seconds'),
                         'Diario logico','test','Riepilogo periodico','verifica limite'))
            self.assertFalse(logical_review(catalog, start + timedelta(minutes=5)))
            self.assertTrue(logical_review(catalog, start + timedelta(minutes=10)))


if __name__ == '__main__':
    unittest.main()
