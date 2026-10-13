# IdeaScientist reproduction (pilot) — OpenAlice workstation + QNAP

Started 2026-10-11. Status: pilot (10 held-out test targets), IdeaScientist-Base only.

## Pinned inputs
- Code: github.com/jiarui-liu/IdeaScientist @ 82a98a08772eab08d11fd097445afa4a8eaaa5b3 (CC BY-NC 4.0; unmodified,
  clone at QNAP literature-library/external/repos/IdeaScientist).
- Data: HF Jerry999/SvalbardIdeaVault @ 64ab36be959afab06066f8c1e7ea292dba9362e5 (CC-BY-4.0), 33 files sha256-verified,
  QNAP literature-library/external/svalbard-idea-vault (download_manifest.json).
- Vault DB rebuilt by openalice scripts/svalbard_vault_import.py: 2,669,631 papers, 0 title dups.
- Keyword index: upstream `ideascientist.vault.index keyword` (FTS5, 6.3 GB).
- Pilot targets: 10 of 272 test papers, random.Random(20261012) (pilot10/problems/selection.json).

## Runtime
- Backbone + judge: command-code z-ai/glm-5.3-flash via loopback forwarder (cc_proxy.py; UA override for
  Cloudflare, credential injected, usage logged). Harness: port 18317, defaults (temperature 0.7, 128k context
  budget, max_turns 100, max_sub_turns 40). Eval: port 18318 injecting thinking disabled + reasoning_effort low
  and +4096 max_tokens allowance.
- No GPU (3090 driver/library mismatch; user chose API-only).

## Deviations from the paper (all results must carry these)
1. Untrained roles only (trained LoRA adapters not released) -> compare against paper's IdeaScientist-Base rows.
2. Backbone and judge are GLM-5.3-flash, not Qwen3.6-27B; same-model judging, like the paper, but a different family.
3. HF release has no full text, LaTeX, or citations: paper reader sees masked records only (papers_read=0),
   citation F1 skipped (--skip-citations).
4. Record fields reconstructed from flattened prose (challenge = "## Problem" section, intuition parsed from
   "Main idea/Explanation"); the HF corpus lacks the nested record.
5. Novelty comparison sets: BM25 top-150 candidates per target (both cohorts) re-ranked by CPU
   Qwen3-Embedding-0.6B (same checkpoint, document side, normalised); 1,829 papers encoded. Recall bounded by BM25.
6. Judge given +4096 token allowance for residual reasoning; visible-output budgets unchanged.
7. run_ideation.py needs explicit --model (upstream does not fall back to IDEASCIENTIST_MODEL).
8. In-domain novelty and mechanism non-obviousness (compute_novelty_aspects.py) not run yet.

## Pilot benchmark (target pid1, one worker)
wall 2h20m; 164 calls; 2.68M prompt + 0.20M completion tokens; 33 orchestrator tool calls; 16 subagents;
0 parser retries. Eval: 5 judge calls, ~4 min. Remaining 9 targets run 3-concurrent.

## Judge change and human reference arm (2026-10-11, user request)
- Primary judge switched to Pi codex-local gpt-6-astra (127.0.0.1:8317 chat/completions, ~0 reasoning tokens);
  GLM-5.3-flash judgments kept in evaluation.glm-5.3-flash/ for pid1 only. Results per judge in evaluation.<model>/.
- Human reference arm (pilot10/human/human_pid<P>): the target paper's own HF proposal_masked written as
  outputs/report.md and scored by the same unmodified evaluator. This is a same-ruler anchor, not a ceiling: the
  rubric is absolute (9-10 = exceptionally strong), and the human text is an LLM-made results-masked summary
  of the paper, not the paper. Reference-grounded is empty for this arm (no report.json; self-comparison).
- Artifact: reference-grounded scoring caps the proposal at TARGET_RECORD_CAP=12000 chars. GLM reports are
  ~24k chars, so trailing fields (comparison_to_sota, proposed_evaluation, falsifiable_predictions,
  limitations) are cut and scored 1. Do not interpret those four subscores for generated runs.
- Length is not controlled: generated pid1 report 24.3k chars vs human 7.7k.

## Upstream reader bugs and v2 patch (2026-10-12)
Commit 82a98a0 never ran the paper reader: every read_paper raised NameError `_reader_lock`
(non-fatal, logged), and build_reader_task swallowed two more errors (`get_stored_full_text(key=...)`
TypeError, undefined `_tok_cap`) so even a successful reader saw only title+abstract.
- v1 runs (runs/ = GLM, runs_gemini_v1_readerbug/, runs_spark_v1_readerbug/): reader dead. GLM-v1 and spark-v1
  scores reflect search-only agents. Gemini-v1 hit the 100-turn orchestrator cap without a report in 9/10.
- v2 (runs_gemini/, runs_spark/): openalice-ideascientist.patch on a local copy (IdeaScientist-patched, via
  PYTHONPATH; QNAP clone stays pristine): define `_reader_lock`, drop `key=`, `_tok_cap = READER_INPUT_TOKEN_CAP`
  (30k, as in the paper), and when no full text exists give the reader the paper's whole results-masked record.
  Reader tokenizer = local Qwen3-Embedding-0.6B tokenizer, HF offline.
- Backbones v2: gemini-3.8-flash-high (antigravity OCI+PHX round-robin) and muse-spark-1.3-contributor
  (opencode Go; Responses API via llm_bridge.py translation, stable x-opencode-session per conversation).
  Reviewer role -> gpt-6-astra (IDEASCIENTIST_ROLE_MODEL/ROLE_BASE_URL). 10 concurrent. Bridge retries 429/5xx.
- Evaluation code unpatched (does not call get_stored_full_text); judge gpt-6-astra.

## Pilot results (2026-10-12, judge gpt-6-astra) — see pilot10/summary_astra_20261012.txt
overall = (quality_avg + mean(novelty_all, novelty_cutoff)) / 2; in-domain novelty and non-obviousness not run.
| arm | reports | quality | nov_all | nov_cut | overall | paired Δ vs human |
|---|---|---|---|---|---|---|
| human (masked summary) | 10/10 | 6.14 | 5.30 | 5.40 | 5.75 | - |
| glm-v1 (reader dead) | 10/10 (pid36 off-schema report -> all 1s) | 5.06 | 4.60 | 5.10 | 4.96 | -0.79 (n=10) |
| spark-v1 (reader dead) | 9/10 | 5.89 | 5.33 | 5.22 | 5.58 | -0.22 (n=9) |
| gemini-v1 (reader dead) | 1/10 (100-turn cap) | - | - | - | - | - |
| spark-v2 (patched) | 8/10 (2 hit 100-turn cap) | 5.95 | 6.00 | 6.00 | 5.97 | +0.16 (n=8, 4 wins) |
| gemini-v2 (patched) | 6/10 (4 hit 100-turn cap) | 6.30 | 5.33 | 5.33 | 5.82 | +0.17 (n=6, 2 wins) |
Means exclude failed runs (survivorship). n<=10, judge-human r~0.5 in the paper: differences of a few tenths
are within noise. Wall per run: spark-v2 16-77 min, gemini-v2 18-153 min; median tokens 5.5M / 8.0M
(reader fix ~2-3x tokens vs v1).
