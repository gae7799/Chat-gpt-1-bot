from contextlib import closing
from datetime import datetime
from pathlib import Path
import sqlite3
import tempfile
import unittest

from consiglio_agenti import ask_agent, chat_context, chat_db, chat_history, CHAT_DAILY_LIMIT


class ChatTests(unittest.TestCase):
    def fixture(self, folder):
        path = Path(folder) / 'catalogo.sqlite'
        with closing(chat_db(path)) as db, db:
            db.executescript("""
                CREATE TABLE photos(sha TEXT,first_name TEXT,status TEXT,product_id TEXT,
                                    ai_title TEXT,ai_theme TEXT,ai_reason TEXT,created TEXT);
                CREATE TABLE files(path TEXT,sha TEXT,present INTEGER);
                INSERT INTO photos VALUES ('s','mare.jpg','Bozza creata','p','Me and Sea',
                                          'mare','Selezionata','2026-10-01');
                INSERT INTO files VALUES ('mare.jpg','s',1);
                INSERT INTO files VALUES ('copia-mare.jpg','s',1);
            """)
        return path

    def test_copies_are_files_and_chat_is_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.fixture(folder)
            data = chat_context(path)
            self.assertEqual(data['duplicates'][0]['copies'],2)
            self.assertIn('non scorte',data['notice'])
            calls = []
            def caller(endpoint,key,payload,method,timeout):
                calls.append(payload)
                return {'output':[{'type':'message','content':[
                    {'type':'output_text','text':'Sono due file identici, non due stampe.'}]}]}
            kwargs={'key_loader':lambda:('openai','fake'),'caller':caller,
                    'moment':datetime(2026,10,1,18)}
            answer = ask_agent(path,'Cosa significa Copie?',**kwargs)
            self.assertIn('file identici',answer)
            self.assertEqual(calls[0]['model'],'gpt-6-sol')
            self.assertFalse(calls[0]['store'])
            self.assertIn('Non esegui azioni',calls[0]['instructions'])
            self.assertIn('due file identici', (Path(folder)/'CHAT_AGENTE/conversazione.txt')
                          .read_text(encoding='utf-8'))
            self.assertEqual(chat_history(path)[0][3],'completato')
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT status FROM photos').fetchone()[0],'Bozza creata')

    def test_no_key_does_not_consume_quota_and_failed_call_does(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.fixture(folder)
            moment = datetime(2026,10,1,18)
            with self.assertRaisesRegex(RuntimeError,'Collega'):
                ask_agent(path,'Ciao',key_loader=lambda:None,moment=moment)
            self.assertEqual(chat_history(path),[])
            def failed(*args): raise RuntimeError('bad secret external response')
            with self.assertRaisesRegex(RuntimeError,'Risposta non disponibile'):
                ask_agent(path,'Ciao',key_loader=lambda:('openai','fake'),
                          caller=failed,moment=moment)
            rows = chat_history(path)
            self.assertEqual(rows[0][3],'errore')
            self.assertNotIn('bad secret',str(rows))

    def test_daily_limit_survives_restart_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.fixture(folder)
            with closing(chat_db(path)) as db, db:
                db.executemany("INSERT INTO agent_chat(day,at,question,state) VALUES ('2026-10-01','t','q','errore')",
                               [()] * CHAT_DAILY_LIMIT)
            with self.assertRaisesRegex(RuntimeError,'Limite chat'):
                ask_agent(path,'Ciao',key_loader=lambda:('openai','fake'),
                          caller=lambda *args:self.fail('network'),moment=datetime(2026,10,1,18))


if __name__ == '__main__':
    unittest.main()
