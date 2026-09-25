from contextlib import closing
from datetime import datetime,timedelta
from pathlib import Path
import json
import tempfile
import unittest
import test_daily
from analisi_giornaliera import market_report,run_daily,queue_retry,connect
from openai_vision import http_diagnostic,OpenAIError,_output_text


class DiagnosticsTests(unittest.TestCase):
    def test_final_message_not_search_preamble(self):
        reply={'status':'completed','output':[
            {'type':'message','phase':'commentary','content':[{'type':'output_text','text':'Cerco sul web...'}]},
            {'type':'web_search_call','status':'completed'},
            {'type':'message','phase':'final_answer','content':[{'type':'output_text','text':'Prezzo con fonte',
                'annotations':[{'type':'url_citation','url':'https://example.org','title':'Fonte','start_index':11,'end_index':16}]}]}]}
        report=market_report(key_loader=lambda:('u','k'),caller=lambda *a:reply)
        self.assertEqual(report['text'],'Prezzo con fonte')
        self.assertEqual(len(report['sources']),1)

    def test_http_details_never_expose_response_secrets(self):
        text=http_diagnostic(429,{'code':'insufficient_quota','message':'sk-SECRET','param':'sk-SECRET'})
        self.assertIn('Credito',text);self.assertNotIn('SECRET',text)
        self.assertIn('max_tool_calls',http_diagnostic(400,{'param':'max_tool_calls','code':'unsupported_parameter'}))

    def test_truncation_is_specific(self):
        with self.assertRaisesRegex(OpenAIError,'token'):
            _output_text({'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'}})

    def test_safe_error_saved_and_one_manual_extra(self):
        helper=test_daily.DailyTests()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'catalogo.sqlite';helper.setup_db(path)
            calls,fns=helper.fixtures();now=datetime(2026,9,24,9)
            run_daily(path,now,**fns)
            def fail():raise OpenAIError('Credito API esaurito.')
            fns['market_fn']=fail
            run_daily(path,now,**fns)
            run_daily(path,now+timedelta(minutes=16),**fns)
            self.assertIn('rimessa',queue_retry(path,'2026-09-24'))
            run_daily(path,now+timedelta(minutes=17),**fns)
            self.assertIn('già stato usato',queue_retry(path,'2026-09-24'))
            self.assertEqual(run_daily(path,now+timedelta(hours=2),**fns),'limite')
            with closing(connect(path)) as db, db:
                row=db.execute("SELECT attempts,error FROM daily_agents WHERE stage='mercato'").fetchone()
                shop=db.execute("SELECT state FROM daily_agents WHERE stage='negozio'").fetchone()[0]
            self.assertEqual(row,(3,'Credito API esaurito.'));self.assertEqual(shop,'completato')


if __name__=='__main__':unittest.main()
