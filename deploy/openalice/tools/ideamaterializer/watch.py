#!/usr/bin/env python3
"""Wait for an owner to finish, then materialize a unique surviving candidate."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from materialize import sha, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("attempt", type=Path)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    config_hash = sha(args.config)
    deadline = time.monotonic() + 3700
    while not (args.attempt / "exit.json").exists():
        if time.monotonic() >= deadline:
            write(args.attempt / "materialization.json", {"status": "owner_not_finished", "executed": False})
            return 75
        time.sleep(10)
    runs = list((args.attempt / "runs_spark").glob("*/outputs/completion.json"))
    if len(runs) != 1:
        write(args.attempt / "materialization.json", {"status": "missing_completion", "executed": False})
        return 75
    receipt = json.loads(runs[0].read_text())
    survivors = [cid for cid, verdict in receipt["verdicts"].items() if verdict == "survive"]
    if receipt["status"] != "proposal_unvalidated" or len(survivors) != 1:
        write(args.attempt / "materialization.json", {"status": "no_unique_passing_proposal",
              "completion": receipt["status"], "verdicts": receipt["verdicts"], "executed": False})
        return 0
    command = [sys.executable, str(Path(__file__).with_name("materialize.py")),
               str(runs[0].parent.parent), survivors[0], str(args.config.resolve())]
    if sha(args.config) != config_hash:
        write(args.attempt / "materialization.json", {"status": "config_changed", "executed": False})
        return 75
    with (args.attempt / "materializer.log").open("x") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    write(args.attempt / "materialization.json", {"status": "materializer_finished", "exit_code": result.returncode,
          "log": str(args.attempt / "materializer.log"), "command": command})
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
