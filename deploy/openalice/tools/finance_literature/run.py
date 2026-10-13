#!/usr/bin/env python3
"""Launch current-literature IdeaScientist with the hash-bound finance extension."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from retrieval_profile import DEFAULT_PROFILE, environment

RUNTIME = Path('/mnt/samsung_ssd/openalice-data/ideascientist')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('collection', type=Path)
    parser.add_argument('problem', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--max-turns', type=int, default=32)
    parser.add_argument('--sub-turns', type=int, default=8)
    parser.add_argument('--literature-profile', type=Path, default=DEFAULT_PROFILE)
    args = parser.parse_args()
    installation = json.loads((args.collection / 'installation.json').read_text())
    manifest = json.loads((args.collection / 'manifest.json').read_text())
    env = dict(os.environ)
    env.update(IDEA_VAULT_DB=str(RUNTIME / 'data/idea_vault.db'),
        IDEASCIENTIST_FINANCE_DB=str(args.collection.resolve() / 'finance.db'),
        IDEASCIENTIST_FINANCE_SHA256=manifest['finance_db_sha256'],
        IDEASCIENTIST_CUTOFF_DATE=installation['cutoff'],
        IDEASCIENTIST_EMBEDDING_DIR=str(RUNTIME / 'data/paper_embeddings_subset'),
        PYTHONPATH=str(RUNTIME / 'IdeaScientist-patched'),
        HF_HOME=str(RUNTIME / 'hf'), HF_HUB_OFFLINE='1',
        IDEASCIENTIST_READER_TOKENIZER='Qwen/Qwen3-Embedding-0.6B',
        IDEASCIENTIST_BASE_URL='http://127.0.0.1:18321/v1',
        IDEASCIENTIST_MODEL='muse-spark-1.3-contributor',
        IDEASCIENTIST_ROLE_BASE_URL=json.dumps({'reviewer':'http://127.0.0.1:8317/v1'}),
        IDEASCIENTIST_ROLE_MODEL=json.dumps({'reviewer':'gpt-6-astra'}),
        IDEASCIENTIST_ROLE_TURN_CAP=json.dumps({r:args.sub_turns for r in
            ['gap_finder','innovator','reviewer','paper_reader','report_writer']}))
    env.update(environment(args.literature_profile))
    if env['IDEASCIENTIST_FINANCE_SHA256']!=manifest['finance_db_sha256']:
        raise ValueError('Shared profile and selected finance collection differ')
    profiles = json.loads(Path.home().joinpath('.pi/agent/models.json').read_text())
    env['IDEASCIENTIST_API_KEY'] = profiles['providers']['codex-local']['apiKey']
    args.out.mkdir(parents=True, exist_ok=False)
    command = [str(RUNTIME / 'venv/bin/python'),
        str(RUNTIME / 'IdeaScientist-patched/scripts/run_ideation.py'),
        '--problem-file',str(args.problem.resolve()),'--run-dir',str(args.out / 'runs_spark'),
        '--model',env['IDEASCIENTIST_MODEL'],'--max-turns',str(args.max_turns),
        '--max-sub-turns',str(args.sub_turns),'--finalization-turns','8']
    (args.out / 'launch.json').write_text(json.dumps({'command':command,
        'finance_db_sha256':manifest['finance_db_sha256'],'cutoff':installation['cutoff'],
        'literature_profile':str(args.literature_profile),
        'literature_profile_sha256':hashlib.sha256(args.literature_profile.read_bytes()).hexdigest(),
        'problem_sha256':hashlib.sha256(args.problem.read_bytes()).hexdigest()},indent=2))
    with (args.out / 'ideation.log').open('w') as log:
        result = subprocess.run(command, env=env, cwd=RUNTIME, stdout=log,stderr=subprocess.STDOUT)
    (args.out / 'exit.json').write_text(json.dumps({'exit_code':result.returncode}))
    return result.returncode


if __name__=='__main__':
    raise SystemExit(main())
