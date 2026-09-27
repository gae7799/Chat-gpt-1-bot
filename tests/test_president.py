from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest

from analisi_giornaliera import connect as daily_db
from consiglio_agenti import (president_db, run_president, president_brief,
                             president_consulted, validate_president, export_president)


class PresidentTests(unittest.TestCase):
    def fixture(self, directory, moment):
        path = Path(directory)/'catalogo.sqlite'
        with closing(president_db(path)) as db, db:
            db.execute("INSERT INTO bot_settings VALUES ('director_auto_enabled','1')")
            db.execute('CREATE TABLE photos(sha TEXT,product_id TEXT,ai_title TEXT,ai_description TEXT)')
            db.execute("INSERT INTO photos VALUES ('s','p','Radici elettriche','Colore viola')")
        self.daily(path,moment)
        return path

    def daily(self,path,moment):
        with closing(daily_db(path)) as db, db:
            db.execute('INSERT OR REPLACE INTO daily_agents VALUES (?,?,?,?,?,?,?)',
                       (moment.date().isoformat(),'editoriale','completato',1,0,json.dumps({'action':'attesa'}),None))

    def reply(self):
        return {'summary':'Priorità: descrivere il colore viola senza inventare domanda.',
                'missing_data':['Dati di vendita non disponibili'],
                'priorities':[{'owner':'marketing','photo_sha':'s','action':'Preparare un testo sul colore viola',
                               'reason':'Il tema è presente nella descrizione', 'evidence':['foto:s'],
                               'completion_check':'Testo salvato con riferimento alla foto'}]}

    def caller(self,calls):
        def call(path,key,payload,method,timeout):
            self.assertEqual(path,'/responses')
            self.assertFalse(payload['store'])
            calls.append(payload)
            return {'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(self.reply())}]}],
                    'usage':{'input_tokens':100,'output_tokens':100}}
        return call

    def test_daily_weekly_quotas_survive_restart_and_handoff_is_not_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            monday = datetime(2026,9,28,10)
            path = self.fixture(folder,monday)
            calls=[]
            args={'key_loader':lambda:('u','fake'),'caller':self.caller(calls)}
            self.assertEqual(run_president(path,monday,**args),'quotidiano')
            self.assertEqual(run_president(path,monday,**args),'strategico')
            self.assertEqual(run_president(path,monday,**args),'limite del periodo raggiunto')
            tuesday=monday+timedelta(days=1)
            self.daily(path,tuesday)
            self.assertEqual(run_president(path,tuesday,**args),'quotidiano')
            self.assertEqual(run_president(path,tuesday,**args),'limite del periodo raggiunto')
            self.assertEqual([c['model'] for c in calls],['gpt-6-sol','gpt-6-astra','gpt-6-sol'])
            brief=president_brief(path,'marketing','s')
            self.assertTrue(brief)
            president_consulted(path,brief)
            with closing(president_db(path)) as db:
                self.assertEqual(db.execute('SELECT DISTINCT state FROM president_tasks').fetchall(),[('Consultato',)])
            self.assertTrue(export_president(path).is_file())

    def test_paused_missing_key_and_pending_report_never_call_api(self):
        with tempfile.TemporaryDirectory() as folder:
            now=datetime(2026,9,28)
            path=self.fixture(folder,now)
            def fail(*args): self.fail('Unexpected paid API call')
            self.assertEqual(run_president(path,now,key_loader=lambda:None,caller=fail),'collega OpenAI')
            with closing(president_db(path)) as db, db:
                db.execute("INSERT INTO bot_settings VALUES ('president_enabled','0')")
            self.assertEqual(run_president(path,now,caller=fail),'sospeso')
            with closing(president_db(path)) as db, db:
                db.execute("UPDATE bot_settings SET value='1' WHERE key='president_enabled'")
            self.assertEqual(run_president(path,now+timedelta(days=1),caller=fail),'attesa del rapporto giornaliero')

    def test_invalid_evidence_does_not_create_tasks_or_repeat_request(self):
        with tempfile.TemporaryDirectory() as folder:
            now=datetime(2026,9,28)
            path=self.fixture(folder,now)
            calls=[]
            def bad(*args):
                calls.append(1)
                result=self.reply(); result['priorities'][0]['evidence']=['invented-source']
                return {'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(result)}]}]}
            args={'key_loader':lambda:('u','fake'),'caller':bad}
            self.assertEqual(run_president(path,now,**args),'errore')
            self.assertEqual(run_president(path,now,**args),'attesa della decisione quotidiana')
            self.assertEqual(len(calls),1)
            with closing(president_db(path)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM president_tasks').fetchone()[0],0)

    def test_reserved_call_blocks_concurrent_request(self):
        with tempfile.TemporaryDirectory() as folder:
            now=datetime(2026,9,28)
            path=self.fixture(folder,now)
            calls=[]
            outer=self.caller(calls)
            def nested(*args):
                self.assertEqual(run_president(path,now,key_loader=lambda:('u','fake'),caller=lambda *a:self.fail()),'in corso')
                return outer(*args)
            self.assertEqual(run_president(path,now,key_loader=lambda:('u','fake'),caller=nested),'quotidiano')
            self.assertEqual(len(calls),1)

    def test_unknown_owner_photo_and_html_are_handled(self):
        context={'evidence':[{'id':'foto:s'}]}
        for field,value in [('owner','unknown'),('photo_sha','missing'),('evidence',['unknown'])]:
            result=self.reply(); result['priorities'][0][field]=value
            with self.assertRaises(ValueError): validate_president(result,context)
        with tempfile.TemporaryDirectory() as folder:
            now=datetime(2026,9,28)
            path=self.fixture(folder,now)
            result=self.reply(); result['summary']='<script>alert(1)</script>'
            def caller(*args): return {'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(result)}]}]}
            run_president(path,now,key_loader=lambda:('u','fake'),caller=caller)
            body=export_president(path).read_text(encoding='utf-8')
            self.assertNotIn('<script>',body)
            self.assertIn('&lt;script&gt;',body)


if __name__=='__main__': unittest.main()
