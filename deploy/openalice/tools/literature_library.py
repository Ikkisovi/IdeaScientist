#!/usr/bin/env python3
"""Fetched-paper library on the QNAP WorkstationLink share.

Stdlib only; any python3 works. Downloaded PDFs are untrusted data: they are
hashed and converted with ``pdftotext`` but never executed or imported.

Layout (root defaults to /mnt/qnap-workstation/literature-library):
  index.jsonl                         rebuilt from every meta.json (reindex)
  papers/arxiv/<base-id>/<version>/   paper.pdf, fulltext.txt, fulltext.layout.txt, meta.json
  papers/arxiv/<base-id>/notes/       study notes (<YYYYMMDD>-<slug>.md)
  papers/arxiv/<base-id>/graph/       Semantic Scholar reference/citation snapshots

A fetched version directory is write-once: re-fetching verifies its hashes and
never rewrites it. A newer arXiv version gets its own sibling directory.

Usage:
  literature_library.py search "factor mining llm" --cat q-fin.ST --to 2025-12-31
  literature_library.py fetch 2610.04074
  literature_library.py graph 2610.04074 --direction references --save
  literature_library.py note 2610.04074 --slug stack-correlation
  literature_library.py list | show 2610.04074 | reindex
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 'literature-library-paper-v1'
DEFAULT_ROOT = Path('/mnt/qnap-workstation/literature-library')
QNAP_MOUNT = Path('/mnt/qnap-workstation')
ARXIV_API = 'https://export.arxiv.org/api/query'
ARXIV_PDF = 'https://arxiv.org/pdf/'
S2_API = 'https://api.semanticscholar.org/graph/v1/paper/'
USER_AGENT = 'openalice-literature-library/1 (research paper archive)'
ATOM = {'a': 'http://www.w3.org/2005/Atom', 'arxiv': 'http://arxiv.org/schemas/atom',
        'os': 'http://a9.com/-/spec/opensearch/1.1/'}
EXIT_UNAVAILABLE = 75

NEW_ID = re.compile(r'(\d{4}\.\d{4,5})(v\d+)?')
OLD_ID = re.compile(r'([a-z\-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?')


# ==================== Identifiers ====================

def parse_arxiv_id(text: str) -> tuple[str, str | None]:
    """Return (base id, version or None) from an id, ``arXiv:`` tag, or abs/pdf URL."""
    s = text.strip()
    s = re.sub(r'^(arxiv:)', '', s, flags=re.I)
    s = re.sub(r'^https?://(www\.|export\.)?arxiv\.org/(abs|pdf)/', '', s)
    s = re.sub(r'\.pdf$', '', s).rstrip('/')
    for pat in (NEW_ID, OLD_ID):
        m = pat.fullmatch(s)
        if m:
            return m.group(1), m.group(2)
    raise ValueError(f'not an arXiv identifier: {text!r}')


def id_dirname(base_id: str) -> str:
    return base_id.replace('/', '_')


# ==================== Root / filesystem ====================

def resolve_root(arg: str | None) -> Path:
    root = Path(arg or os.environ.get('OPENALICE_LITERATURE_ROOT') or DEFAULT_ROOT)
    if root.is_relative_to(QNAP_MOUNT):
        try:
            os.listdir(QNAP_MOUNT)  # trigger the systemd automount
        except OSError:
            pass
        if not os.path.ismount(QNAP_MOUNT):
            print(f'QNAP share not mounted at {QNAP_MOUNT}; refusing to write to the local disk',
                  file=sys.stderr)
            sys.exit(EXIT_UNAVAILABLE)
    (root / 'papers' / 'arxiv').mkdir(parents=True, exist_ok=True)
    (root / '.staging').mkdir(exist_ok=True)
    return root


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def write_json_atomic(path: Path, obj) -> None:
    tmp = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + '\n')
    os.replace(tmp, path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


# ==================== HTTP ====================

def http_get(url: str, timeout: int = 60, retries: int = 3) -> bytes:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - retried, then re-raised
            last = e
            time.sleep(3 * (attempt + 1))  # arXiv asks for >=3 s between calls
    raise RuntimeError(f'GET failed after {retries} attempts: {url}: {last}')


# ==================== arXiv API ====================

def parse_atom_entries(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    out = []
    for e in root.findall('a:entry', ATOM):
        abs_url = e.findtext('a:id', '', ATOM).strip()
        if '/abs/' not in abs_url:  # error entries carry an api/errors id
            raise RuntimeError(f'arXiv API error: {e.findtext("a:summary", "", ATOM).strip()}')
        base, ver = parse_arxiv_id(abs_url)
        pdf = next((l.get('href') for l in e.findall('a:link', ATOM) if l.get('title') == 'pdf'), None)
        prim = e.find('arxiv:primary_category', ATOM)
        out.append({
            'arxiv_id': base,
            'version': ver,
            'title': ' '.join(e.findtext('a:title', '', ATOM).split()),
            'authors': [a.findtext('a:name', '', ATOM) for a in e.findall('a:author', ATOM)],
            'abstract': ' '.join(e.findtext('a:summary', '', ATOM).split()),
            'published': e.findtext('a:published', '', ATOM),
            'updated': e.findtext('a:updated', '', ATOM),
            'primary_category': prim.get('term') if prim is not None else None,
            'categories': [c.get('term') for c in e.findall('a:category', ATOM)],
            'doi': e.findtext('arxiv:doi', None, ATOM),
            'journal_ref': e.findtext('arxiv:journal_ref', None, ATOM),
            'comment': e.findtext('arxiv:comment', None, ATOM),
            'abs_url': abs_url,
            'pdf_url': pdf,
        })
    return out


def date_bound(d: str, end: bool) -> str:
    return datetime.strptime(d, '%Y-%m-%d').strftime('%Y%m%d') + ('2359' if end else '0000')


def build_search_query(terms: str, cat: str | None, date_from: str | None, date_to: str | None) -> str:
    """Plain words become all: terms; strings already using field prefixes pass through."""
    if re.search(r'\b(ti|au|abs|co|jr|cat|rn|id|all):', terms):
        q = terms
    else:
        q = ' AND '.join(f'all:{w}' for w in terms.split())
    if cat:
        q = f'({q}) AND cat:{cat}'
    if date_from or date_to:
        lo = date_bound(date_from, False) if date_from else '199101010000'
        hi = date_bound(date_to, True) if date_to else '209912312359'
        q = f'({q}) AND submittedDate:[{lo} TO {hi}]'
    return q


def arxiv_metadata(base_id: str, version: str | None) -> dict:
    url = ARXIV_API + '?' + urllib.parse.urlencode({'id_list': base_id + (version or '')})
    entries = parse_atom_entries(http_get(url))
    if not entries:
        raise RuntimeError(f'arXiv API returned no entry for {base_id}{version or ""}')
    return entries[0]


# ==================== Index ====================

def iter_meta(root: Path):
    for meta in sorted((root / 'papers' / 'arxiv').glob('*/v*/meta.json')):
        yield json.loads(meta.read_text())


def reindex(root: Path) -> int:
    rows = []
    for m in iter_meta(root):
        rows.append({k: m[k] for k in ('arxiv_id', 'version', 'title', 'published',
                                       'primary_category', 'fetched_utc', 'pdf_sha256', 'path')})
    tmp = root / f'.index.jsonl.{uuid.uuid4().hex}.tmp'
    tmp.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    os.replace(tmp, root / 'index.jsonl')
    return len(rows)


def held_ids(root: Path) -> set[str]:
    return {p.name.replace('_', '/') for p in (root / 'papers' / 'arxiv').iterdir() if p.is_dir()}


# ==================== Commands ====================

def cmd_search(args) -> int:
    root = resolve_root(args.root)
    q = build_search_query(args.terms, args.cat, args.date_from, args.date_to)
    params = {'search_query': q, 'start': 0, 'max_results': args.max,
              'sortBy': args.sort, 'sortOrder': 'descending'}
    entries = parse_atom_entries(http_get(ARXIV_API + '?' + urllib.parse.urlencode(params)))
    held = held_ids(root)
    if args.json:
        for e in entries:
            print(json.dumps({**e, 'in_library': e['arxiv_id'] in held}, ensure_ascii=False))
        return 0
    print(f'# query: {q}  ({len(entries)} results)')
    for e in entries:
        mark = '*' if e['arxiv_id'] in held else ' '
        print(f"{mark} {e['arxiv_id']}{e['version'] or ''}  {e['published'][:10]}  "
              f"[{e['primary_category']}]  {e['title']}")
    return 0


def verify_existing(vdir: Path) -> dict:
    meta = json.loads((vdir / 'meta.json').read_text())
    for name, key in (('paper.pdf', 'pdf_sha256'), ('fulltext.txt', 'text_sha256'),
                      ('fulltext.layout.txt', 'layout_text_sha256')):
        if sha256_file(vdir / name) != meta[key]:
            raise RuntimeError(f'hash mismatch in existing {vdir / name}; not touching it')
    return meta


def pdftotext(pdf: Path, out: Path, layout: bool) -> None:
    cmd = ['pdftotext', '-enc', 'UTF-8'] + (['-layout'] if layout else []) + [str(pdf), str(out)]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)


def fetch_one(root: Path, ident: str) -> dict:
    base, ver = parse_arxiv_id(ident)
    md = arxiv_metadata(base, ver)
    ver = md['version']
    pdir = root / 'papers' / 'arxiv' / id_dirname(base)
    vdir = pdir / ver
    if (vdir / 'meta.json').exists():
        meta = verify_existing(vdir)
        print(f'held  {base}{ver}  verified  {vdir}')
        return meta

    stage = root / '.staging' / f'{id_dirname(base)}{ver}.{uuid.uuid4().hex}'
    stage.mkdir(parents=True)
    try:
        pdf_bytes = http_get(ARXIV_PDF + base + ver, timeout=180)
        if not pdf_bytes.startswith(b'%PDF'):
            raise RuntimeError(f'{base}{ver}: download is not a PDF ({pdf_bytes[:40]!r})')
        (stage / 'paper.pdf').write_bytes(pdf_bytes)
        pdftotext(stage / 'paper.pdf', stage / 'fulltext.txt', layout=False)
        pdftotext(stage / 'paper.pdf', stage / 'fulltext.layout.txt', layout=True)
        tool = subprocess.run(['pdftotext', '-v'], capture_output=True, text=True)
        meta = {
            'schema': SCHEMA,
            **md,
            'source': 'arxiv',
            'path': str(vdir.relative_to(root)),
            'fetched_utc': utc_now(),
            'pdf_source_url': ARXIV_PDF + base + ver,
            'pdf_bytes': len(pdf_bytes),
            'pdf_sha256': sha256_file(stage / 'paper.pdf'),
            'text_sha256': sha256_file(stage / 'fulltext.txt'),
            'layout_text_sha256': sha256_file(stage / 'fulltext.layout.txt'),
            'text_extractor': (tool.stderr or tool.stdout).splitlines()[0] if (tool.stderr or tool.stdout) else 'pdftotext',
        }
        write_json_atomic(stage / 'meta.json', meta)
        pdir.mkdir(exist_ok=True)
        (pdir / 'notes').mkdir(exist_ok=True)
        os.rename(stage, vdir)  # fails if a concurrent fetch already created it
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    print(f'new   {base}{ver}  {md["title"][:90]}  {vdir}')
    return meta


def cmd_fetch(args) -> int:
    root = resolve_root(args.root)
    failures = 0
    for i, ident in enumerate(args.ids):
        if i:
            time.sleep(3)
        try:
            fetch_one(root, ident)
        except Exception as e:  # noqa: BLE001 - report and continue with the batch
            failures += 1
            print(f'FAIL  {ident}: {e}', file=sys.stderr)
    n = reindex(root)
    print(f'index: {n} paper versions')
    return 1 if failures else 0


def cmd_graph(args) -> int:
    root = resolve_root(args.root)
    base, _ = parse_arxiv_id(args.id)
    fields = 'title,year,externalIds,citationCount'
    rows, offset = [], 0
    while True:
        url = (f'{S2_API}arXiv:{base}/{args.direction}?'
               + urllib.parse.urlencode({'fields': fields, 'limit': 100, 'offset': offset}))
        page = json.loads(http_get(url))
        for item in page.get('data', []):
            p = item.get('citedPaper' if args.direction == 'references' else 'citingPaper') or {}
            ext = p.get('externalIds') or {}
            rows.append({'title': p.get('title'), 'year': p.get('year'),
                         'arxiv_id': ext.get('ArXiv'), 'doi': ext.get('DOI'),
                         'citation_count': p.get('citationCount')})
        if page.get('next') is None or offset + 100 >= args.max:
            break
        offset = page['next']
        time.sleep(1)
    held = held_ids(root)
    for r in rows:
        mark = '*' if r['arxiv_id'] and r['arxiv_id'] in held else ' '
        print(f"{mark} {r['arxiv_id'] or '-':>12}  {r['year'] or '----'}  {r['title']}")
    print(f'# {len(rows)} {args.direction} for {base} (Semantic Scholar)')
    if args.save:
        gdir = root / 'papers' / 'arxiv' / id_dirname(base) / 'graph'
        gdir.mkdir(parents=True, exist_ok=True)
        out = gdir / f'{args.direction}-{datetime.now(timezone.utc):%Y%m%d}.json'
        write_json_atomic(out, {'arxiv_id': base, 'direction': args.direction, 'source': 'semantic_scholar',
                                'retrieved_utc': utc_now(), 'rows': rows})
        print(f'saved {out}')
    return 0


NOTE_TEMPLATE = """---
arxiv_id: {arxiv_id}
version: {version}
title: "{title}"
note_date: {date}
author: {author}
text_sha256: {text_sha256}
---

