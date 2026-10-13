import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

from code_index import links, sha
from code_overlay import install


class CodeEvidenceTests(unittest.TestCase):
    def test_link_normalization_and_relation(self):
        text='Our code is available at https://github.com/Author/\nMethod.git. '
        self.assertEqual(next(links(text))[0], 'author/method')
        self.assertEqual(next(links(text))[2], 'paper_code_claim')
        self.assertEqual(next(links('https://github.com/pytorch/pytorch'))[2], 'common_dependency')
        self.assertEqual(list(links('https://github.com/topics/finance')), [])

    def test_index_hash_and_historical_fence(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'code.db';db=sqlite3.connect(path)
            db.executescript('CREATE TABLE papers(paper_key TEXT,paper_id INTEGER);'
                'CREATE TABLE links(paper_key TEXT,repo TEXT,relation TEXT);'
                'CREATE TABLE repos(repo TEXT,json TEXT);')
            db.execute('INSERT INTO papers VALUES(?,?)',('paper:7',7))
            db.execute('INSERT INTO links VALUES(?,?,?)',('paper:7','a/b','paper_code_claim'))
            db.execute('INSERT INTO repos VALUES(?,?)',('a/b',json.dumps({'repo':'a/b',
                'state':'public_verified','license_spdx':'MIT','open_source_license_detected':True})))
            db.commit();db.close()
            corpus=SimpleNamespace(CUTOFF_DATE='2026-10-14',
                keyword_search=lambda q,k,c:[{'id':7,'title':'fixture'}],
                get_paper_biblio=lambda pid:{'id':pid})
            with self.assertRaises(ValueError):install(corpus,path,'wrong','2026-10-13')
            install(corpus,path,sha(path),'2026-10-13')
            self.assertTrue(corpus.keyword_search(['fixture'])[0]['github_repositories'])
            self.assertEqual(corpus.keyword_search(['fixture'],cutoff_date='2026-01-01')[0]['github_repositories'],[])
            self.assertFalse(corpus.get_paper_biblio(7)['github_repositories'][0]['authorship_verified'])


if __name__=='__main__':unittest.main()
