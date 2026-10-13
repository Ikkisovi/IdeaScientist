#!/usr/bin/env python3
"""Exercise real containment with an engineering fixture, never a scientific pass."""
import json
from pathlib import Path
import time

from materialize import OUTPUT_HOME, execute, limits_for, scope_for, write


def main():
    root = OUTPUT_HOME / ("canary-" + time.strftime("%Y%m%dT%H%M%S"))
    root.mkdir(parents=True)
    config = {"manifest": "/mnt/samsung_ssd/openalice-data/lea91-qc-basis-rebuild-20261005-v1/publication/release/manifest.json",
              "manifest_sha256": "872dbbf9fedd9a07ec885bc6c8e53ab22cdc47712ad31c0348a982b56ae6ccca",
              "date_slice": [2520, 2776], "entity_indices": list(range(128)),
              "fields": ["core_daily_fields__close", "core_daily_fields__volume"],
              "cpus": [18, 19], "memory_mib": 512, "wall_seconds": 30}
    scope, mounts = scope_for(config)
    write(root / "scope.json", scope)
    (root / "experiment.py").write_text('''import json, socket, os, time
from pathlib import Path
import numpy as np
from panel import load_panel
t = time.monotonic()
data = load_panel()
denied = {}
for path in ["/data/0-values.npy", "/app/panel.py", "/usr/ideamaterializer-write-probe"]:
    try:
        with open(path, "ab") as f: f.write(b"probe")
    except OSError: denied[path] = True
    else: raise AssertionError("write escaped sandbox")
assert not Path("/home/ikkipipi/.pi/agent/models.json").exists()
assert "IDEASCIENTIST_API_KEY" not in os.environ
assert os.sched_getaffinity(0) == {18, 19}
try:
    socket.create_connection(("127.0.0.1", 18321), timeout=1)
except OSError: denied["network"] = True
else: raise AssertionError("network escaped sandbox")
cells = data["values"].size
Path("results.json").write_text(json.dumps({"engineering_fixture": True, "scientific_pass": False,
    "shape": list(data["values"].shape), "finite_cells": int(np.isfinite(data["values"]).sum()),
    "cells_per_second": cells / (time.monotonic()-t), "denied": denied}))
''')
    code = execute(root, mounts, limits_for(config))
    if code:
        raise RuntimeError((root / "experiment.log").read_text())
    for name, script, seconds, memory in [
        ("timeout", "import time\ntime.sleep(20)\n", 2, 256),
        ("memory", "import os,time\nfor _ in range(2):\n if os.fork()==0:\n  x=bytearray(160*1024*1024)\n  time.sleep(20)\n  os._exit(0)\ntime.sleep(20)\n", 10, 256)]:
        out = root / name
        out.mkdir()
        write(out / "scope.json", scope)
        (out / "experiment.py").write_text(script)
        result = execute(out, [], limits_for({**config, "wall_seconds": seconds, "memory_mib": memory}))
        if result == 0:
            raise AssertionError(name + " containment failed")
        reason = "oom-kill" if name == "memory" else "result 'timeout'"
        if reason not in (out / "supervisor.log").read_text():
            raise AssertionError(name + " failed without the expected supervisor disposition")
    write(root / "acceptance.json", {"engineering_only": True, "readonly_network_secret": "passed",
          "aggregate_memory_and_timeout": "passed", "config": config})
    print(root)


if __name__ == "__main__":
    main()
