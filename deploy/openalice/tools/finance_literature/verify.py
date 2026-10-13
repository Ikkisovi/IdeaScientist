#!/usr/bin/env python3
"""Verify every collected source and the exact QNAP/SSD publication readback."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import resource
import sqlite3
import time


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1<<20),b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('collection',type=Path)
    parser.add_argument('local',type=Path)
    args=parser.parse_args()
    started=time.monotonic()
    manifest=json.loads((args.collection/'manifest.json').read_text())
    assert sha(args.collection/'finance.db')==manifest['finance_db_sha256']==sha(args.local/'finance.db')
    assert sha(args.collection/'catalog.json')==manifest['catalog_sha256']
    records=json.loads((args.collection/'records.json').read_text())
    paths={}
    for record in records:
        root=Path(record['path'])
        assert json.loads((root/'meta.json').read_text())==record
        for name,key in [('paper.pdf','pdf_sha256'),('fulltext.txt','text_sha256'),
                         ('fulltext.layout.txt','layout_sha256'),('landing.html','landing_sha256')]:
            if record.get(key):
                assert sha(root/name)==record[key],str(root/name)
                paths[str(root/name)]=(root/name).stat().st_size
    with sqlite3.connect(f'file:{args.local}/finance.db?mode=ro&immutable=1',uri=True) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        for pid,body,metadata in db.execute('SELECT id,full_text,meta_json FROM papers'):
            meta=json.loads(metadata)
            if body:
                assert hashlib.sha256(body.encode()).hexdigest()==meta['text_sha256']
        assert db.execute('SELECT count(*) FROM papers').fetchone()[0]==manifest['unique_papers']
        assert db.execute('SELECT count(*) FROM papers_fts').fetchone()[0]==manifest['fulltext_papers']
    sample=[Path(p) for p in paths if p.endswith('/fulltext.txt')][:12]
    benchmark=[]
    for workers in (1,3):
        t=time.monotonic()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            hashes=list(pool.map(sha,sample))
        wall=time.monotonic()-t
        benchmark.append({'workers':workers,'files':len(sample),'bytes':sum(p.stat().st_size for p in sample),
                          'wall_seconds':wall,'files_per_second':len(sample)/wall,
                          'hashes':hashes,'cache_state':'post-verification warm cache'})
    assert benchmark[0]['hashes']==benchmark[1]['hashes']
    result={'status':'passed','source_files_verified':len(paths),'source_bytes_verified':sum(paths.values()),
        'qnap_local_exact_readback':True,'sqlite_integrity':'ok','database_bodies_match_source_hashes':True,
        'papers':manifest['unique_papers'],'fulltext_papers':manifest['fulltext_papers'],
        'metadata_only_papers':manifest['metadata_only_papers'],'wall_seconds':time.monotonic()-started,
        'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'read_benchmark':benchmark,'benchmark_phase':'post-collection; not a pre-launch measurement',
        'verifier_sha256':sha(__file__)}
    for root in (args.collection,args.local):
        with (root/'verification.json').open('x') as stream:
            json.dump(result,stream,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='read_benchmark'},indent=2))


if __name__=='__main__':
    main()
