#!/usr/bin/env python3
"""Rebuild an IdeaScientist-compatible vault DB from the published HF records.

The Hugging Face release of the Svalbard Idea Vault (Jerry999/SvalbardIdeaVault)
ships flattened prose fields; the IdeaScientist harness expects the SQLite
schema written by its own arXiv crawl (``papers`` + ``metadata_results_masked``
with a nested ``fields_json``). This importer maps each record's
``proposal_masked`` Markdown sections back to the record keys that
``ideascientist.vault.fields.field_texts`` reads, keeping the section text as
prose strings (``serialize_labeled`` passes strings through unchanged).

Not reconstructible from the release: full text, raw LaTeX, and the citation
graph. ``paper_full_text`` and ``citations`` are created empty, so citation
F1 must be skipped and novelty/retrieval run on the masked records only.

Usage:
  svalbard_vault_import.py --records <vault>/records --out /local/ssd/idea_vault.db
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time

# proposal_masked "## Heading" -> results-masked record key
SECTION_KEYS = {
    'thesis': 'one_sentence_thesis',
    'topic': 'topic_relevance',
    'problem': 'core_problem',
    'key novelty': 'key_novelty',
    'problem definition': 'problem_definition',
    'key terms': 'key_terms',
    'related work': 'related_work',
    'method': 'method',
    'model details': 'model_details',
    'comparison to sota': 'comparison_to_sota',
    'proposed evaluation': 'proposed_evaluation',
    'falsifiable predictions': 'falsifiable_predictions',
    'limitations': 'limitations',
}

SCHEMA = """
CREATE TABLE papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT UNIQUE, authors TEXT, date TEXT,
    venue TEXT, source TEXT, url TEXT, abstract TEXT, arxiv_id TEXT, doi TEXT);
CREATE TABLE metadata_results_masked (
    paper_id INTEGER PRIMARY KEY, fields_json TEXT, model TEXT, created_at TEXT);
CREATE TABLE paper_full_text (
    paper_id INTEGER PRIMARY KEY, arxiv_id TEXT, source_url TEXT, content_source TEXT,
    full_text TEXT, raw_tex TEXT, bbl_content TEXT, char_len INTEGER, fetch_status TEXT,
    fetch_error TEXT, fetched_at TEXT);
CREATE TABLE citations (
    id INTEGER PRIMARY KEY AUTOINCREMENT, source_paper_id INTEGER NOT NULL, cited_paper_id INTEGER,
    direction TEXT NOT NULL, cited_title TEXT NOT NULL, verified_status TEXT, confidence REAL,
    s2_paper_id TEXT, arxiv_id TEXT, doi TEXT, is_related_work INTEGER, fetched_at TEXT,
    publication_date TEXT);
