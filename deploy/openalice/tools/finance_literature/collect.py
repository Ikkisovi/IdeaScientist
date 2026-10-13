#!/usr/bin/env python3
"""Collect a versioned, source-backed finance corpus on the mounted QNAP share."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import time
import unicodedata
import urllib.parse
import urllib.request

from bs4 import BeautifulSoup

ROOT = Path('/mnt/qnap-workstation/literature-library')
BASE = Path('/mnt/samsung_ssd/openalice-data/ideascientist/data/idea_vault.db')
UA = 'OpenAlice-literature-library/1.0 (private academic research archive)'
TOPICS = ['machine learning', 'asset pricing', 'factor model', 'nowcast', 'forecast',
          'financial market', 'risk premium', 'portfolio', 'yield', 'exchange rate',
          'stock', 'bond', 'quantile', 'volatility', 'liquidity', 'monetary policy']


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def put(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def normalized(title):
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', clean_title(title)).lower())


def clean_title(title):
    if 'â' in title or 'Ã' in title:
        for encoding in ('cp1252', 'latin1'):
            try:
                title = title.encode(encoding).decode('utf-8')
                break
            except (UnicodeError, ValueError):
                pass
    return BeautifulSoup(title, 'html.parser').get_text(' ', strip=True)


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=25) as response:
        data = response.read(32 * 1024 * 1024 + 1)
        if len(data) > 32 * 1024 * 1024:
            raise ValueError('Document exceeds 32 MiB')
        return data, response.geturl(), response.headers.get('Content-Type', '')


def soup(data):
    try:
        data = data.decode('utf-8')
    except (UnicodeError, AttributeError):
        pass
    return BeautifulSoup(data, 'html.parser')


def discover(out, seeds):
    records = list(seeds)
    for year in (2026, 2025, 2024):
        url = f'https://www.federalreserve.gov/econres/feds/{year}.htm'
        try:
            data, final, _ = fetch(url)
            (out / f'feds-{year}.html').write_bytes(data)
            rows = []
            for node in soup(data).select('div.heading.feds-note'):
                head = node.select_one('h5 a')
                if not head:
                    continue
                text = node.get_text(' ', strip=True)
                if sum(term in text.lower() for term in TOPICS) < 2:
                    continue
                links = [urllib.parse.urljoin(final, a['href']) for a in node.select('a[href]')
                         if '.pdf' in a['href'].lower()]
                abstract = node.select_one('[id^=abstract-more]')
                date = node.find('time')
                rows.append({'source': 'feds', 'key': 'feds-' + node.get('id', ''),
                    'url': urllib.parse.urljoin(final, head['href']), 'title': head.get_text(' ', strip=True),
                    'authors': node.select_one('.authors').get_text(' ', strip=True) if node.select_one('.authors') else '',
                    'published_date': date.get_text(' ', strip=True) if date else '',
                    'abstract': abstract.get_text(' ', strip=True) if abstract else '',
                    'pdf_urls': links, 'discovery_url': url})
            records.extend(rows[:16])
        except Exception as exc:
            put(out / f'feds-{year}-error.json', {'url': url, 'error': str(exc)})
    url = 'https://dachxiu.chicagobooth.edu/'
    try:
        data, final, _ = fetch(url)
        (out / 'dacheng-xiu.html').write_bytes(data)
        seen = set()
        for a in soup(data).select('a[href]'):
            href = a['href']
            if not href.lower().endswith('.pdf') or any(word in href.lower() for word in
                    ('supp', 'slide', 'cv', 'rejoinder', 'sofie', 'comment', 'prad')):
                continue
            container = a.find_parent(class_='list-group-item') or a.parent
            text = container.get_text(' ', strip=True)
            title_match = re.search(r'["“]([^"”]+)["”]', text)
            if not title_match or sum(term in text.lower() for term in TOPICS) < 1:
                continue
            title = title_match[1]
            if normalized(title) in seen:
                continue
            seen.add(normalized(title))
            records.append({'source': 'author', 'key': 'xiu-' + Path(href).stem,
                'url': final, 'title': title, 'pdf_urls': [urllib.parse.urljoin(final, href)],
                'discovery_url': url, 'author_page_context': text[:3000]})
            if len(seen) >= 20:
                break
    except Exception as exc:
        put(out / 'author-discovery-error.json', {'error': str(exc)})
    unique = {}
    for row in records:
        unique.setdefault(row['key'], row)
    put(out / 'discovered.json', list(unique.values()))
    return list(unique.values())


def collect_one(seed, collection):
    started = time.monotonic()
    record = dict(seed)
    capture = datetime.now(timezone.utc).isoformat(timespec='seconds')
    dest = ROOT / 'papers/finance' / seed['source'] / seed['key'] / collection
    dest.mkdir(parents=True, exist_ok=False)
    record.update(captured_at=capture, availability_date=capture[:10],
                  availability_grade='capture-date upper bound; historical version availability not certified',
                  status='metadata_only', errors=[], path=str(dest))
    pdf_urls = list(record.get('pdf_urls', []))
    if not record['url'].lower().split('?')[0].endswith('.pdf'):
        try:
            data, final, content_type = fetch(record['url'])
            if data.startswith(b'%PDF'):
                pdf_urls.insert(0, final)
            (dest / 'landing.html').write_bytes(data)
            record['landing_sha256'] = sha(dest / 'landing.html')
            record['landing_final_url'] = final
            parsed = soup(data)
            meta = {}
            for item in parsed.select('meta[name][content]'):
                meta.setdefault(item['name'].lower(), []).append(item['content'])
            title = meta.get('citation_title', meta.get('dc.title', []))
            if title:
                record['title'] = title[0]
            if meta.get('citation_author'):
                record['authors'] = '; '.join(meta['citation_author'])
            for name, target in [('citation_doi', 'doi'), ('citation_publication_date', 'published_date')]:
                if meta.get(name):
                    record[target] = meta[name][0]
            pdf_urls = meta.get('citation_pdf_url', []) + pdf_urls
            for a in parsed.select('a[href]'):
                href = a['href']
                if '.pdf' in href.lower() and re.search(r'pdf|full paper|download', a.get_text(), re.I):
                    pdf_urls.append(urllib.parse.urljoin(final, href))
            if not record.get('abstract'):
                abstract = parsed.select_one('.page-header__intro, .field--name-body, #abstract')
                if abstract:
                    record['abstract'] = abstract.get_text(' ', strip=True)[:12000]
                elif meta.get('description'):
                    record['abstract'] = meta['description'][0]
        except Exception as exc:
            record['errors'].append({'stage': 'landing', 'url': record['url'], 'error': str(exc)})
    else:
        pdf_urls.insert(0, record['url'])
    for url in dict.fromkeys(pdf_urls[:4]):
        try:
            data, final, content_type = fetch(url)
            if not data.startswith(b'%PDF'):
                raise ValueError('Response is not a PDF')
            with tempfile.TemporaryDirectory(prefix='openalice-finance-') as temp:
                pdf = Path(temp) / 'paper.pdf'
                text = Path(temp) / 'fulltext.txt'
                pdf.write_bytes(data)
                subprocess.run(['pdftotext', '-enc', 'UTF-8', str(pdf), str(text)], check=True,
                               timeout=40, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                body = text.read_text(errors='replace')
                if len(body) < 3000:
                    raise ValueError('Body text is missing or too short')
                words = set(re.findall(r'[a-z]{4,}', record['title'].lower()))
                head = set(re.findall(r'[a-z]{4,}', body[:5000].lower()))
                if words and len(words & head) / len(words) < .7:
                    raise ValueError('PDF first-page title does not match landing metadata')
                author_names = [normalized(a.strip().split()[-1]) for a in record.get('authors', '').split(';') if a.strip()]
                author_names = [a for a in author_names if len(a) > 2]
                head_text = normalized(body[:5000])
                author_matches = sum(a in head_text for a in author_names)
                if author_names and author_matches < min(2, len(author_names)):
                    raise ValueError('PDF first-page author surnames do not match discovery metadata')
                record['author_surname_check'] = {'expected':len(author_names),'matched':author_matches,
                    'scope':'first 5000 characters; not complete author-name certification'}
                review = seed.get('bibliography_review')
                if review and sha(pdf) != review['pdf_sha256']:
                    raise ValueError('PDF differs from manually reviewed bibliography evidence')
                (dest / 'paper.pdf').write_bytes(data)
                (dest / 'fulltext.txt').write_text(body)
                subprocess.run(['pdftotext', '-layout', '-enc', 'UTF-8', str(pdf), str(dest / 'fulltext.layout.txt')],
                               check=True, timeout=40, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            record.update(status='fulltext', pdf_url=final, pdf_sha256=sha(dest / 'paper.pdf'),
                          text_sha256=sha(dest / 'fulltext.txt'), text_chars=len(body),
                          layout_sha256=sha(dest / 'fulltext.layout.txt'))
            if review:
                record['title'] = seed['title']
                record['authors'] = seed['authors']
                record['bibliography_review_verified'] = True
            break
        except Exception as exc:
            record['errors'].append({'stage': 'pdf', 'url': url, 'error': str(exc)})
    record['wall_seconds'] = time.monotonic() - started
    put(dest / 'meta.json', record)
    print(f"{record['status']:13} {seed['key']} {record['title'][:100]}", flush=True)
    return record


def publish(out, records):
    grouped = {}
    for record in records:
        key = normalized(record['title'])
        if not key:
            continue
        grouped.setdefault(key, []).append(record)
    base = sqlite3.connect(f'file:{BASE}?mode=ro&immutable=1', uri=True)
    # CIFS does not provide reliable SQLite writer locking; publish a closed DB.
    scratch = Path('/mnt/samsung_ssd/openalice-data/finance-enrichment/builds') / out.name
    scratch.mkdir(parents=True, exist_ok=False)
    local_db = scratch / 'finance.db'
    db = sqlite3.connect(local_db)
    db.executescript('''CREATE TABLE papers(id INTEGER PRIMARY KEY,title TEXT,authors TEXT,date TEXT,
        availability_date TEXT,source TEXT,url TEXT,abstract TEXT,doi TEXT,full_text TEXT,meta_json TEXT);
        CREATE VIRTUAL TABLE papers_fts USING fts5(title,abstract,body);
        CREATE TABLE collection_meta(key TEXT PRIMARY KEY,value TEXT);''')
    rows = []
    for key, versions in grouped.items():
        best = max(versions, key=lambda r: (r['status'] == 'fulltext',
            bool(r.get('bibliography_review_verified')), bool(r.get('authors')), bool(r.get('abstract'))))
        body = (Path(best['path']) / 'fulltext.txt').read_text() if best['status'] == 'fulltext' else ''
        existing = base.execute('SELECT id FROM papers WHERE title=?', (best['title'],)).fetchone()
        pid = existing[0] if existing else 10_000_000_000 + int(hashlib.sha256(key.encode()).hexdigest()[:12], 16)
        best = dict(best)
        title = clean_title(best['title'])
        if title != best['title']:
            best['original_title'] = best['title']
            best['title'] = title
        if re.search(r'Paper statistics|job opening', best.get('authors', ''), re.I):
            best['invalid_original_authors'] = best['authors']
            best['authors'] = ''
        for field in ('authors', 'abstract', 'published_date', 'doi'):
            if not best.get(field):
                best[field] = next((r[field] for r in versions if r.get(field)
                                   and not (field == 'authors' and re.search(r'Paper statistics|job opening',r[field],re.I))), '')
        best['aliases'] = [{'source': r['source'], 'key': r['key'], 'url': r['url'], 'path': r['path']} for r in versions]
        best['base_paper_id'] = existing[0] if existing else None
        db.execute('INSERT INTO papers VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (pid, best['title'], best.get('authors', ''), best.get('published_date', ''),
             best['availability_date'], best['source'], best['url'], best.get('abstract', ''),
             best.get('doi', ''), body, json.dumps(best)))
        if body:
            db.execute('INSERT INTO papers_fts(rowid,title,abstract,body) VALUES(?,?,?,?)',
                       (pid, best['title'], best.get('abstract', ''), body))
        rows.append({'id': pid, 'title': best['title'], 'status': best['status'], 'source': best['source'],
                     'path': best['path'], 'aliases': best['aliases'], 'base_paper_id': best['base_paper_id']})
    db.execute('INSERT INTO collection_meta VALUES(?,?)', ('schema', 'openalice-finance-literature/1'))
    db.commit()
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise ValueError('Database integrity check failed')
    db.close()
    base.close()
    with local_db.open('rb') as source, (out / 'finance.db').open('xb') as target:
        import shutil
        shutil.copyfileobj(source, target)
        target.flush()
        os.fsync(target.fileno())
    if sha(local_db) != sha(out / 'finance.db'):
        raise ValueError('QNAP DB exact readback differs')
    put(out / 'catalog.json', rows)
    put(out / 'manifest.json', {'schema': 'openalice-finance-literature/1', 'collection': out.name,
        'source_records': len(records), 'unique_papers': len(rows),
        'fulltext_papers': sum(r['status'] == 'fulltext' for r in rows),
        'metadata_only_papers': sum(r['status'] != 'fulltext' for r in rows),
        'duplicates_merged': len(records) - len(rows), 'base_title_matches': sum(r['base_paper_id'] is not None for r in rows),
        'source_counts': {s: sum(r['source'] == s for r in records) for s in sorted({r['source'] for r in records})},
        'finance_db_sha256': sha(out / 'finance.db'), 'catalog_sha256': sha(out / 'catalog.json'),
        'collector_sha256': sha(__file__), 'base_vault': str(BASE), 'base_modified': False,
        'results_masked_records_generated': False, 'embedding_novelty_supported': False,
        'publication_date_is_not_version_availability': True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('seeds', type=Path)
    parser.add_argument('--collection', default=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    parser.add_argument('--no-discover', action='store_true')
    parser.add_argument('--prior-records', type=Path)
    args = parser.parse_args()
    os.listdir(ROOT)
    if not os.path.ismount('/mnt/qnap-workstation'):
        raise SystemExit('QNAP is not mounted; refusing local fallback')
    out = ROOT / 'external/finance-economics-quant' / args.collection
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    seeds = json.loads(args.seeds.read_text())
    put(out / 'seeds.json', seeds)
    (out / 'collector.py').write_bytes(Path(__file__).read_bytes())
    records = seeds if args.no_discover else discover(out, seeds)
    with ThreadPoolExecutor(max_workers=3) as pool:
        collected = list(pool.map(lambda r: collect_one(r, args.collection), records))
    if args.prior_records:
        prior = json.loads(args.prior_records.read_text())
        put(out / 'prior.json', {'path': str(args.prior_records), 'sha256': sha(args.prior_records), 'records': len(prior)})
        collected = prior + collected
    put(out / 'records.json', collected)
    publish(out, collected)
    put(out / 'runtime.json', {'wall_seconds': time.monotonic() - started, 'workers': 3,
                              'download_cap_bytes': 32 << 20, 'request_timeout_seconds': 25})
    print(out, flush=True)


if __name__ == '__main__':
    main()
