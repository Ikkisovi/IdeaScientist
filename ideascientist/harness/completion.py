"""Bounded finalization and evidence reports for IdeaScientist runs."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path


def verdicts(docs: Path) -> dict[str, str]:
    scores = (docs / "scores.md").read_text() if (docs / "scores.md").exists() else ""
    result = {}
    for match in re.finditer(r"^###\s+(C\d+)\b[^\n]*\n(.*?)(?=^###\s+C\d+\b|\Z)", scores, re.M | re.S):
        verdict = re.search(r"\*\*Verdict\*\*\s*:\s*`?(survive|revise|reject)\b", match[2], re.I)
        if verdict:
            result[match[1]] = verdict[1].lower()
    return result


def proposal(docs: Path) -> dict | None:
    path = docs / "report.json"
    if not path.exists():
        return None
    try:
        from ideascientist.rewards.report_writer.parser import parse_report_text
        report = parse_report_text(path.read_text())
        return report.obj if report.has_all_fields() else None
    except Exception:
        return None


def render_proposal(rep: dict) -> str:
    # Load the pure renderer without importing the optional evaluation stack.
    import ideascientist
    path = Path(ideascientist.__file__).parent / "evaluation/render.py"
    spec = importlib.util.spec_from_file_location("ideascientist_completion_render", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.render_report(rep)


def complete(run_dir: Path, reason: str, error: str = "") -> dict:
    """Publish a readable result without turning rejected ideas into proposals."""
    docs = run_dir / "outputs"
    docs.mkdir(parents=True, exist_ok=True)
    rep = proposal(docs)
    rendered = ""
    if rep:
        try:
            rendered = render_proposal(rep)
        except Exception as exc:
            rep = None
            error = error or f"Report rendering failed: {type(exc).__name__}: {exc}"
    decisions = verdicts(docs)
    survivors = [cid for cid, value in decisions.items() if value == "survive"]
    status = "proposal_unvalidated" if rep else (
        "writer_incomplete" if survivors else "no_surviving_candidate")
    sources = {}
    for name in ("problem.md", "plan.md", "gaps.md", "candidates.md", "scores.md", "report.json"):
        path = docs / name
        if path.exists():
            sources[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = {"status": status, "reason": reason, "finalizer_error": error,
               "generated_at": datetime.now(timezone.utc).isoformat(),
               "verdicts": decisions, "survivors": survivors, "source_sha256": sources,
               "completion_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "experiments_run": False, "review_pass_implied": False}
    lines = ["# IdeaScientist final report", "", f"Status: **{status}**",
             f"Termination: `{reason}`", "",
             "This run generated research ideas; it did not execute experiments. "
             "Report delivery does not imply scientific validation.", ""]
    if error:
        lines += [f"Finalization error: {error}", ""]
    if rep:
        lines += [rendered]
    else:
        candidates = (docs / "candidates.md").read_text() if (docs / "candidates.md").exists() else ""
        titles = dict(re.findall(r"^###\s+(C\d+)\s*[—–-]\s*(.+)$", candidates, re.M))
        scores = (docs / "scores.md").read_text() if (docs / "scores.md").exists() else ""
        objections = {}
        for match in re.finditer(r"^###\s+(C\d+)\b[^\n]*\n(.*?)(?=^###\s+C\d+\b|\Z)", scores, re.M | re.S):
            objection = re.search(r"\*\*Strongest objection[^\n]*?\*\*\s*:\s*(.+)", match[2])
            if objection:
                objections[match[1]] = objection[1]
        lines += ["## Decision", "",
                  "No complete proposal was delivered. Review verdicts remain unchanged. "
                  "The evidence below preserves the work and its unresolved objections.", "",
                  "| Candidate | Latest verdict | Main objection |", "| --- | --- | --- |"]
        for cid in dict.fromkeys([*titles, *decisions]):
            title = titles.get(cid, "").replace("|", "\\|")
            objection = objections.get(cid, "See scores.md" if cid in decisions else "Not reviewed").replace("|", "\\|")
            lines.append(f"| {cid}: {title} | {decisions.get(cid, 'unreviewed')} | {objection} |")
        lines += ["", "## Next steps", "",
                  "Address the specific grounding, novelty, and feasibility objections in scores.md "
                  "before another search or proposal. Unreviewed candidates require review. "
                  "If a survivor exists, finish its report without expanding the candidate pool.", ""]
        for name in ("problem.md", "gaps.md", "candidates.md", "scores.md", "plan.md"):
            path = docs / name
            if path.exists():
                lines += [f"## Evidence: {name}", "", path.read_text(), ""]
    text = "\n".join(lines).rstrip() + "\n"
    # Recovery is append-only with respect to any existing report.
    target = docs / "report.md"
    if target.exists() and target.read_text().strip():
        target = docs / "completion_report.md"
    temporary = target.with_suffix(".md.tmp")
    temporary.write_text(text)
    os.replace(temporary, target)
    receipt["report_file"] = target.name
    receipt["report_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    receipt_path = docs / "completion.json"
    tmp = receipt_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(receipt, indent=2) + "\n")
    os.replace(tmp, receipt_path)
    return receipt


def active_runs(root: Path) -> set[Path]:
    active = set()
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            args = (proc / "cmdline").read_bytes().decode().split("\0")
            if not any(arg.endswith("/run_ideation.py") for arg in args):
                continue
            base = Path(args[args.index("--run-dir") + 1])
            if not base.is_absolute():
                base = (proc / "cwd").resolve() / base
            base = base.resolve()
            if not base.is_relative_to(root.resolve()):
                continue
            cid = args[args.index("--problem-id") + 1]
            active.update(p.resolve() for p in base.glob(f"*_{cid}") if p.is_dir())
        except (OSError, ValueError, IndexError, UnicodeError):
            continue
    return active


def recover(root: Path) -> tuple[list[dict], bool]:
    active = active_runs(root)
    results = []
    for run in sorted(root.glob("runs_*/*")):
        if not run.is_dir() or run.resolve() in active or not (run / "outputs/problem.md").exists():
            continue
        if (run / "outputs/completion.json").exists():
            continue
        summary = run / "logs/summary.json"
        if not summary.exists():
            # An absent owner alone is not evidence of a graceful completion.
            reason = "owner_exited_without_summary"
        else:
            reason = "legacy_run_completed"
            try:
                events = json.loads((run / "logs/harness_log.json").read_text())
                endings = [event for event in events if event.get("kind") == "loop_end"]
                if endings:
                    reason = "legacy_" + endings[-1]["reason"]
            except (OSError, ValueError, KeyError, TypeError):
                pass
        results.append({"run_dir": str(run), **complete(run, reason)})
    return results, bool(active)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recover", type=Path, required=True)
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    while True:
        results, running = recover(args.recover)
        for result in results:
            print(json.dumps(result), flush=True)
        if not args.watch or not running:
            break
        time.sleep(10)


if __name__ == "__main__":
    main()