CREATE TABLE svalbard_split (paper_id INTEGER PRIMARY KEY, arxiv_id TEXT, split TEXT);
CREATE TABLE svalbard_import (key TEXT PRIMARY KEY, value TEXT);
"""
INDEXES = """
CREATE INDEX idx_papers_arxiv ON papers(arxiv_id);
CREATE INDEX idx_papers_date ON papers(date);
CREATE INDEX idx_split ON svalbard_split(split);
"""


def split_sections(md: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for block in re.split(r'^## ', md or '', flags=re.M)[1:]:
        head, _, body = block.partition('\n')
        key = SECTION_KEYS.get(head.strip().lower())
        if key and body.strip():
            out[key] = body.strip()
    return out


def to_record(r: dict) -> dict:
    sec = split_sections(r.get('proposal_masked', ''))
    rec: dict = {'title': r.get('title', '')}
    rec.update({k: v for k, v in sec.items() if k not in ('core_problem', 'key_novelty', 'problem_definition')})
    # Top-level problem_definition = formal part (first paragraph); challenge = "## Problem".
    pd = (r.get('problem_definition') or '').split('\n\n', 1)[0].strip()
    rec['problem_definition'] = sec.get('problem_definition') or pd
    challenge = sec.get('core_problem') or ''
    if not challenge and '\n\n' in (r.get('problem_definition') or ''):
        challenge = r['problem_definition'].split('\n\n', 1)[1].strip()
    rec['core_problem'] = {'problem_statement': challenge}
    rec['key_novelty'] = split_novelty(sec.get('key_novelty') or r.get('intuition') or '')
    return rec


def split_novelty(text: str) -> dict:
    """'Main idea: X. Explanation: Y' -> {'main_idea': X, 'explanation': Y} (labels re-added on read)."""
    m = re.match(r'\s*Main idea:\s*(.*?)(?:\.?\s*Explanation:\s*(.*))?\s*$', text, flags=re.S)
    if not m:
        return {'explanation': text}
    return {'main_idea': m.group(1).strip(), 'explanation': (m.group(2) or '').strip()}


def zstd_lines(path: str):
    p = subprocess.Popen(['zstd', '-dc', path], stdout=subprocess.PIPE)
    for line in p.stdout:
        if line.strip():
            yield json.loads(line)
    if p.wait() != 0:
        raise RuntimeError(f'zstd failed on {path}')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--records', required=True, help='<vault>/records directory')
    ap.add_argument('--out', required=True, help='new SQLite file (must not exist)')
    ap.add_argument('--limit', type=int, default=0, help='stop after N records (smoke test)')
    args = ap.parse_args(argv)
    if os.path.exists(args.out):
        print(f'{args.out} exists; refusing to overwrite', file=sys.stderr)
        return 2
    files = []
    for split in ('test', 'val', 'train', 'corpus'):
        files += sorted(glob.glob(os.path.join(args.records, split, '*.jsonl.zst')))
    tmp = args.out + '.building'
    if os.path.exists(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    con.execute('PRAGMA journal_mode=OFF')
    con.execute('PRAGMA synchronous=OFF')
    con.executescript(SCHEMA)
    n = dup = 0
    t0 = time.time()
    for f in files:
        rows = []
        for r in zstd_lines(f):
            rows.append(r)
            if args.limit and n + len(rows) >= args.limit:
                break
        for r in rows:
            cur = con.execute(
                'INSERT OR IGNORE INTO papers(title, authors, date, venue, source, url, abstract, arxiv_id, doi) '
                'VALUES (?,?,?,?,?,?,?,?,?)',
                (r.get('title'), json.dumps(r.get('authors') or []), r.get('date'), None, 'arxiv',
                 r.get('arxiv_url'), r.get('abstract'), r.get('arxiv_id'), None))
            if cur.rowcount == 0:
                dup += 1  # title UNIQUE, as in the upstream crawl schema
                continue
            pid = cur.lastrowid
            con.execute('INSERT INTO metadata_results_masked VALUES (?,?,?,?)',
                        (pid, json.dumps(to_record(r), ensure_ascii=False), 'hf-release', r.get('generated_at')))
            con.execute('INSERT INTO svalbard_split VALUES (?,?,?)', (pid, r.get('arxiv_id'), r.get('split')))
        n += len(rows)
        con.commit()
        print(f'{os.path.relpath(f, args.records)}  rows={n}  title_dups={dup}  {time.time() - t0:.0f}s', flush=True)
        if args.limit and n >= args.limit:
            break
    con.executescript(INDEXES)
    manifest = os.path.join(os.path.dirname(args.records.rstrip('/')), 'download_manifest.json')
    meta = {'records_dir': os.path.abspath(args.records), 'rows_read': n, 'title_dups_skipped': dup,
            'built_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'importer_sha256': hashlib.sha256(open(__file__, 'rb').read()).hexdigest(),
            'hf_revision': json.load(open(manifest))['revision'] if os.path.exists(manifest) else None}
    con.executemany('INSERT INTO svalbard_import VALUES (?,?)', [(k, json.dumps(v)) for k, v in meta.items()])
    con.commit()
    con.close()
    os.rename(tmp, args.out)
    print(json.dumps(meta))
    return 0


if __name__ == '__main__':
    sys.exit(main())
