---
name: ideascientist
description: Run the IdeaScientist research-ideation harness (arXiv 2610.04074) on the workstation with API backbones (Gemini 3.8 flash, muse-spark, GLM-5.3-flash) and a gpt-6-astra reviewer, grounded in the 2.67M-paper Svalbard Idea Vault. Use it to turn a stuck research problem into literature-grounded research proposals, or to judge proposals with the paper's rubric.
---

# IdeaScientist

IdeaScientist is a multi-agent harness: orchestrator → gap_finder → innovator →
reviewer → report_writer, plus a paper_reader. It searches a vault of arXiv
idea records and writes a research proposal for a stated problem.

We run it untrained. The paper's per-role GRPO weights are not used, and every
role goes through a loopback API bridge.

Evidence from our reproduction, 10-problem pilot, judged by astra:
- Patched-harness proposals score at about the level of the human paper on the
  same problem: spark +0.16, Gemini +0.17 on the 10-point rubric. That is
  within judge noise.
- The harness runs no experiments.

Treat its output as untested, literature-grounded ideas, never as results. See
`references/REPRODUCTION.md`.

## Layout

| What | Where |
|---|---|
| This skill: scripts and bridges (source of truth) | `/home/ikkipipi/openalice/.agents/skills/ideascientist/` |
| Runtime (`IDEASCIENTIST_HOME`) | `/mnt/samsung_ssd/openalice-data/ideascientist/` |
| Upstream pristine clone, pinned `82a98a0` | `/mnt/qnap-workstation/literature-library/external/repos/IdeaScientist` |
| Upstream PR with the reader fixes | https://github.com/jiarui-liu/IdeaScientist/pull/2 |

Runtime contents:
- `venv/`: Python 3.14, CPU torch.
- `IdeaScientist-patched/`: upstream plus `references/openalice-ideascientist.patch`.
- `data/idea_vault.db` (27 GB), `data/keyword_index.db`, `data/vault_fts.db`.
- `hf/`: Qwen3-Embedding-0.6B tokenizer.
- `env.sh`, `logs/`.

## Bridges (loopback; credentials resolved from `~/.pi/agent/models.json`, never printed)

| Name | Port | Upstream | Model id passed to the harness |
|---|---|---|---|
| glm | 18317 | command-code (`cc_proxy.py`; User-Agent override for Cloudflare 1010) | `z-ai/glm-5.3-flash` |
| glm-eval | 18318 | same, thinking disabled, +4096 max_tokens (judge mode) | – |
| gemini | 18320 | antigravity OCI and PHX, round-robin, 429/5xx backoff | `gemini-3.8-flash-high` |
| spark | 18321 | opencode-go Responses API (chat→responses translation, `x-opencode-session`) | `muse-spark-1.3-contributor` |
| astra | 8317 | existing codex-local endpoint (not started here) | `gpt-6-astra` (reviewer role and judge) |

## Commands

```bash
I=/home/ikkipipi/openalice/.agents/skills/ideascientist/scripts/ideascientist.sh
$I status                     # bridges, astra, running runs/judges
$I bridges                    # start missing bridges (idempotent; setsid, logs in $IDEASCIENTIST_HOME/logs)
$I run --out /mnt/samsung_ssd/openalice-data/ideascientist/<topic> \
       --arms gemini,spark -P 6 problems/*.txt
$I list <out>                 # report.md present? reviewed candidates per run
$I judge astra <out>/runs_*/<run>   # rubric judge; writes evaluation.gpt-6-astra/
```

Launch `run` as a tracked background job. It takes 20–150 minutes per run;
wait for the exit instead of polling.

## Writing a problem file

Use the vault record format: the harness and judges expect it.

```
Challenge: Problem statement: <what fails, with the concrete evidence/numbers>. Why it matters: <consequence>.

Problem definition: Formal setting: <objects, objective, constraints>. Inputs: <...>. Outputs: <...>
```

- **Lead with the diagnosed failure.** Give measured numbers and what has
  already been tried, so the gap_finder does not re-propose it.
- **Keep it 300–450 words.** The examples are in
  `$IDEASCIENTIST_HOME/lea91q/problems/`.
- **The text goes to external LLM providers.** Never include credentials,
  account data, paid-dataset content or live positions. Describe the method
  and statistics only.

## Outputs per run (`<out>/runs_<arm>/<ts>_<id>/`)

