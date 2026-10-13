"""Validate the shared retrieval profile before a new research process starts."""
import hashlib
import json
from pathlib import Path

DEFAULT_PROFILE=Path('/mnt/samsung_ssd/openalice-data/ideascientist/data/paper-code/'
                     '20261013-paper-code-v1/retrieval-profile.json')


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
    return h.hexdigest()


def environment(path):
    profile=json.loads(Path(path).read_text())
    for family in ('finance','code'):
        entry=profile[family]
        if sha(entry['db'])!=entry['sha256']:raise ValueError(family+' database hash differs')
    for module,expected in profile['runtime_modules'].items():
        if sha(module)!=expected:raise ValueError('Pinned runtime module differs: '+module)
    return {'IDEA_VAULT_DB':profile['vault_db'],'IDEASCIENTIST_KEYWORD_INDEX':profile['keyword_index'],
        'IDEASCIENTIST_FINANCE_DB':profile['finance']['db'],
        'IDEASCIENTIST_FINANCE_SHA256':profile['finance']['sha256'],
        'IDEASCIENTIST_CODE_DB':profile['code']['db'],
        'IDEASCIENTIST_CODE_SHA256':profile['code']['sha256'],
        'IDEASCIENTIST_CODE_AVAILABILITY_DATE':profile['code']['availability_date'],
        'IDEASCIENTIST_CUTOFF_DATE':profile['cutoff'],'PYTHONPATH':profile['patched_runtime']}
