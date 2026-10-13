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
- **`harness/finance_overlay.py` and `harness/code_overlay.py`:** optional retrieval extensions, loaded by `corpus.py` only when their environment variables are set.
  - `IDEASCIENTIST_FINANCE_DB`: SSRN and institutional finance papers, with full-text readback.
  - `IDEASCIENTIST_CODE_DB` (with `IDEASCIENTIST_CODE_AVAILABILITY_DATE`): GitHub repositories linked from papers. Search and bibliography results gain repository URL, license, revision and README evidence, fenced by capture date for historical cutoffs.
  - Each database is pinned by SHA-256. With neither variable set, the harness behaves as before.

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

- **`skills/ideascientist/scripts/build_site_data.py`:** builds the data for the private Atlas page (questions, runs, reviewed candidates and cited papers).
- **`skills/finance-literature-enrichment/` and `tools/finance_literature/`:** finance-paper collection, the paper→GitHub index (`code_index.py`), and the shared retrieval profile (`retrieval_profile.py`, `retrieve.py`, `install_stack.py`).
- **`skills/ideamaterializer/` and `tools/ideamaterializer/`:** turn an astra-surviving proposal into a reviewed script, then run it as a CPU-, memory- and time-bounded offline experiment.
  - Before generating a script, it queries the same paper and code index and passes the evidence to the generator and the reviewer, saved as `literature.json`.
  - It archives only repository metadata and READMEs. It does not check out, install or run third-party code.
- **`docs/`:** the materializer contract, finance enrichment and the paper-code index.

Databases, paper bodies, READMEs and run artifacts stay on the workstation and are not in Git.

Reproduction notes and the 10-problem pilot results are in `skills/ideascientist/references/REPRODUCTION.md`.
