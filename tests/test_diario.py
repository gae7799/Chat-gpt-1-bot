from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from registro import record, save_texts, text_folder, logical_review


class DiaryTests(unittest.TestCase):
    def test_text_export_is_readable_and_not_duplicated(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = Path(folder) / 'catalogo.sqlite'
            record(catalog,'Fotografie','Luce','Selezionata',
                   '{"ai_title":"Luce","ai_reason":"Composizione equilibrata"}')
            self.assertEqual(save_texts(catalog),1)
            self.assertEqual(save_texts(catalog),0)
            files = list(text_folder(catalog).glob('*.txt'))
            self.assertEqual(len(files),1)
            self.assertIn('Motivazione: Composizione equilibrata',files[0].read_text(encoding='utf-8'))
            self.assertEqual(list(text_folder(catalog).glob('*.tmp')),[])
            record(catalog,'Sessione','Bot','Avvio')
            self.assertEqual(save_texts(catalog),1)
            self.assertEqual(len(list(text_folder(catalog).glob('*.txt'))),2)

    def test_review_every_five_minutes_even_across_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = Path(folder) / 'catalogo.sqlite'
            moment = datetime(2026,9,20,12,tzinfo=timezone.utc)
            self.assertTrue(logical_review(catalog,moment))
            self.assertFalse(logical_review(catalog,moment+timedelta(seconds=299)))
            self.assertTrue(logical_review(catalog,moment+timedelta(seconds=300)))
            self.assertEqual(save_texts(catalog),2)
