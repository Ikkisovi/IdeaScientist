#!/usr/bin/env python3
"""Index paper-linked GitHub repositories without downloading or executing code."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import resource
import shutil
import sqlite3
import subprocess
import time
import urllib.parse

ROOT = Path('/mnt/qnap-workstation/literature-library')
RUNTIME = Path('/mnt/samsung_ssd/openalice-data/ideascientist')
OPEN_LICENSES = {'MIT', 'Apache-2.0', 'BSD-2-Clause', 'BSD-3-Clause', 'ISC', 'Unlicense',
    'CC0-1.0', 'MPL-2.0', 'EPL-1.0', 'EPL-2.0', 'BSL-1.0', 'Zlib', '0BSD'}
DEPENDENCIES = {'pytorch/pytorch', 'numpy/numpy', 'scikit-learn/scikit-learn',
    'pandas-dev/pandas', 'tensorflow/tensorflow', 'huggingface/transformers'}
RESERVED = {'topics', 'orgs', 'users', 'settings', 'search', 'features', 'login',
    'signup', 'site', 'marketplace', 'sponsors', 'collections', 'about'}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def save(path, value):
    with Path(path).open('x') as f:
        json.dump(value, f, indent=2, ensure_ascii=False)


def connect(path):
    return sqlite3.connect(f'file:{path}?mode=ro&immutable=1', uri=True)


def links(text):
    # Preserve original contexts; repair only line wraps inside a URL.
    repaired = re.sub(r'(github\.com/[^\s/]+/)\s*\n\s*', r'\1', text, flags=re.I)
    pattern = r'(?:https?://)?(?:www\.)?github\.com/([\w.-]+)/([\w.-]+)'
    for m in re.finditer(pattern, repaired, re.I):
        owner, repo = m[1], m[2].rstrip('.,;:')
        if owner.lower() in RESERVED or not repo or repo == 'github.io':
            continue
        if repo.endswith('.git'):
            repo = repo[:-4]
        name = (owner + '/' + repo).lower()
        context = repaired[max(0, m.start() - 220):m.end() + 220]
        relation = 'mentioned_repository'
        if name in DEPENDENCIES:
            relation = 'common_dependency'
        elif re.search(r'our (?:code|implementation)|(?:code|implementation|source).{0,65}'
                       r'(?:available|released|github)|open.source', context, re.I | re.S):
            relation = 'paper_code_claim'
        yield name, context, relation


def github(endpoint):
    result = subprocess.run(['gh', 'api', endpoint], capture_output=True, text=True, timeout=40)
    if result.returncode:
        raise RuntimeError(result.stderr[-600:])
    return json.loads(result.stdout)


def verify_repo(name, out):
    dest = out / 'repositories' / name.replace('/', '__')
    dest.mkdir(parents=True)
    result = {'repo': name, 'url': 'https://github.com/' + name, 'state': 'unverified',
              'checked_at': datetime.now(timezone.utc).isoformat(), 'code_executed': False}
    try:
        metadata = github('repos/' + name)
        if metadata.get('private') or metadata.get('visibility') not in (None,'public'):
            raise ValueError('Private repository is outside public literature scope')
        save(dest / 'github.json', metadata)
        license_id = (metadata.get('license') or {}).get('spdx_id') or ''
        branch = urllib.parse.quote(metadata['default_branch'], safe='')
        revision = github('repos/' + name + '/commits/' + branch)
        save(dest / 'revision.json', revision)
        commit = revision['sha']
        opened = license_id in OPEN_LICENSES or bool(re.fullmatch(r'(?:A?GPL|LGPL)-[123]\.0(?:-only|-or-later)?', license_id))
        result.update(state='public_verified', canonical_repo=metadata['full_name'],
            description=metadata.get('description') or '', license_spdx=license_id,
            open_source_license_detected=opened, archived=metadata['archived'],
            default_branch=metadata['default_branch'], revision=commit,
            metadata_path=str(dest / 'github.json'), metadata_sha256=sha(dest / 'github.json'),
            revision_path=str(dest / 'revision.json'), revision_sha256=sha(dest / 'revision.json'))
        try:
            readme = github('repos/' + name + '/readme?ref=' + commit)
            text = base64.b64decode(readme['content']).decode('utf-8', errors='replace')
            if len(text.encode()) > 1 << 20:
                raise ValueError('README exceeds 1 MiB')
            (dest / 'README.md').write_text(text)
            result.update(readme_path=str(dest / 'README.md'), readme_sha256=sha(dest / 'README.md'), readme=text)
        except Exception as exc:
            result['readme_error'] = str(exc)
    except Exception as exc:
        result.update(state='unavailable', error=str(exc))
    save(dest / 'result.json', {k:v for k,v in result.items() if k != 'readme'})
    return result


def build(args):
    if not ROOT.is_dir() or not Path('/mnt/qnap-workstation').is_mount():
        raise RuntimeError('QNAP mount required')
    local = RUNTIME / 'data/paper-code' / args.collection
    out = ROOT / 'external/paper-code' / args.collection
    local.mkdir(parents=True, exist_ok=False)
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    db = sqlite3.connect(local / 'code.db')
    db.executescript('''CREATE TABLE papers(paper_key TEXT PRIMARY KEY,paper_id INTEGER,
        arxiv_id TEXT,title TEXT,paper_url TEXT,corpus TEXT);
        CREATE TABLE links(paper_key TEXT,repo TEXT,source TEXT,source_sha256 TEXT,
        location TEXT,context TEXT,relation TEXT, UNIQUE(paper_key,repo,source,context));
        CREATE TABLE repos(repo TEXT PRIMARY KEY,json TEXT);
        CREATE VIRTUAL TABLE code_fts USING fts5(paper_key UNINDEXED,repo UNINDEXED,title,context,readme);''')
    counts = {}

    def ingest(key, pid, arxiv, title, url, corpus, text, source, digest, location):
        found = list(links(text))
        if not found:
            return
        db.execute('INSERT OR IGNORE INTO papers VALUES(?,?,?,?,?,?)', (key,pid,arxiv,title,url,corpus))
        for repo, context, relation in found:
            db.execute('INSERT OR IGNORE INTO links VALUES(?,?,?,?,?,?,?)',
                       (key,repo,source,digest,location,context,relation))

    finance = connect(args.finance_db)
    aliases = {}
    for pid,t,m in finance.execute('SELECT id,title,meta_json FROM papers'):
        record = json.loads(m)
        for a in record['aliases']:
            aliases[a['path']] = (pid,t,record['url'])
    paths = sorted((ROOT / 'papers').glob('**/fulltext.txt'))
    pdfs = set()
    for path in paths:
        meta_path = path.with_name('meta.json')
        if not meta_path.exists():
            continue
        m = json.loads(meta_path.read_text())
        match = aliases.get(str(path.parent))
        pid,t,url = match if match else (None,m.get('title',''),m.get('abs_url',m.get('url','')))
        arxiv = m.get('arxiv_id','')
        key = 'paper:' + str(pid) if pid is not None else 'arxiv:' + arxiv if arxiv else 'path:' + str(path.parent)
        body = path.read_text()
        digest = sha(path)
        ingest(key,pid,arxiv,t,url,'finance' if match else 'library',body,str(path),digest,'fulltext')
        ingest(key,pid,arxiv,t,url,'finance' if match else 'library',meta_path.read_text(),str(meta_path),sha(meta_path),'metadata')
        pdf = path.with_name('paper.pdf')
        pdf_hash = m.get('pdf_sha256')
        if pdf.exists() and pdf_hash not in pdfs:
            pdfs.add(pdf_hash)
            converted = subprocess.run(['pdftohtml','-xml','-stdout','-i',str(pdf)], capture_output=True,
                                       text=True, timeout=30)
            if converted.returncode:
                raise RuntimeError('PDF hyperlink extraction failed: ' + str(pdf))
            ingest(key,pid,arxiv,t,url,'finance' if match else 'library',converted.stdout,str(pdf),sha(pdf),'pdf_hyperlink_or_text')
    counts['stored_fulltext_files_scanned'] = len(paths)
    counts['unique_pdfs_scanned'] = len(pdfs)
    metadata_paths=sorted((ROOT/'papers').glob('**/meta.json'))
    for meta_path in metadata_paths:
        if meta_path.with_name('fulltext.txt').exists():continue
        m=json.loads(meta_path.read_text());match=aliases.get(str(meta_path.parent))
        pid,t,url=match if match else (None,m.get('title',''),m.get('abs_url',m.get('url','')))
        arxiv=m.get('arxiv_id','')
        key='paper:'+str(pid) if pid is not None else 'arxiv:'+arxiv if arxiv else 'path:'+str(meta_path.parent)
        ingest(key,pid,arxiv,t,url,'finance' if match else 'library',meta_path.read_text(),
               str(meta_path),sha(meta_path),'metadata')
    counts['stored_metadata_snapshots_scanned']=len(metadata_paths)
    vault = connect(RUNTIME / 'data/idea_vault.db')
    for table, column, join, fields in [
        ('papers','abstract','', 'p.abstract'),
        ('metadata_results_masked','fields_json','JOIN metadata_results_masked m ON m.paper_id=p.id','m.fields_json')]:
        counts[table + '_rows_scanned'] = vault.execute('SELECT count(*) FROM ' + table).fetchone()[0]
        sql = f'SELECT p.id,p.title,p.arxiv_id,p.url,{fields} FROM papers p {join} WHERE instr(lower({fields}),\'github.com/\')>0'
        matched = 0
        for pid,t,a,url,body in vault.execute(sql):
            ingest('paper:'+str(pid),pid,a or '',t,url,'svalbard',body,
                str(RUNTIME/'data/idea_vault.db'),'record-sha256:'+hashlib.sha256(body.encode()).hexdigest(),table)
            matched += 1
        counts[table + '_matching_rows'] = matched
        db.commit()
        print(table, matched, 'GitHub-bearing records', flush=True)
    # Bind library arXiv keys to vault IDs when a matching vault record exists.
    unbound=db.execute("SELECT paper_key,arxiv_id FROM papers WHERE paper_id IS NULL AND arxiv_id!=''").fetchall()
    wanted=list({a for _,a in unbound})
    if wanted:
        identifiers=dict(vault.execute('SELECT arxiv_id,id FROM papers WHERE arxiv_id IN (' +
            ','.join('?' for _ in wanted) + ')',wanted))
        for key,a in unbound:
            if a in identifiers:
                db.execute('UPDATE papers SET paper_id=? WHERE paper_key=?',(identifiers[a],key))
    vault.close()
    finance.close()
    db.commit()
    save(local/'scan.json', {'counts':counts,'wall_seconds':time.monotonic()-started,
        'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'source_vault_read_only':True,'vault_fulltexts_available':0})
    candidates = db.execute('''SELECT l.repo, max(p.corpus!='svalbard') AS held,
        max(lower(p.title) LIKE '%factor%' OR lower(p.title) LIKE '%financ%' OR
            lower(p.title) LIKE '%portfolio%' OR lower(p.title) LIKE '%trading%' OR
            lower(p.title) LIKE '%asset pricing%' OR lower(p.title) LIKE '%time series%') AS relevant,
        max(l.relation='paper_code_claim') AS claimed FROM links l JOIN papers p USING(paper_key)
        GROUP BY l.repo ORDER BY held DESC,relevant DESC,claimed DESC,l.repo''').fetchall()
    rate = github('rate_limit')['resources']['core']
    budget = min(args.verify_max, max(0,(rate['remaining']-100)//3))
    save(local/'network-budget.json',{'initial_core_rate':rate,'repository_cap':budget,
        'policy':'held papers first, then financial/time-series titles, then code-availability claims',
        'worker_count':3,'request_timeout_seconds':40})
    print('Repository candidates',len(candidates),'verification cap',budget,flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(lambda row:verify_repo(row[0],local),candidates[:budget]):
            db.execute('INSERT INTO repos VALUES(?,?)',(result['repo'],json.dumps(result)))
    for row in candidates[budget:]:
        db.execute('INSERT INTO repos VALUES(?,?)',(row[0],json.dumps({'repo':row[0],
            'state':'unverified','url':'https://github.com/'+row[0],'reason':'bounded verification budget'})))
    for key,repo,title,context in db.execute('''SELECT l.paper_key,l.repo,p.title,group_concat(l.context,'\n')
        FROM links l JOIN papers p USING(paper_key) GROUP BY l.paper_key,l.repo''').fetchall():
        record=json.loads(db.execute('SELECT json FROM repos WHERE repo=?',(repo,)).fetchone()[0])
        db.execute('INSERT INTO code_fts VALUES(?,?,?,?,?)',(key,repo,title,context,record.get('readme','')))
    db.commit()
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    repo_rows=[json.loads(x[0]) for x in db.execute('SELECT json FROM repos')]
    manifest={'collection':args.collection,'schema':'paper-code-index/1','counts':counts,
        'linked_papers':db.execute('SELECT count(*) FROM papers').fetchone()[0],
        'unique_repositories':len(repo_rows),'repositories_checked':budget,
        'public_verified':sum(x['state']=='public_verified' for x in repo_rows),
        'open_source_license_detected':sum(bool(x.get('open_source_license_detected')) for x in repo_rows),
        'readmes_captured':sum(bool(x.get('readme')) for x in repo_rows),
        'code_db_sha256':'','finance_db_sha256':sha(args.finance_db),
        'source_vault':str(RUNTIME/'data/idea_vault.db'),
        'builder_sha256':sha(__file__),'wall_seconds':time.monotonic()-started,
        'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'association_is_not_authorship_proof':True,'code_executed':False}
    db.close()
    manifest['code_db_sha256']=sha(local/'code.db')
    save(local/'manifest.json',manifest)
    (local/'builder.py').write_bytes(Path(__file__).read_bytes())
    for p in local.iterdir():
        target=out/p.name
        if p.is_dir(): shutil.copytree(p,target)
        else: shutil.copyfile(p,target)
    verified=0
    for p in local.rglob('*'):
        if p.is_file():
            assert sha(p)==sha(out/p.relative_to(local));verified+=1
    save(out/'verification.json',{'status':'passed','files_exact_readback':verified,
        'database_integrity':'ok','code_db_sha256':manifest['code_db_sha256']})
    print(json.dumps(manifest),flush=True)


def search(path, query, k=8, open_only=False):
    match=' OR '.join('"'+x+'"' for x in re.findall(r'[a-zA-Z0-9]+',query)[:32] if len(x)>2)
    if not match: return []
    with connect(path) as db:
        rows=db.execute('''SELECT f.paper_key,f.repo,p.title,p.paper_id,p.arxiv_id,r.json,bm25(code_fts)
            FROM code_fts f JOIN papers p ON p.paper_key=f.paper_key JOIN repos r ON r.repo=f.repo
            WHERE code_fts MATCH ? ''' +
            ("AND json_extract(r.json,'$.open_source_license_detected')=1 " if open_only else '')+
            'ORDER BY bm25(code_fts) LIMIT ?',(match,k)).fetchall()
        output=[]
        for key,repo,title,pid,arxiv,record,score in rows:
            record=json.loads(record)
            if open_only and not record.get('open_source_license_detected'): continue
            record.pop('readme',None)
            evidence=[dict(zip(('source','sha256','location','context','relation'),r)) for r in db.execute(
                'SELECT source,source_sha256,location,context,relation FROM links WHERE paper_key=? AND repo=? LIMIT 4',(key,repo))]
            output.append({'paper_id':pid,'arxiv_id':arxiv,'title':title,'repository':record,'evidence':evidence})
            if len(output)>=k:break
        return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('build');p.add_argument('--finance-db',type=Path,required=True)
    p.add_argument('--collection',required=True);p.add_argument('--verify-max',type=int,default=800)
    p=sub.add_parser('search');p.add_argument('db',type=Path);p.add_argument('query')
    p.add_argument('--k',type=int,default=8);p.add_argument('--open-only',action='store_true')
    args=parser.parse_args()
    if args.command=='build':build(args)
    else:print(json.dumps(search(args.db,args.query,args.k,args.open_only),indent=2))


if __name__=='__main__':main()
