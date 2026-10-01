"""Live shop safety: purchase state, exact legacy IDs, and duplicate creation."""
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
import sqlite3
import tempfile
import unittest

from direttore_autonomo import check_public_shop, publish_due
from pubblicazione import _create_one, CreationNeedsReview


class StoreSafetyTests(unittest.TestCase):
    def catalog(self, path):
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript('''CREATE TABLE photos(
                sha TEXT PRIMARY KEY, first_name TEXT, status TEXT, image_id TEXT,
                product_id TEXT, legacy_product_id TEXT, ai_title TEXT, ai_description TEXT);
                INSERT INTO photos VALUES ('sha','photo.jpg','Pronta','image-1','main','old','Opera','Descrizione');''')

    def test_sold_out_public_offer_is_restored_without_republishing(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'catalogo.sqlite'; self.catalog(path)
            state={'main':'SOLD_OUT','old':'AVAILABLE'}
            access={'main':'PUBLIC','old':'PUBLIC'}
            catalog=lambda *args:[{'id':p,'name':'Opera','access':{'type':access[p]}} for p in state]
            def get(*args):
                pid=args[-1]
                return {'id':pid,'state':{'type':state[pid]},'access':{'type':access[pid]},
                        'variants':[{'stock':{'type':'UNLIMITED'}}]}
            def available(*args): state[args[-2]]='AVAILABLE'
            def hide(*args): access[args[-1]]='HIDDEN'
            result=check_public_shop(path,credential_loader=lambda:('u','p'),catalog_loader=catalog,
                                     product_loader=get,availability_setter=available,hide_setter=hide)
            self.assertEqual((result['restored'],result['hidden_duplicates']), (1,1))
            self.assertEqual((access['main'],access['old'],state['main']),('PUBLIC','HIDDEN','AVAILABLE'))
            again=check_public_shop(path,credential_loader=lambda:('u','p'),catalog_loader=catalog,
                                    product_loader=get,availability_setter=available,hide_setter=hide)
            self.assertEqual((again['restored'],again['hidden_duplicates']),(0,0))

    def test_zero_stock_does_not_claim_available(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'catalogo.sqlite'; self.catalog(path)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("UPDATE photos SET legacy_product_id=NULL")
            product={'id':'main','name':'Opera','access':{'type':'PUBLIC'},
                     'state':{'type':'SOLD_OUT'},'variants':[{'stock':{'type':'LIMITED','inStock':0}}]}
            result=check_public_shop(path,credential_loader=lambda:('u','p'),
                     catalog_loader=lambda *args:[product],product_loader=lambda *args:product,
                     availability_setter=lambda *args:self.fail('cannot create inventory'))
            self.assertEqual(result['restored'],0)
            self.assertIn('varianti',result['issues'][0])

    def test_other_public_title_blocks_scheduled_publication(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'catalogo.sqlite'
            with closing(sqlite3.connect(path)) as db, db:
                db.executescript('''CREATE TABLE director_plan(id INTEGER PRIMARY KEY,product_id TEXT,title TEXT,
                    position INTEGER,proposed_at TEXT,reason TEXT,status TEXT);
                    INSERT INTO director_plan VALUES (1,'new','Opera',1,'2026-09-25T18:30','','Approvata');
                    CREATE TABLE bot_settings(key TEXT PRIMARY KEY,value TEXT);
                    INSERT INTO bot_settings VALUES ('director_auto_enabled','1');''')
            result=publish_due(path,product_setter=lambda *args:self.fail('duplicate published'),
                product_getter=lambda *args:'HIDDEN',credential_loader=lambda:('u','p'),
                catalog_loader=lambda *args:[{'id':'other','name':'Opera','access':{'type':'PUBLIC'}}])
            self.assertEqual(result,0)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT status FROM director_plan').fetchone()[0], 'Doppione da verificare')

    def test_existing_title_blocks_new_draft(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder); path=base/'catalogo.sqlite'; self.catalog(path)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("UPDATE photos SET product_id=NULL,image_id='image-1',legacy_product_id=NULL")
            (base/'photo.jpg').write_bytes(b'picture')
            with (patch('pubblicazione.Vault') as vault,
                  patch('pubblicazione.template_details',return_value=({},'r')),
                  patch('pubblicazione.list_products',return_value=[{'id':'existing','name':'Opera','access':{'type':'PUBLIC'}}]),
                  patch('pubblicazione.create_hidden_draft') as create):
                vault.return_value.load.return_value=('u','p')
                with self.assertRaises(CreationNeedsReview):
                    _create_one(path,base,'sha','photo.jpg','template',10)
                create.assert_not_called()


if __name__=='__main__': unittest.main()
