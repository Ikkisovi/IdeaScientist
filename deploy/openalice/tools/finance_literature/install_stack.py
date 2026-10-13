#!/usr/bin/env python3
"""Install a versioned, opt-in shared IdeaScientist/Materializer retrieval profile."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shlex
import shutil

from code_index import save, sha

RUNTIME=Path('/mnt/samsung_ssd/openalice-data/ideascientist')
HERE=Path(__file__).resolve().parent
MARKER='\n# OpenAlice optional paper-code evidence extension.\n'
HOOK=MARKER+'''if os.environ.get("IDEASCIENTIST_CODE_DB"):
    from .code_overlay import install as _install_code
    _install_code(_finance_sys.modules[__name__] if "_finance_sys" in globals() else __import__("sys").modules[__name__],
                  os.environ["IDEASCIENTIST_CODE_DB"], os.environ.get("IDEASCIENTIST_CODE_SHA256", ""),
                  os.environ["IDEASCIENTIST_CODE_AVAILABILITY_DATE"])
'''


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('finance',type=Path);p.add_argument('code',type=Path);args=p.parse_args()
    fm=json.loads((args.finance/'manifest.json').read_text());cm=json.loads((args.code/'manifest.json').read_text())
    assert sha(args.finance/'finance.db')==fm['finance_db_sha256']
    assert sha(args.code/'code.db')==cm['code_db_sha256']
    now=datetime.now(timezone.utc)
    profile={'schema':'materializer-literature-profile/1',
        'finance':{'db':str(args.finance/'finance.db'),'sha256':fm['finance_db_sha256']},
        'code':{'db':str(args.code/'code.db'),'sha256':cm['code_db_sha256'],'availability_date':now.date().isoformat()},
        'vault_db':str(RUNTIME/'data/idea_vault.db'),'keyword_index':str(RUNTIME/'data/keyword_index.db'),
        'patched_runtime':str(RUNTIME/'IdeaScientist-patched'),
        'cutoff':(now+timedelta(days=1)).date().isoformat()}
    corpus=RUNTIME/'IdeaScientist-patched/ideascientist/harness/corpus.py'
    backup=RUNTIME/'backups'/(now.strftime('%Y%m%dT%H%M%SZ')+'-paper-code')
    backup.mkdir();shutil.copyfile(corpus,backup/'corpus.py')
    target=corpus.with_name('code_overlay.py')
    if target.exists():shutil.copyfile(target,backup/'code_overlay.py')
    shutil.copyfile(HERE/'code_overlay.py',target)
    before=corpus.read_text()
    if MARKER not in before:corpus.write_text(before+HOOK)
    profile['runtime_modules']={str(module):sha(module) for module in
        (corpus,target,corpus.with_name('finance_overlay.py'))}
    path=args.code/'retrieval-profile.json';save(path,profile)
    shell=RUNTIME/('finance-code-env-'+args.code.name+'.sh')
    env={'PYTHONPATH':profile['patched_runtime'],'IDEASCIENTIST_FINANCE_DB':profile['finance']['db'],
        'IDEASCIENTIST_FINANCE_SHA256':profile['finance']['sha256'],
        'IDEASCIENTIST_CODE_DB':profile['code']['db'],'IDEASCIENTIST_CODE_SHA256':profile['code']['sha256'],
        'IDEASCIENTIST_CODE_AVAILABILITY_DATE':profile['code']['availability_date'],
        'IDEASCIENTIST_CUTOFF_DATE':profile['cutoff']}
    with shell.open('x') as f:
        f.write('source '+shlex.quote(str(RUNTIME/'env.sh'))+'\n')
        for k,v in env.items():f.write('export '+k+'='+shlex.quote(v)+'\n')
    save(args.code/'installation.json',{'profile':str(path),'profile_sha256':sha(path),'shell_profile':str(shell),
        'backup':str(backup),'corpus_before_sha256':sha(backup/'corpus.py'),
        'corpus_after_sha256':sha(corpus),'module_sha256':sha(target),
        'default_env_changed':False,'running_processes_changed':False})
    print(path)


if __name__=='__main__':main()