# {title}

## Method (problem / gap / mechanism / evidence)

## Results and how strong they are

## Weaknesses and evaluation caveats

## Relation to OpenAlice (match / mismatch / transferable)

## Candidate follow-ups (not started)
"""


def cmd_note(args) -> int:
    root = resolve_root(args.root)
    base, _ = parse_arxiv_id(args.id)
    pdir = root / 'papers' / 'arxiv' / id_dirname(base)
    metas = sorted(pdir.glob('v*/meta.json'), key=lambda p: int(p.parent.name[1:]))
    if not metas:
        print(f'{base} is not in the library; fetch it first', file=sys.stderr)
        return 2
    meta = json.loads(metas[-1].read_text())
    slug = re.sub(r'[^a-z0-9-]+', '-', args.slug.lower()).strip('-')
    path = pdir / 'notes' / f'{datetime.now():%Y%m%d}-{slug}.md'
    path.parent.mkdir(exist_ok=True)
    with path.open('x') as f:  # never overwrite an existing note
        f.write(NOTE_TEMPLATE.format(date=f'{datetime.now():%Y-%m-%d}', author=args.author,
                                     title=meta['title'].replace('"', "'"), **{
                                         k: meta[k] for k in ('arxiv_id', 'version', 'text_sha256')}))
    print(path)
    return 0


def cmd_list(args) -> int:
    root = resolve_root(args.root)
    for m in iter_meta(root):
        notes = len(list((root / 'papers' / 'arxiv' / id_dirname(m['arxiv_id']) / 'notes').glob('*.md')))
        print(f"{m['arxiv_id']}{m['version']}  {m['published'][:10]}  notes={notes}  {m['title']}")
    return 0


def cmd_show(args) -> int:
    root = resolve_root(args.root)
    base, ver = parse_arxiv_id(args.id)
    pdir = root / 'papers' / 'arxiv' / id_dirname(base)
    metas = sorted(pdir.glob(f'{ver or "v*"}/meta.json'), key=lambda p: int(p.parent.name[1:]))
    if not metas:
        print(f'{base} is not in the library', file=sys.stderr)
        return 2
    meta = json.loads(metas[-1].read_text())
    print(json.dumps(meta, indent=1, ensure_ascii=False))
    print(f'dir:   {metas[-1].parent}')
    for n in sorted((pdir / 'notes').glob('*.md')):
        print(f'note:  {n}')
    return 0


VAULT_FIELDS = ('title', 'challenge', 'problem_definition', 'intuition', 'solution')
VAULT_FTS_CANDIDATES = (
    os.environ.get('OPENALICE_VAULT_FTS', ''),
    '/mnt/samsung_ssd/openalice-data/ideascientist/data/vault_fts.db',   # local copy (fast)
    str(DEFAULT_ROOT / 'external' / 'svalbard-idea-vault' / 'vault_fts.db'),  # QNAP archive
)
STOP = set('the and for with from that this into over under using use based via are its their our new '
           'method methods approach model models problem problems data paper'.split())


def vault_fts_path() -> Path | None:
    for c in VAULT_FTS_CANDIDATES:
        if c and Path(c).exists():
            return Path(c)
    return None


def build_vault_match(text: str, fields: list[str], raw: bool) -> str:
    if raw:
        q = text
    else:
        words = [w for w in re.findall(r'[A-Za-z][A-Za-z0-9\-]+', text.lower()) if len(w) > 2 and w not in STOP]
        if not words:
            raise ValueError('query has no searchable terms')
        q = ' OR '.join('"' + w.replace('"', '') + '"' for w in dict.fromkeys(words))
    return '{' + ' '.join(fields) + '} : (' + q + ')' if fields else q


def cmd_vault_search(args) -> int:
    fts = vault_fts_path()
    if fts is None:
        print('vault FTS index not found; build it with scripts/svalbard_vault_fts.py', file=sys.stderr)
        return EXIT_UNAVAILABLE
    fields = args.field or ['challenge']
    bad = [f for f in fields if f not in VAULT_FIELDS]
    if bad:
        print(f'unknown field(s) {bad}; valid: {VAULT_FIELDS}', file=sys.stderr)
        return 2
    match = build_vault_match(args.query, fields, args.raw)
    where, params = ['vault_fts MATCH ?'], [match]
    if args.date_from:
        where.append('m.date >= ?'); params.append(args.date_from)
    if args.date_to:
        where.append('m.date <= ?'); params.append(args.date_to)
    for c in args.exclude_cat or []:
        where.append("(' ' || m.categories || ' ') NOT LIKE ?"); params.append(f'% {c}%')
    if args.cat:
        where.append('(' + ' OR '.join("(' ' || m.categories || ' ') LIKE ?" for _ in args.cat) + ')')
        params += [f'% {c}%' for c in args.cat]
    sql = ('SELECT m.arxiv_id, m.date, m.primary_cat, m.title, m.intuition_head, bm25(vault_fts) AS s '
           'FROM vault_fts JOIN vault_meta m ON m.rowid = vault_fts.rowid WHERE ' + ' AND '.join(where) +
           ' ORDER BY s LIMIT ?')
    con = sqlite3_ro(fts)
    rows = con.execute(sql, params + [args.k]).fetchall()
    held = held_ids(resolve_root(args.root)) if not args.no_library_check else set()
    if args.json:
        for a, d, c, t, i, s in rows:
            print(json.dumps({'arxiv_id': a, 'date': d, 'primary_cat': c, 'title': t, 'intuition': i,
                              'bm25': round(s, 3), 'in_library': a in held}, ensure_ascii=False))
        return 0
    print(f'# {fts.name}  fields={fields}  {len(rows)} results')
    for a, d, c, t, i, s in rows:
        print(f"{'*' if a in held else ' '} {a}  {d}  [{c}]  {' '.join((t or '').split())}")
        if not args.brief and i:
            print(f"      {' '.join(i.split())[:args.width]}")
    return 0


def sqlite3_ro(path: Path):
    import sqlite3
    return sqlite3.connect(f'file:{path}?mode=ro&immutable=1', uri=True)


def cmd_reindex(args) -> int:
    print(f'index: {reindex(resolve_root(args.root))} paper versions')
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', help='library root (env OPENALICE_LITERATURE_ROOT)')
    sub = ap.add_subparsers(dest='cmd', required=True)

    s = sub.add_parser('search', help='arXiv API search, optionally bounded by submission date')
    s.add_argument('terms')
    s.add_argument('--cat', help='arXiv category, e.g. q-fin.ST, cs.LG')
    s.add_argument('--from', dest='date_from', help='YYYY-MM-DD inclusive')
    s.add_argument('--to', dest='date_to', help='YYYY-MM-DD inclusive (literature cutoff)')
    s.add_argument('--max', type=int, default=20)
    s.add_argument('--sort', default='relevance', choices=['relevance', 'submittedDate', 'lastUpdatedDate'])
    s.add_argument('--json', action='store_true')
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser('fetch', help='download PDF + metadata + text into the library')
    s.add_argument('ids', nargs='+')
    s.set_defaults(fn=cmd_fetch)

    s = sub.add_parser('graph', help='Semantic Scholar references or citations')
    s.add_argument('id')
    s.add_argument('--direction', default='references', choices=['references', 'citations'])
    s.add_argument('--max', type=int, default=500)
    s.add_argument('--save', action='store_true')
    s.set_defaults(fn=cmd_graph)

    s = sub.add_parser('note', help='create a new dated study-note template')
    s.add_argument('id')
    s.add_argument('--slug', required=True)
    s.add_argument('--author', default='agent')
    s.set_defaults(fn=cmd_note)

    s = sub.add_parser('vault-search', help='search the 2.67M-paper Svalbard Idea Vault by field (cross-domain)')
    s.add_argument('query', help='plain text (terms OR-ed, BM25 ranked) or FTS5 syntax with --raw')
    s.add_argument('--field', action='append', choices=VAULT_FIELDS,
                   help='column(s) to search; default challenge (who fought the same difficulty)')
    s.add_argument('--cat', action='append', help='keep only these arXiv category prefixes (e.g. q-bio)')
    s.add_argument('--exclude-cat', action='append', help='drop these category prefixes (force cross-domain)')
    s.add_argument('--from', dest='date_from', help='YYYY-MM-DD inclusive')
    s.add_argument('--to', dest='date_to', help='YYYY-MM-DD inclusive (literature cutoff)')
    s.add_argument('--k', type=int, default=20)
    s.add_argument('--raw', action='store_true')
    s.add_argument('--brief', action='store_true', help='titles only')
    s.add_argument('--width', type=int, default=220)
    s.add_argument('--json', action='store_true')
    s.add_argument('--no-library-check', action='store_true')
    s.set_defaults(fn=cmd_vault_search)

    for name, fn in (('list', cmd_list), ('reindex', cmd_reindex)):
        sub.add_parser(name).set_defaults(fn=fn)
    s = sub.add_parser('show')
    s.add_argument('id')
    s.set_defaults(fn=cmd_show)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == '__main__':
    sys.exit(main())
