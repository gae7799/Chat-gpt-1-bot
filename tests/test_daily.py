from datetime import datetime, timedelta
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from analisi_giornaliera import run_daily, connect, market_report, editorial_report, market_html


class DailyTests(unittest.TestCase):
    def setup_db(self, path):
        with sqlite3.connect(path) as db:
            db.executescript('''CREATE TABLE bot_settings(key TEXT PRIMARY KEY,value TEXT);
                INSERT INTO bot_settings VALUES ('director_auto_enabled','1');
                CREATE TABLE photos(sha TEXT,product_id TEXT,ai_recommended INTEGER,ai_title TEXT,ai_score INTEGER);
                INSERT INTO photos VALUES ('one','p1',1,'Opera',88);''')

    def fixtures(self):
        calls=[]
        def shop(local):
            calls.append('shop')
            return {'products':[{'product_id':'p1','access':'HIDDEN','title':'Opera'}], 'checked':1,'catalog_ids':1}
        def market():
            calls.append('market')
            return {'text':'Prezzi richiesti; nessuna misura della domanda.', 'sources':{'https://example.org':'Offerta'},'annotations':[]}
        def editorial(*args):
            calls.append('editorial'); return {'action':'proposta','sha':'one','title':'Opera','reason':'Test'}
        return calls,dict(shop_fn=shop,market_fn=market,editorial_fn=editorial)

    def test_one_report_per_local_day_and_restart_reuse(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'catalogo.sqlite'; self.setup_db(path)
            calls, fns=self.fixtures(); now=datetime(2026,9,24,9)
            for expected in ('negozio','mercato','editoriale','completato','completato'):
                self.assertEqual(run_daily(path,now,**fns),expected)
            self.assertEqual(calls,['shop','market','editorial'])
            self.assertTrue((Path(folder)/'RAPPORTI_GIORNALIERI/2026-09-24.html').exists())
            self.assertEqual(run_daily(path,now+timedelta(days=1),**fns),'negozio')
            with connect(path) as db:
                report=json.loads(db.execute("SELECT payload FROM daily_agents WHERE day='2026-09-25' AND stage='negozio'").fetchone()[0])
            self.assertEqual(report['visibility_changes'],[])

    def test_error_backoff_retains_completed_phase_and_caps_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'catalogo.sqlite';self.setup_db(path)
            calls,fns=self.fixtures();now=datetime(2026,9,24,9)
            run_daily(path,now,**fns)
            def fail(): calls.append('failure');raise RuntimeError('secret-key-not-to-log')
            fns['market_fn']=fail
            self.assertEqual(run_daily(path,now,**fns),'errore')
            self.assertEqual(run_daily(path,now+timedelta(minutes=1),**fns),'attesa')
            self.assertEqual(run_daily(path,now+timedelta(minutes=16),**fns),'errore')
            self.assertEqual(run_daily(path,now+timedelta(hours=2),**fns),'limite')
            self.assertEqual(calls,['shop','failure','failure'])
            self.assertNotIn('secret-key', (Path(folder)/'RAPPORTI_GIORNALIERI/2026-09-24.json').read_text())

    def test_paused_never_calls_providers(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'catalogo.sqlite';self.setup_db(path)
            with sqlite3.connect(path) as db: db.execute("UPDATE bot_settings SET value='0'")
            calls,fns=self.fixtures()
            self.assertEqual(run_daily(path,datetime(2026,9,24),**fns),'sospeso')
            self.assertFalse(calls)

    def test_active_lease_blocks_second_process(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'catalogo.sqlite';self.setup_db(path)
            calls,fns=self.fixtures();now=datetime(2026,9,24,9)
            with connect(path) as db:
                db.execute("INSERT INTO daily_agents VALUES ('2026-09-24','negozio','in corso',1,?,NULL,NULL)",(now.timestamp()+3600,))
            self.assertEqual(run_daily(path,now,**fns),'attesa');self.assertFalse(calls)

    def test_market_needs_real_search_and_citations(self):
        response={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'Un prezzo inventato','annotations':[]}]}]}
        with self.assertRaises(RuntimeError):
            market_report(key_loader=lambda:('u','k'),caller=lambda *args:response)
        response['output'].insert(0,{'type':'web_search_call','status':'completed'})
        response['output'][1]['content'][0]['annotations']=[{'type':'url_citation','url':'https://example.org','title':'Fonte','start_index':0,'end_index':2}]
        report=market_report(key_loader=lambda:('u','k'),caller=lambda *args:response)
        self.assertIn('href="https://example.org"',market_html(report))

    def test_critic_and_public_products_excluded(self):
        local={'photos':[{'sha':'s','product_id':'p','ai_recommended':1}],'plans':[],
               'reviews':[{'sha':'s','blocks':1}]}
        result=editorial_report(local,{'products':[{'product_id':'p','access':'HIDDEN'}]}, {},
                                key_loader=lambda:self.fail('Should not call OpenAI'))
        self.assertEqual(result['action'],'attesa')
        local['reviews']=[]
        result=editorial_report(local,{'products':[{'product_id':'p','access':'PUBLIC'}]}, {},
                                key_loader=lambda:self.fail('Should not call OpenAI'))
        self.assertEqual(result['action'],'attesa')

    def test_editorial_cannot_invent_candidate(self):
        local={'photos':[{'sha':'s','product_id':'p','ai_recommended':1,'ai_score':80}],'plans':[],'reviews':[]}
        reply={k:'x' for k in ('sha','title','description','format_proposal','timing','reason','social_post','price_note')}
        response={'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(reply)}]}]}
        with self.assertRaises(RuntimeError):
            editorial_report(local,{'products':[{'product_id':'p','access':'HIDDEN'}]}, {'text':'test','sources':{}},
                             key_loader=lambda:('u','k'),caller=lambda *args:response)


if __name__=='__main__':unittest.main()
