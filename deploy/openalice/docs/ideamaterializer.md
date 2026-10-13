# IdeaMaterializer

IdeaScientist produces literature-grounded proposals. IdeaMaterializer turns a
complete proposal whose selected candidate has a latest Astra `survive` verdict
into a small, executable experiment. Successful execution is distinct from a
scientific pass, formal research admission or deployment.

Source is in `scripts/ideamaterializer/`. Runtime artifacts are create-only under
`/mnt/samsung_ssd/openalice-data/ideamaterializer/`; datasets and credentials never
enter Git. The branch is additive and does not modify the existing harness.

## Pipeline

1. Verify completion hashes for problem, candidates, scores and proposal. Require
   the complete 14-field proposal, latest surviving candidate, and Astra requested
   model evidence in the harness reviewer log. This log records routing intent;
   it is not independent provider execution-identity proof.
2. Pin a corpus manifest, identity registry and axes. Project selected source
   files through a read-only loader with original values, reasons and membership
   qualifications. Caps are 512 dates, 256 historical entities and 32 fields.
3. Spark generates a frozen plan and Python script. Astra reviews that exact
   plan/script against the candidate, proposal, available inputs and temporal
   rules. No surviving proposal, missing necessary inputs or rejected script
   produces a retained disposition without running an experiment.
4. Execute one worker under an aggregate systemd cgroup: at most two pinned CPUs,
   4 GiB RAM, zero additional swap, 64 tasks, ten minutes, reduced priority.
   Bubblewrap supplies a new PID/network namespace, a cleared environment,
   read-only interpreter/source/selected-data mounts and a private writable output.
   Host home, provider credentials, live storage and GPU devices are absent.
   A file is limited to 256 MiB; the supervisor stops aggregate output above
   256 MiB (sampled, so short overshoot is possible). Temporary files use a
   memory-accounted tmpfs. Resource/namespace enforcement failure fails closed.
5. Record exact source/script/plan/input/output hashes, limits, exit code,
   wall/CPU time and process RSS. Scripts must emit `results.json` and domain
   throughput. An exit zero without valid JSON is an execution failure. The
   scientific interpretation remains in the measured results; no automatic
   promotion or unmeasured quality claim is made.

The new paper/code-index branch retrieves literature before script generation,
using `scripts/finance_literature/retrieve.py` and the same pinned finance/code
profile as IdeaScientist. It writes `literature.json` with paper IDs, repository
links, detected licenses, exact Git commit IDs, README hashes/excerpts and the
paper contexts where links occurred. Both Spark and Astra receive this evidence.
The default is the versioned `20261013-paper-code-v1/retrieval-profile.json`
under the IdeaScientist runtime; override with `--literature-profile` or a
`literature_profile` in scope configuration. Missing/mismatched indexes fail
closed before any generation call. Repository evidence is reference material;
external code is not installed or executed, and the existing execution sandbox
and scientific admission gates still apply.

Only problem text, proposal, public literature/repository evidence and
schema/qualification metadata go to the LLMs.
No factor values or paid-data rows are sent. There are two generation/review
calls per materialization; there is no unbounded correction loop.

## Run

Use the validated host environment, not the lightweight ideation venv:

```bash
source /home/ikkipipi/openalice/scripts/openalice_python_env.sh
$OPENALICE_PYTHON scripts/ideamaterializer/materialize.py \
  <ideascientist-run-dir> C1 <scope.json>
```

The scope schema is illustrated by `scripts/ideamaterializer/raven-scope.json`.
It deliberately provides factor inputs only. These are source observations,
with missingness and research membership qualifications, not certified PIT
or executable return labels. Choose entities using past information; the sample
indices are an engineering scope, not a claimed representative market universe.

For predictive experiments, additionally provide `label_manifest` and
`label_manifest_sha256`. A `ideamaterializer-labels/1` manifest must contain
`shape`, the exact corpus `axes_sha256`, `definition`, `qualification`,
`source_receipt_sha256`, `horizon_sessions`, and `values`, `reason`,
`realization_index` entries with absolute `path` and `sha256`. Arrays share the
full date/entity grid. Values are float64, reasons uint8 and realization indices
integers. Finite labels require reason zero and future realization within the
calendar. All hashes and selected values are checked inside the bounded worker.
The label receipt must come from an independently qualified label preparation;
this interface does not certify a label merely because its hashes match.
Split purging uses actual realization indices. Never derive return labels from
the factor panels' raw close/open or silently fill unavailable prices.

## Short RAVEN question

`spark_question.py <problem.txt> <new-attempt-dir>` invokes Spark with Astra
reviewing: 24 exploration turns plus an eight-turn writer reserve; each nested
role is capped at eight tool-loop turns. Nested readers still make additional
API calls, so 32 is not a total API-call count. A writer failure or no survivor
still leaves the existing completion evidence report.

`watch.py <attempt-dir> <scope.json>` waits for owner exit and invokes the
materializer only for exactly one surviving complete proposal. Other outcomes
produce `materialization.json`. Run launchers with a durable systemd user unit;
do not rerun an existing owner. A missing owner exit is recorded after the
bounded wait. Input insufficiency remains explicit rather than generating fake
market results.

## Verification

```bash
$OPENALICE_PYTHON -m unittest discover -s scripts/ideamaterializer -p test_materialize.py
$OPENALICE_PYTHON scripts/ideamaterializer/canary.py
```

The engineering canary reads a real hash-bound corpus slice and verifies source
write denial, source-code write denial, missing credentials and network denial.
Separate runs verify a wall timeout and memory kill. It bypasses scientific
admission only as a clearly labelled engineering fixture, never as a research
claim. SIGKILL cannot emit the worker's final runtime statistics; the external
supervisor still retains failure/elapsed-time evidence.
