import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

from finance_overlay import install


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'finance.db'
        with sqlite3.connect(self.path) as db:
            db.executescript('''CREATE TABLE papers(id INTEGER PRIMARY KEY,title,authors,date,availability_date,
                source,url,abstract,doi,full_text,meta_json);
                CREATE VIRTUAL TABLE papers_fts USING fts5(title,abstract,body);''')
            db.execute('INSERT INTO papers VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (10_000_000_001,'Finance factor method','','2015','2026-10-13','test','','abstract','',
                 'actual full body', '{}'))
            db.execute('INSERT INTO papers_fts(rowid,title,abstract,body) VALUES(?,?,?,?)',
                       (10_000_000_001,'Finance factor method','abstract','actual full body'))
            db.execute('INSERT INTO papers VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (10_000_000_002,'Unavailable factor paper','','2014','2026-10-13','test','','abstract','', '', '{}'))
        self.hash = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def tearDown(self):
        self.temp.cleanup()

    def corpus(self, cutoff):
        return SimpleNamespace(CUTOFF_DATE=cutoff,
            keyword_search=lambda q,k,c: [{'id':i,'title':'base','bm25':-100000} for i in range(1,6)],
            get_paper_biblio=lambda pid: {'id':pid,'title':'base'} if pid<10 else None,
            get_stored_full_text=lambda pid: 'base body' if pid<10 else '',
            get_paper_record=lambda pid: {'old':True} if pid<10 else None,
            get_paper_fields=lambda pid: {'old':True} if pid<10 else None)

    def test_capture_date_fences_old_publication(self):
        c=self.corpus('2026-01-01')
        install(c,self.path,self.hash)
        self.assertNotIn(10_000_000_001,[r['id'] for r in c.keyword_search(['factor'])])
        self.assertIsNone(c.get_paper_biblio(10_000_000_001))
        self.assertEqual(c.get_stored_full_text(10_000_000_001),'')
        self.assertEqual(c.get_stored_full_text(1),'base body')

    def test_fulltext_ranking_and_no_abstract_body(self):
        c=self.corpus('2026-10-14')
        install(c,self.path,self.hash)
        rows=c.keyword_search(['factor'])
        self.assertEqual(rows[3]['id'],10_000_000_001)
        self.assertEqual(c.get_stored_full_text(10_000_000_001),'actual full body')
        self.assertEqual(c.get_stored_full_text(10_000_000_002),'')
        self.assertNotIn(10_000_000_002,[r['id'] for r in rows])
        self.assertIsNone(c.get_paper_record(10_000_000_001))

    def test_publication_hash_required(self):
        with self.assertRaises(ValueError):
            install(self.corpus('2026-10-14'),self.path,'wrong')


if __name__=='__main__':
    unittest.main()
