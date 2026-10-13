"""Read the same pinned paper/code indexes used by current-literature ideation."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

DEFAULT_PROFILE=Path('/mnt/samsung_ssd/openalice-data/ideascientist/data/paper-code/'
                     '20261013-paper-code-v1/retrieval-profile.json')


def retrieve(proposal, profile=DEFAULT_PROFILE):
    profile=Path(profile)
    terms=' '.join(str(proposal['proposal'].get(k,'')) for k in ('title','core_problem','key_terms'))
    # Citation IDs are resolved separately; concise method queries avoid generic prose.
    query=' '.join(re.findall(r'[A-Za-z][A-Za-z0-9_-]{2,}',terms)[:24])
    paper_ids=list(dict.fromkeys(re.findall(r'\[(\d+)\]',json.dumps(proposal['proposal']))))[:16]
    command=['/mnt/samsung_ssd/openalice-data/ideascientist/venv/bin/python',
        str(Path(__file__).resolve().parents[1]/'finance_literature/retrieve.py'),
        str(profile),query,'--k','8','--paper-ids',*paper_ids]
    result=subprocess.run(command,capture_output=True,text=True,timeout=60)
    if result.returncode:raise RuntimeError('Pinned literature retrieval failed: '+result.stderr[-1000:])
    data=json.loads(result.stdout)
    if hashlib.sha256(profile.read_bytes()).hexdigest()!=data['profile_sha256']:
        raise ValueError('Retrieval profile changed')
    return data
