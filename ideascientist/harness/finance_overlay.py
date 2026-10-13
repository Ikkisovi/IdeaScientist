"""Read-only financial literature extension for the IdeaScientist corpus surface."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3


def install(corpus, path, expected_sha256):
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if not expected_sha256 or digest != expected_sha256:
        raise ValueError('Financial corpus requires its exact publication hash')

    def connection():
        return sqlite3.connect(f'file:{path}?mode=ro&immutable=1', uri=True)

    def row(pid, cutoff):
        with connection() as db:
            db.row_factory = sqlite3.Row
            result = db.execute('SELECT * FROM papers WHERE id=? AND availability_date<?',
                                (int(pid), cutoff)).fetchone()
        return dict(result) if result else None

    original_search = corpus.keyword_search
    original_biblio = corpus.get_paper_biblio
    original_body = corpus.get_stored_full_text
    original_record = corpus.get_paper_record
    original_fields = corpus.get_paper_fields

    def finance_search(queries, k, cutoff):
        best = {}
        with connection() as db:
            for query in queries[:12]:
                terms = re.findall(r'[A-Za-z0-9]+', query)
                match = ' OR '.join('"' + term + '"' for term in terms[:48] if len(term) >= 3)
                if not match:
                    continue
                for pid, title, score in db.execute('''SELECT f.rowid,p.title,bm25(papers_fts)
                    FROM papers_fts f JOIN papers p ON p.id=f.rowid
                    WHERE papers_fts MATCH ? AND p.availability_date<? ORDER BY bm25(papers_fts) LIMIT ?''',
                    (match, cutoff, k)):
                    if pid not in best or score < best[pid]['bm25']:
                        best[pid] = {'id': pid, 'title': title, 'bm25': float(score), 'corpus': 'finance'}
        return sorted(best.values(), key=lambda r: r['bm25'])[:k]

    def keyword_search(queries, k=40, cutoff_date=corpus.CUTOFF_DATE):
        base = original_search(queries, k, cutoff_date)
        finance = finance_search(queries, k, cutoff_date)
        # Scores from different BM25 collections are not numerically comparable.
        # Reserve every fourth rank for a matching finance result, deduplicated by id.
        output, seen = [], set()
        while (base or finance) and len(output) < k:
            queue = finance if finance and (len(output) % 4 == 3 or not base) else base
            item = dict(queue.pop(0))
            if item['id'] in seen:
                continue
            seen.add(item['id'])
            item['corpus'] = item.get('corpus', 'svalbard')
            item['retrieval_rank'] = len(output) + 1
            output.append(item)
        return output

    def get_paper_biblio(pid):
        record = row(pid, corpus.CUTOFF_DATE)
        if not record:
            return original_biblio(pid) if int(pid) < 10_000_000_000 else None
        year = re.search(r'(?:19|20)\d{2}', str(record['date']))
        return {'id': int(pid), 'title': record['title'], 'abstract': record['abstract'],
                'date': record['date'], 'year': year[0] if year else '', 'url': record['url'],
                'source': record['source'], 'availability_date': record['availability_date'],
                'fulltext_available': bool(record['full_text']), 'doi': record['doi']}

    def get_stored_full_text(pid):
        record = row(pid, corpus.CUTOFF_DATE)
        if record:
            # A bibliographic abstract is never represented as a paper body.
            return record['full_text'] or ''
        return original_body(pid) if int(pid) < 10_000_000_000 else ''

    def get_paper_record(pid):
        if row(pid, corpus.CUTOFF_DATE) and int(pid) >= 10_000_000_000:
            return None
        return original_record(pid)

    def get_paper_fields(pid):
        record = row(pid, corpus.CUTOFF_DATE)
        if not record:
            return original_fields(pid) if int(pid) < 10_000_000_000 else None
        return {**get_paper_biblio(pid), 'authors': record['authors'], 'venue': record['source'],
                'arxiv_id': '', 'challenge': '', 'problem_definition': '', 'intuition': '', 'solution': '',
                'results_masked_available': False}

    for name, function in locals().copy().items():
        if name in ('keyword_search', 'get_paper_biblio', 'get_stored_full_text', 'get_paper_record', 'get_paper_fields'):
            setattr(corpus, name, function)
