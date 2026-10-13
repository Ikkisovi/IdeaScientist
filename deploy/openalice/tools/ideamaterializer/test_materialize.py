import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("materialize", Path(__file__).with_name("materialize.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class MaterializerTests(unittest.TestCase):
    def test_literature_hash_failure_prevents_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);config=out/'config.json';config.write_text('{}')
            args=SimpleNamespace(run=out,candidate='C1',config=config)
            with patch.object(m,'passing_proposal',return_value={'candidate':'C1'}), \
                 patch.object(m,'scope_for',return_value=({},[])), \
                 patch.object(m,'limits_for',return_value={}), \
                 patch('literature.retrieve',side_effect=ValueError('database hash differs')), \
                 patch.object(m,'ask') as ask:
                with self.assertRaisesRegex(ValueError,'hash differs'):m.materialize(args,out)
                ask.assert_not_called()

    def test_latest_review_and_hashes_bind_admission(self):
        with tempfile.TemporaryDirectory() as temp:
            docs = Path(temp) / "outputs"
            docs.mkdir()
            for name, value in {"problem.md": "problem", "candidates.md": "### C1 - candidate",
                                "scores.md": "### C1 verdict\n- **Verdict**: survive\n",
                                "report.json": json.dumps({f: "fixture" for f in m.FIELDS})}.items():
                (docs / name).write_text(value)
            completion = {"status": "proposal_unvalidated", "verdicts": {"C1": "survive"},
                          "source_sha256": {p.name: m.sha(p) for p in docs.iterdir()}}
            (docs / "completion.json").write_text(json.dumps(completion))
            logs = Path(temp) / "logs/_sublogs"
            logs.mkdir(parents=True)
            (logs / "reviewer.json").write_text(json.dumps([{"model": "gpt-6-astra"}]))
            self.assertEqual(m.passing_proposal(temp, "C1")["candidate"], "C1")
            with (docs / "scores.md").open("a") as stream:
                stream.write("### C1 verdict\n- **Verdict**: revise\n")
            with self.assertRaisesRegex(ValueError, "hash"):
                m.passing_proposal(temp, "C1")
            completion["source_sha256"]["scores.md"] = m.sha(docs / "scores.md")
            (docs / "completion.json").write_text(json.dumps(completion))
            with self.assertRaisesRegex(ValueError, "survive"):
                m.passing_proposal(temp, "C1")

    def test_caps_and_command(self):
        cpus = sorted(os.sched_getaffinity(0))[:2]
        limits = m.limits_for({"cpus": cpus})
        for invalid in ({"cpus": cpus, "memory_mib": 4097}, {"cpus": cpus, "wall_seconds": 601},
                        {"cpus": [cpus[0], cpus[0]]}):
            with self.assertRaises(ValueError):
                m.limits_for(invalid)
        command = m.sandbox_command(Path("/tmp/fixture"), [], limits, "fixture")
        for option in ("--unshare-all", "--clearenv", "--property=MemorySwapMax=0",
                       "--property=TasksMax=64", "--property=KillMode=control-group"):
            self.assertIn(option, command)
        self.assertNotIn(str(Path.home() / ".pi"), " ".join(command))

    def test_rejected_script_never_executes(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            config = out / "config.json"
            config.write_text("{}")
            args = SimpleNamespace(run=out, candidate="C1", config=config)
            scope = {"date_slice": [0, 2], "shape": [2, 2], "labels": None,
                     "qualification": "fixture", "fields": []}
            with patch.object(m, "passing_proposal", return_value={"candidate": "C1"}), \
                 patch.object(m, "scope_for", return_value=(scope, [])), \
                 patch.object(m, "limits_for", return_value={}), \
                 patch('literature.retrieve', return_value={'papers':[], 'repositories':[]}), \
                 patch.object(m, "ask", side_effect=[({"script": "print('fixture')", "plan": {}}, {}),
                                                    ({"pass": False, "objections": ["missing controls"]}, {})]), \
                 patch.object(m, "execute") as execute:
                self.assertEqual(m.materialize(args, out), 75)
                execute.assert_not_called()
                self.assertEqual(json.loads((out / "result.json").read_text())["status"], "script_rejected")

    def test_scope_refuses_oversized_projection(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.json"
            path.write_text(json.dumps({"schema": "lea91-qc-research-corpus-v1",
                                       "fmp_dependencies": [], "shape": [3000, 951]}))
            config = {"manifest": str(path), "manifest_sha256": m.sha(path),
                      "date_slice": [0, 513], "entity_indices": [0], "fields": ["f"]}
            with self.assertRaisesRegex(ValueError, "Scope exceeds"):
                m.scope_for(config)


if __name__ == "__main__":
    unittest.main()