- `outputs/gaps.md`: literature gaps.
- `outputs/candidates.md`: candidate ideas.
- `outputs/scores.md`: astra reviewer verdict for each candidate.
- `outputs/report.md` / `report.json`: final proposal.
- `outputs/papers/`: papers read.
- `logs/summary.json`: turns and tokens.
- `<id>.log` beside the run directory.

The local completion patch reserves 20 turns from the default 100-turn
orchestrator budget: exploration stops after 80 turns, then a surviving
candidate receives a forced report-writer phase capped at 20 tool-loop turns.
These are orchestration/writer budgets, not a cap on all nested API calls.
The patched CLI exposes `--finalization-turns` to change the reserve.

Every normal exit or caught orchestrator error writes `outputs/report.md`
and `outputs/completion.json`. If no candidate survives, or the writer fails,
the report preserves the problem, gaps, candidates, latest review verdicts,
objections and next steps; it does not invent a passing proposal. Completion
status separates `proposal_unvalidated`, `no_surviving_candidate` and
`writer_incomplete`, with source/report hashes. Incomplete proposal JSON is
preserved and never counted as completion. The judge wrapper skips negative
and incomplete completion reports.

For legacy processes that already loaded the old loop, run a separate local
recovery observer; it waits for the owner to exit before writing anything:

```bash
PYTHONPATH=$IDEASCIENTIST_HOME/IdeaScientist-patched \
  $IDEASCIENTIST_HOME/venv/bin/python \
  /home/ikkipipi/openalice/.agents/skills/ideascientist/scripts/completion.py \
  --recover <out> --watch
```

Recovery preserves any existing report and writes a separate
`completion_report.md` in that case. Reproduction source is
`scripts/completion.py` plus `references/openalice-ideascientist.patch`.
SIGKILL/power loss cannot execute an in-process finalizer; recovery must run
after the owner exits for those cases.

## Judging caveats

- **Rubric.** The quality rubric (5 dimensions plus relevance) works without a
  target paper.
- **Novelty is not valid for new problems.** Novelty scores compare against
  vault embeddings. We only encoded a BM25 top-150 subset for the 10 pilot
  targets (CPU, about 1 text/s), so novelty for any other problem compares
  against the wrong neighbours.
  - Do not report it.
  - Or first extend the subset with
    `$IDEASCIENTIST_HOME/build_subset_embeddings.py`, which takes about 1.5 h
    per 1,800 papers.
- **Reference-grounded scoring.** It needs a target paper and truncates the
  proposal at 12,000 characters.
- **Judge.** Use astra. GLM as judge needs the glm-eval bridge and still
  under-parses.

## Gotchas

- **Reader bugs.** Upstream `runner.py` had three swallowed reader bugs (fixed
  in the patched copy and PR #2). Unpatched, `papers_read` is always 0.
- **Model argument.** Always pass `--model`. Upstream sends `model: null`
  without it; this is fixed in the PR.
- **Concurrency.** 10 concurrent runs on Gemini caused 429s before the bridge
  had backoff. Six concurrent runs is comfortable.
- **Model names.** A "/" in a model name nests the evaluation directories. The
  wrapper sanitises this to the last path segment.

## Related

- `literature-study` skill: `scripts/literature_library.py vault-search`
  gives the same vault as fast field-targeted FTS5 (challenge / intuition /
  solution, `--cat` / `--exclude-cat`). Use it first for quick cross-domain
  retrieval, and IdeaScientist when you want full proposals.
- Rebuilding the runtime:
  1. HF dataset `Jerry999/SvalbardIdeaVault` at revision `64ab36be95…`.
  2. Build `idea_vault.db` with `scripts/svalbard_vault_import.py`.
  3. Build `vault_fts.db` with `scripts/svalbard_vault_fts.py`.
  4. Apply `references/openalice-ideascientist.patch` to the pinned clone.
  5. Create a venv with CPU torch and sentence-transformers.
  6. Write `env.sh` as in `references/REPRODUCTION.md`.

## Atlas page

The private Atlas page shows questions, runs, reviewed candidates and the vault papers they cite. It has a tree view and a graph view, and lives at https://claude.ai/artifact/13bkSq2R4uX5AiPp6qNpXq.

To refresh its data:

1. Rebuild the data file:

   ```bash
   cd $IDEASCIENTIST_HOME
   PYTHONPATH=IdeaScientist-patched /home/ikkipipi/openalice/.venv/bin/python build_site_data.py <data.json>
   ```

   A copy of the script is also in `scripts/build_site_data.py`.

2. Republish `data.json` next to the page with the Artifact tool, passing `url`. A shell script cannot republish the page itself.
