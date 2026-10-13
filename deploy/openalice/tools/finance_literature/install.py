#!/usr/bin/env python3
"""Install an opt-in financial retrieval extension and hash-bound current-literature profile."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil

HERE = Path(__file__).resolve().parent
RUNTIME = Path('/mnt/samsung_ssd/openalice-data/ideascientist')
COLLECTION = Path('/mnt/qnap-workstation/literature-library/external/finance-economics-quant')
MARKER = '\n# OpenAlice optional financial literature extension.\n'
HOOK = MARKER + '''if os.environ.get("IDEASCIENTIST_FINANCE_DB"):
    import sys as _finance_sys
    from .finance_overlay import install as _install_finance
    _install_finance(_finance_sys.modules[__name__], os.environ["IDEASCIENTIST_FINANCE_DB"],
                     os.environ.get("IDEASCIENTIST_FINANCE_SHA256", ""))
'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('collection', type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.collection / 'manifest.json').read_text())
    if sha(args.collection / 'finance.db') != manifest['finance_db_sha256']:
        raise ValueError('Dataset publication hash differs')
    local = RUNTIME / 'data/finance-literature' / args.collection.name
    local.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(args.collection / 'finance.db', local / 'finance.db')
    shutil.copyfile(args.collection / 'manifest.json', local / 'manifest.json')
    if sha(local / 'finance.db') != manifest['finance_db_sha256']:
        raise ValueError('Local exact readback differs')
    corpus = RUNTIME / 'IdeaScientist-patched/ideascientist/harness/corpus.py'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = RUNTIME / 'backups' / (stamp + '-finance-overlay')
    backup.mkdir(parents=True)
    shutil.copyfile(corpus, backup / 'corpus.py')
    module = corpus.with_name('finance_overlay.py')
    if module.exists():
        shutil.copyfile(module, backup / 'finance_overlay.py')
    shutil.copyfile(HERE / 'finance_overlay.py', module)
    original = corpus.read_text()
    if MARKER not in original:
        corpus.write_text(original + HOOK)
    cutoff = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    env = {'IDEASCIENTIST_FINANCE_DB': str(local / 'finance.db'),
           'IDEASCIENTIST_FINANCE_SHA256': manifest['finance_db_sha256'],
           'IDEASCIENTIST_CUTOFF_DATE': cutoff,
           'PYTHONPATH': str(RUNTIME / 'IdeaScientist-patched')}
    profile = RUNTIME / ('finance-env-' + args.collection.name + '.sh')
    with profile.open('x') as stream:
        stream.write('source ' + shlex.quote(str(RUNTIME / 'env.sh')) + '\n')
        for key, value in env.items():
            stream.write('export ' + key + '=' + shlex.quote(value) + '\n')
    with (local / 'installation.json').open('x') as stream:
        json.dump({'collection': str(args.collection), 'finance_db_sha256': sha(local / 'finance.db'),
                   'module_sha256': sha(module), 'corpus_before_sha256': sha(backup / 'corpus.py'),
                   'corpus_after_sha256': sha(corpus), 'profile': str(profile), 'backup': str(backup),
                   'activation': 'opt-in profile only; existing env.sh unchanged',
                   'cutoff': cutoff, 'historical_source_availability': 'capture-date fenced'}, stream, indent=2)
    print(profile)


if __name__ == '__main__':
    main()
