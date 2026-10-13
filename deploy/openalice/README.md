# OpenAlice workstation deployment kit

This branch (`openalice-workstation`) is the harness as it runs on our workstation.

## Harness changes

It builds on PR #2 (reader lock, body prefetch and model default) and adds the following:

- **`harness/corpus.py`:** when a vault paper has no stored full text, the reader receives the structured idea record instead.
  - The HF Svalbard Idea Vault ships no full text.
- **`harness/runner.py` and `harness/completion.py`:** forced completion.
  - The last 20 of the orchestrator's turns are reserved for a report-writer phase.
  - Every exit writes `outputs/report.md` and `outputs/completion.json`. The status is `proposal_unvalidated`, `no_surviving_candidate` or `writer_incomplete`.
  - A failed run therefore never ends silently without a report.
- **`scripts/run_ideation.py`:** adds `--finalization-turns`.

## Deployment kit

`deploy/openalice/` contains:

- **`skills/ideascientist/`:** an agent skill, plus `scripts/ideascientist.sh` with `status`, `bridges`, `run`, `judge` and `list`.
  - Loopback API bridges:
    - `llm_bridge.py`: chat or Responses mode, round-robin across upstreams, with 429 backoff.
    - `cc_proxy.py`
  - Credentials are read at runtime from the Pi `models.json`. None are stored here.
- **`skills/literature-study/` and `tools/literature_library.py`:** an arXiv library, plus `vault-search`, an FTS5 search over the vault.
- **`tools/svalbard_vault_import.py`:** rebuilds the harness SQLite database from `Jerry999/SvalbardIdeaVault`.
- **`tools/svalbard_vault_fts.py`:** builds the per-field FTS5 index.

Reproduction notes and the 10-problem pilot results are in `skills/ideascientist/references/REPRODUCTION.md`.
