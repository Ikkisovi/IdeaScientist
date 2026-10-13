"""Measure the sandboxed worker, including its descendants, on every normal exit."""
import json
import hashlib
from pathlib import Path
import resource
import runpy
import time

started = time.monotonic()
try:
    receipt = json.loads(Path("/execution.json").read_text())
    if hashlib.sha256(Path("/experiment.py").read_bytes()).hexdigest() != receipt["experiment_sha256"]:
        raise ValueError("Experiment changed at worker handoff")
    for name, expected in receipt["source_sha256"].items():
        if hashlib.sha256(Path("/app", name).read_bytes()).hexdigest() != expected:
            raise ValueError("Materializer source changed at worker handoff")
    runpy.run_path("/experiment.py", run_name="__main__")
finally:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    Path("/output/runtime.json").write_text(json.dumps({
        "wall_seconds": time.monotonic() - started,
        "cpu_seconds": usage.ru_utime + usage.ru_stime + children.ru_utime + children.ru_stime,
        "worker_max_rss_kib": usage.ru_maxrss, "children_max_rss_kib": children.ru_maxrss,
        "note": "RSS is process peak, not aggregate cgroup peak; SIGKILL cannot run finally"}, indent=2))
