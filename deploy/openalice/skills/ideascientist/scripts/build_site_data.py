"""Collect IdeaScientist question/run/candidate/verdict data into one JSON for the viewer page.

  python3 -I build_site_data.py <out.json>
"""
import glob, json, os, re, sqlite3, sys, time
from ideascientist.evaluation.render import render_report
W = '/mnt/samsung_ssd/openalice-data/ideascientist'
DB = sqlite3.connect(f'file:{W}/data/idea_vault.db?mode=ro&immutable=1', uri=True)
CAP = 14000

def read(p, cap=CAP):
    try:
        s = open(p, encoding='utf-8', errors='replace').read()
    except OSError:
        return ''
    return s if len(s) <= cap else s[:cap] + f'\n\n… (truncated, {len(s):,} chars total)'

def sections(md, pat):
    out = {}
    parts = re.split(r'^(### .*)$', md, flags=re.M)
    for i in range(1, len(parts), 2):
        m = re.match(pat, parts[i])
        if m:
            out[m.group(1)] = (parts[i].lstrip('# ').strip(), parts[i + 1].strip())
    return out

def paper_title(pid):
    r = DB.execute('select title, date, arxiv_id from papers where id=?', (pid,)).fetchone()
    return {'title': r[0], 'date': (r[1] or '')[:10], 'arxiv': r[2]} if r else None

def running_ids():
    ids = set()
    for p in glob.glob('/proc/[0-9]*/cmdline'):
        try:
            a = open(p, 'rb').read().split(b'\0')
        except OSError:
            continue
        if any(x.endswith(b'run_ideation.py') for x in a) and b'--problem-id' in a:
            i = a.index(b'--problem-id'); m = a.index(b'--model') if b'--model' in a else -1
            ids.add((a[i + 1].decode(), a[m + 1].decode() if m >= 0 else ''))
    return ids

RUN = running_ids()
ARM_MODEL = {'gemini': 'gemini-3.8-flash-high', 'spark': 'muse-spark-1.3-contributor', 'glm': 'z-ai/glm-5.3-flash'}
papers = {}

def run_record(d, arm, qid):
    o = f'{d}/outputs'
    comp = json.load(open(f'{o}/completion.json')) if os.path.exists(f'{o}/completion.json') else None
    summ = json.load(open(f'{d}/logs/summary.json')) if os.path.exists(f'{d}/logs/summary.json') else {}
    ev = f'{d}/evaluation.gpt-6-astra/evaluation.json'
    score = json.load(open(ev))['summary'] if os.path.exists(ev) else None
    cands = sections(read(f'{o}/candidates.md', 10**7), r'### (C\d+)\b')
    verds = sections(read(f'{o}/scores.md', 10**7), r'### (C\d+) verdict')
    clist = []
    for cid, (title, body) in cands.items():
        v = verds.get(cid, ('', ''))[1]
        m = re.search(r'\*\*Verdict\*\*:\s*([a-z_]+)', v)
        refs = sorted({int(x) for x in re.findall(r'\[(\d{3,8})\]', body + v)})
        for r in refs:
            if r not in papers:
                t = paper_title(r)
                if t:
                    papers[r] = t
        obj = re.search(r'Strongest objection[^:]*:\*?\*?\s*(.+)', v)
        clist.append({'id': cid, 'title': re.sub(r'^C\d+\s*[—-]\s*', '', title), 'body': body[:6000],
                      'verdict': m.group(1) if m else ('pending' if not v else 'unparsed'), 'review': v[:6000],
                      'objection': obj.group(1).strip() if obj else '', 'refs': [r for r in refs if r in papers]})
    live = (qid, ARM_MODEL.get(arm, '')) in RUN
    report, thesis = read(f'{o}/report.md'), ''
    if os.path.exists(f'{o}/report.json'):
        try:
            rj = json.load(open(f'{o}/report.json'))
            report, thesis = render_report(rj)[:CAP * 2], rj.get('one_sentence_thesis', '') or rj.get('title', '')
        except Exception as e:  # off-schema report (e.g. GLM pid36)
            report = f'(report.json could not be rendered: {e})'
    if live:
        status = 'running'
    elif comp:
        status = comp['status']
    elif os.path.exists(f'{o}/report.json') or os.path.exists(f'{o}/report.md'):
        status = 'proposal'
    else:
        status = 'no_report'
    return {'arm': arm, 'dir': d.replace(W + '/', ''), 'status': status, 'reason': (comp or {}).get('reason', ''),
            'score': score, 'tokens': summ.get('total_tokens') or summ.get('tokens'), 'turns': summ.get('turns'),
            'gaps': read(f'{o}/gaps.md', 8000), 'report': report, 'thesis': thesis,
            'candidates': clist, 'mtime': max((os.path.getmtime(p) for p in glob.glob(f'{o}/*')), default=0)}

def latest(pattern):
    ds = sorted(x for x in glob.glob(pattern) if os.path.isdir(x))
    return ds[-1] if ds else None

groups = []
# LEA-91 open problems
qs = []
for f in sorted(glob.glob(f'{W}/lea91q/problems/*.txt')):
    qid = os.path.basename(f)[:-4]; txt = open(f).read()
    runs = []
    for arm in ('gemini', 'spark'):
        d = latest(f'{W}/lea91q/runs_{arm}/*_{qid}')
        if d:
            runs.append(run_record(d, arm, qid))
    qs.append({'id': qid, 'title': {'q1_postselection_fitness': 'Fitness that survives selection',
                                     'q2_slow_exposure_regime': 'Slow exposures and regime-shared loss',
                                     'q3_surrogate_reward_goodhart': 'Surrogate reward without Goodhart'}.get(qid, qid),
               'problem': txt, 'runs': runs})
groups.append({'id': 'lea91', 'title': 'LEA-91 factor search', 'subtitle': 'Open problems from P2–P4 (2026-10-12)', 'questions': qs})
# Pilot reproduction
sel = json.load(open(f'{W}/pilot10/problems/selection.json'))['selected']
ps = []
for s in sel:
    pid = s['paper_id']; qid = f'pid{pid}'
    runs = []
    for arm, sub in (('spark', 'runs_spark'), ('gemini', 'runs_gemini'), ('glm', 'runs'), ('human', 'human')):
        d = latest(f'{W}/pilot10/{sub}/*{qid}') if arm != 'human' else latest(f'{W}/pilot10/human/human_{qid}')
        if d:
            r = run_record(d, arm, qid)
            if arm == 'human':
                r['status'] = 'reference'
            runs.append(r)
    ps.append({'id': qid, 'title': s['title'], 'arxiv': s['arxiv_id'], 'problem': read(f'{W}/pilot10/problems/{qid}.txt'), 'runs': runs})
groups.append({'id': 'pilot', 'title': 'Reproduction pilot', 'subtitle': '10 held-out vault papers · astra-judged', 'questions': ps})

out = {'generated': time.strftime('%Y-%m-%d %H:%M %Z'), 'groups': groups,
       'papers': {str(k): v for k, v in papers.items()}}
json.dump(out, open(sys.argv[1], 'w'), ensure_ascii=False)
n = sum(len(q['runs']) for g in groups for q in g['questions'])
print(f'questions={sum(len(g["questions"]) for g in groups)} runs={n} papers={len(papers)} bytes={os.path.getsize(sys.argv[1]):,}')
for g in groups:
    for q in g['questions']:
        print(q['id'], [(r['arm'], r['status'], len(r['candidates'])) for r in q['runs']])
