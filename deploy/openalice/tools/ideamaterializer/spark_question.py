#!/usr/bin/env python3
"""Launch one short Spark ideation with Astra reviewing, without dataset access."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'finance_literature'))
from retrieval_profile import DEFAULT_PROFILE, environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("problem", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--literature-profile", type=Path, default=DEFAULT_PROFILE)
    args = parser.parse_args()
    runtime = Path("/mnt/samsung_ssd/openalice-data/ideascientist")
    env = dict(os.environ)
    env.update(IDEA_VAULT_DB=str(runtime / "data/idea_vault.db"),
               HF_HOME=str(runtime / "hf"), HF_HUB_OFFLINE="1",
               PYTHONPATH=str(runtime / "IdeaScientist-patched"),
               IDEASCIENTIST_READER_TOKENIZER="Qwen/Qwen3-Embedding-0.6B",
               IDEASCIENTIST_BASE_URL="http://127.0.0.1:18321/v1",
               IDEASCIENTIST_MODEL="muse-spark-1.3-contributor",
               IDEASCIENTIST_ROLE_BASE_URL=json.dumps({"reviewer": "http://127.0.0.1:8317/v1"}),
               IDEASCIENTIST_ROLE_MODEL=json.dumps({"reviewer": "gpt-6-astra"}),
               IDEASCIENTIST_ROLE_TURN_CAP=json.dumps({r: 8 for r in
                   ["gap_finder", "innovator", "reviewer", "paper_reader", "report_writer"]}),
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    env.update(environment(args.literature_profile))
    profiles = json.loads(Path.home().joinpath(".pi/agent/models.json").read_text())
    env["IDEASCIENTIST_API_KEY"] = profiles["providers"]["codex-local"]["apiKey"]
    args.out.mkdir(parents=True, exist_ok=False)
    command = [str(runtime / "venv/bin/python"),
               str(runtime / "IdeaScientist-patched/scripts/run_ideation.py"),
               "--problem-file", str(args.problem.resolve()), "--problem-id", "raven-context-value",
               "--model", env["IDEASCIENTIST_MODEL"], "--run-dir", str(args.out / "runs_spark"),
               "--max-turns", "32", "--max-sub-turns", "8", "--finalization-turns", "8"]
    (args.out / "launch.json").write_text(json.dumps({"command": command,
        "problem_sha256": hashlib.sha256(args.problem.read_bytes()).hexdigest(),
        "configured_producer": env["IDEASCIENTIST_MODEL"], "configured_reviewer": "gpt-6-astra",
        "literature_profile": str(args.literature_profile),
        "literature_profile_sha256": hashlib.sha256(args.literature_profile.read_bytes()).hexdigest(),
        "exploration_turns": 24, "finalization_turns": 8, "subagent_turns": 8,
        "experiments_run": False}, indent=2))
    with (args.out / "spark.log").open("w") as log:
        result = subprocess.run(command, env=env, cwd=runtime, stdout=log, stderr=subprocess.STDOUT)
    (args.out / "exit.json").write_text(json.dumps({"exit_code": result.returncode}))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
