# Shared paper and implementation retrieval

`scripts/finance_literature/code_index.py` scans all saved QNAP paper versions:
metadata, extracted prose and PDF hyperlinks. It also searches every existing
Svalbard paper abstract and results-masked record for literal GitHub repository
links. Svalbard metadata are not full papers; absence of a link there does not
establish that a paper has no implementation. No new bulk full-text downloads,
repository checkout, dependency installation or third-party execution occurs.

Paper contexts, source-file hashes or record hashes and repository URLs are
retained. The index labels common dependencies, code-availability claims and
other mentions separately. These automated labels do not prove authorship or
official implementation identity. Public GitHub metadata, detected SPDX license,
default-branch revision and README at that revision are captured for a bounded
number of candidates, prioritizing held papers, financial/time-series titles,
then code-availability claims. Unchecked or inaccessible repositories remain
explicit. Recognized software licenses are a screening signal, not a legal audit.

SQLite is built on SSD, closed, copied to QNAP and checked byte-for-byte. The
optional `install_stack.py` profile pins both finance and code indexes, adds
repository evidence to existing IdeaScientist keyword/bibliography results, and
supplies the same profile to Materializer's pre-generation retrieval. Newly
observed repository metadata are fenced by capture date for historical queries.
Original default settings and already-running research processes remain intact.

The launchers on `codex/materializer-paper-code-index-20261013` (`run.py` and
`spark_question.py`) select this profile by default and record its hash. The
original skill shell wrapper still selects its historical environment; source
the new `finance-code-env-<collection>.sh` profile and invoke the patched harness
directly, or use these new launchers. Merely installing an index does not alter
an existing run or silently select a new literature cutoff.

```bash
python scripts/finance_literature/code_index.py search <code.db> 'factor mining' --open-only
python scripts/finance_literature/retrieve.py <retrieval-profile.json> 'adaptive factor windows'
python scripts/finance_literature/install_stack.py <local-finance-collection> <local-code-collection>
```

The retriever uses the IdeaScientist runtime Python; the scanner and Materializer
use the OpenAlice host environment. Network discovery runs with a durable user
systemd supervisor, a request budget and CPU/memory/wall limits. Runtime artifacts,
paper bodies, READMEs, API responses and generated databases stay outside Git.
