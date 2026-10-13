---
name: finance-literature-enrichment
description: Collect SSRN and institutional finance/economics papers into the QNAP library, publish a verified retrieval extension and attach it to current-literature IdeaScientist runs.
---

# Financial literature enrichment

Read `docs/finance-literature-enrichment.md`. Use the mounted shared QNAP library
and `scripts/finance_literature/`. Keep originals and old snapshots, record denied
requests, use public author/institution versions when available and distinguish
metadata from actual paper bodies. Build SQLite locally, publish closed databases
to QNAP and verify source hashes plus replica readback. Current-literature
profiles are explicit; preserve historical cutoff controls and never fabricate
results-masked records or embedding novelty coverage.
