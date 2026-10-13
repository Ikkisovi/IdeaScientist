"""Attach hash-bound paper/repository evidence to existing IdeaScientist tools."""
import hashlib
import json
from pathlib import Path
import sqlite3


def install(corpus, path, expected_sha256, availability_date):
    path=Path(path)
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
    if not expected_sha256 or h.hexdigest()!=expected_sha256:
        raise ValueError('Code index publication hash differs')

    def repositories(pid, cutoff):
        if availability_date>=cutoff:return []
        with sqlite3.connect(f'file:{path}?mode=ro&immutable=1',uri=True) as db:
            rows=db.execute('''SELECT l.repo,r.json,group_concat(DISTINCT l.relation)
                FROM links l JOIN papers p USING(paper_key) JOIN repos r ON r.repo=l.repo
                WHERE p.paper_id=? GROUP BY l.repo LIMIT 4''',(int(pid),)).fetchall()
        output=[]
        for repo,raw,relation in rows:
            record=json.loads(raw)
            output.append({k:record.get(k) for k in ('repo','url','state','license_spdx',
                'open_source_license_detected','revision')} | {'paper_relation':relation,
                'authorship_verified':False,'code_executed':False})
        return output

    original_search=corpus.keyword_search
    original_biblio=corpus.get_paper_biblio

    def keyword_search(queries,k=40,cutoff_date=corpus.CUTOFF_DATE):
        return [dict(row,github_repositories=repositories(row['id'],cutoff_date))
                for row in original_search(queries,k,cutoff_date)]

    def get_paper_biblio(pid):
        row=original_biblio(pid)
        return dict(row,github_repositories=repositories(pid,corpus.CUTOFF_DATE)) if row else row

    corpus.keyword_search=keyword_search
    corpus.get_paper_biblio=get_paper_biblio
