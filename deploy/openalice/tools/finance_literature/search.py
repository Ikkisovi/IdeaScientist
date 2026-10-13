#!/usr/bin/env python3
"""Search the QNAP finance extension; opt into its metadata-only catalog."""
import argparse
import json
from pathlib import Path
import re
import sqlite3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('db', type=Path)
    parser.add_argument('query')
    parser.add_argument('--k', type=int, default=20)
    parser.add_argument('--metadata', action='store_true', help='also search title/abstract of unavailable bodies')
    args = parser.parse_args()
    with sqlite3.connect(f'file:{args.db}?mode=ro&immutable=1', uri=True) as db:
        match = ' OR '.join('"'+t+'"' for t in re.findall(r'[a-zA-Z0-9]+', args.query) if len(t) >= 3)
        if args.metadata:
            terms = re.findall(r'[a-zA-Z0-9]+', args.query)[:12]
            where = ' OR '.join('(title LIKE ? OR abstract LIKE ?)' for _ in terms) or '0'
            params = [value for term in terms for value in ('%'+term+'%', '%'+term+'%')]
            rows = db.execute('SELECT id,title,source,length(full_text),NULL FROM papers WHERE '+where+
                              ' ORDER BY title LIMIT ?', [*params,args.k])
        else:
            rows = db.execute('''SELECT p.id,p.title,p.source,length(p.full_text),bm25(papers_fts)
                FROM papers_fts f JOIN papers p ON p.id=f.rowid
                WHERE papers_fts MATCH ? ORDER BY bm25(papers_fts) LIMIT ?''', (match,args.k))
        for pid, title, source, length, score in rows:
            print(json.dumps({'id': pid, 'title': title, 'source': source, 'fulltext_chars': length,
                              'metadata_only': not bool(length), 'bm25': score}))


if __name__ == '__main__':
    main()
