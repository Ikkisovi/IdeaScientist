#!/usr/bin/env python3
"""Build a per-field FTS5 index over the Svalbard Idea Vault HF records.

Columns are searchable separately (title, challenge, problem_definition,
intuition, solution), so a query can target "who fought the same difficulty"
(challenge) and filter by arXiv category and submission date to force
cross-domain retrieval. Used by ``literature_library.py vault-search``.

  svalbard_vault_fts.py --records <vault>/records --out <dir>/vault_fts.db
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sqlite3
import subprocess
import sys
import time

SCHEMA = """
CREATE VIRTUAL TABLE vault_fts USING fts5(
    title, challenge, problem_definition, intuition, solution,
    content='', tokenize='porter unicode61');
CREATE TABLE vault_meta (
    rowid INTEGER PRIMARY KEY, arxiv_id TEXT, date TEXT, primary_cat TEXT,
    categories TEXT, split TEXT, title TEXT, intuition_head TEXT);
"""


def sections(md: str) -> dict[str, str]:
    out = {}
    for block in re.split(r'^## ', md or '', flags=re.M)[1:]:
        head, _, body = block.partition('\n')
        out[head.strip().lower()] = body.strip()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--records', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args(argv)
    if os.path.exists(args.out):
        print(f'{args.out} exists; refusing to overwrite', file=sys.stderr)
        return 2
    tmp = args.out + '.building'
    if os.path.exists(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    con.execute('PRAGMA journal_mode=OFF')
    con.execute('PRAGMA synchronous=OFF')
    con.executescript(SCHEMA)
    files = sorted(glob.glob(os.path.join(args.records, '*', '*.jsonl.zst')))
    n, t0 = 0, time.time()
    for f in files:
        p = subprocess.Popen(['zstd', '-dc', f], stdout=subprocess.PIPE)
        fts, meta = [], []
        for line in p.stdout:
            r = json.loads(line)
            n += 1
            sec = sections(r.get('proposal_masked', ''))
            pd_full = r.get('problem_definition') or ''
            challenge = sec.get('problem') or (pd_full.split('\n\n', 1)[1] if '\n\n' in pd_full else '')
            pd = sec.get('problem definition') or pd_full.split('\n\n', 1)[0]
            solution = ' '.join(x for x in (sec.get('method'), sec.get('model details')) if x)
            cats = r.get('categories') or []
            fts.append((n, r.get('title'), challenge, pd, r.get('intuition') or '', solution))
            meta.append((n, r.get('arxiv_id'), r.get('date'), cats[0] if cats else None, ' '.join(cats),
                         r.get('split'), r.get('title'), (r.get('intuition') or '')[:400]))
        if p.wait() != 0:
            raise RuntimeError(f'zstd failed on {f}')
        con.executemany('INSERT INTO vault_fts(rowid, title, challenge, problem_definition, intuition, solution) '
                        'VALUES (?,?,?,?,?,?)', fts)
        con.executemany('INSERT INTO vault_meta VALUES (?,?,?,?,?,?,?,?)', meta)
        con.commit()
        print(f'{os.path.relpath(f, args.records)} rows={n} {time.time() - t0:.0f}s', flush=True)
    con.execute('CREATE INDEX idx_meta_arxiv ON vault_meta(arxiv_id)')
    con.execute("INSERT INTO vault_fts(vault_fts) VALUES('optimize')")
    con.commit()
    con.close()
    os.rename(tmp, args.out)
    print(f'done rows={n} {time.time() - t0:.0f}s')
    return 0


if __name__ == '__main__':
    sys.exit(main())
