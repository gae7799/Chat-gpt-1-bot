from datetime import datetime
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest

from analisi_giornaliera import marketing_continuo
from registro import connect as journal_connect


class MarketingTests(unittest.TestCase):
    def test_tracks_documents_sources_and_photo_relationships_without_repeating_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'DATI').mkdir()
            path = root / 'DATI/catalogo.sqlite'
            with sqlite3.connect(path) as db:
                db.executescript('''CREATE TABLE photos(sha TEXT, first_name TEXT, product_id TEXT,
                    ai_title TEXT, ai_theme TEXT, ai_description TEXT);
                    INSERT INTO photos VALUES ('s1','radici.jpg','p1','Radici elettriche','viola','Trama di luce');
                    CREATE TABLE advisor_reviews(sha TEXT,role TEXT,assessment TEXT,action TEXT);
                    INSERT INTO advisor_reviews VALUES ('s1','marketing','Pubblico interessato ai colori','Presentare organicamente');
                    CREATE TABLE daily_agents(day TEXT,stage TEXT,state TEXT,attempts INTEGER,next_at REAL,payload TEXT,error TEXT);
                ''')
                db.execute('INSERT INTO daily_agents VALUES (?,?,?,?,?,?,?)',('2026-09-25','mercato','completato',1,0,
                    json.dumps({'text':'Poster viola con prezzo esposto, vendite non note',
                                'sources':{'https://example.org':'Fonte prezzo'}}),None))
                db.execute('INSERT INTO daily_agents VALUES (?,?,?,?,?,?,?)',('2026-09-25','negozio','completato',1,0,
                    json.dumps({'products':[{'product_id':'p1','title':'Radici elettriche','access':'PUBLIC'}]}),None))
            docs = root / 'DOCUMENTI_MARKETING'
            docs.mkdir()
            (docs/'idee.md').write_text('Campagna organica sulla luce e sul viola.',encoding='utf-8')
            (docs/'ignora.pdf').write_bytes(b'%PDF-1.4')
            stamp = datetime(2026,9,25,12)
            self.assertTrue(marketing_continuo(path,stamp))
            self.assertFalse(marketing_continuo(path,stamp))
            report = json.loads((root/'DATI/RAPPORTI_MARKETING/rapporto-attuale.json').read_text(encoding='utf-8'))
            self.assertEqual(report['works'][0]['visibility'],'PUBLIC')
            self.assertEqual({m['source'] for m in report['works'][0]['matches']},{'idee.md','Ricerca del 2026-09-25'})
            self.assertIn('ignora.pdf',report['skipped'][0])
            self.assertIn('Fonte prezzo',(root/'DATI/RAPPORTI_MARKETING/rapporto-attuale.html').read_text(encoding='utf-8'))
            with journal_connect(path) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE actor='Specialista marketing'").fetchone()[0],1)
            (docs/'idee.md').write_text('Studio fotografico di radici: <script>alert(1)</script>',encoding='utf-8')
            self.assertTrue(marketing_continuo(path,stamp))
            markup = (root/'DATI/RAPPORTI_MARKETING/rapporto-attuale.html').read_text(encoding='utf-8')
            self.assertNotIn('<script>',markup)
            with journal_connect(path) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE actor='Specialista marketing'").fetchone()[0],2)


if __name__ == '__main__':
    unittest.main()
