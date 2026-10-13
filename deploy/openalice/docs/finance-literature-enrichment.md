# Financial, economics and quantitative literature extension

The QNAP library now supports a source-backed financial extension beside the
Svalbard arXiv corpus. Source collection and the harness integration are in
`scripts/finance_literature/`. Runtime papers, source pages and publication
databases live outside Git.

## Storage and provenance

- Papers: `/mnt/qnap-workstation/literature-library/papers/finance/<source>/<key>/<collection>/`.
- Catalog/database: `/mnt/qnap-workstation/literature-library/external/finance-economics-quant/<collection>/`.
- SSD read replica: `/mnt/samsung_ssd/openalice-data/ideascientist/data/finance-literature/<collection>/`.

Each paper has source metadata and its retrieval disposition. Admitted bodies
have the original PDF, plain/layout text and SHA256 hashes. The collector checks
the PDF signature, minimum extractable body length, first-page title overlap and
available author surnames. Surname checks are not complete author-name audits.
Landing pages and failed requests are retained separately. Direct access denials
are recorded; they do not trigger attempts to bypass an access control.
Public author/institution versions can supply a body while preserving the SSRN
record as a source alias. This is a private research library, not redistribution
or a claim of an open license. Source license and publication terms remain those
of the provider.

The first discovery covers SSRN, NBER, the Federal Reserve FEDS series, BIS and
financial econometrics on an author's university page. It targets factor models,
return prediction, forecast uncertainty, nonstationarity, portfolio construction,
volatility/microstructure, nowcasting and monetary-policy mechanisms. SSRN working
papers and preprints are not treated as peer-reviewed validation of their claims.
Neither PDF checks nor collection membership establish scientific quality.

Cross-source normalized titles are deduplicated in the publication catalog;
original snapshots are retained. Exact matches to the existing Svalbard title
reuse that paper ID and augment its body only in the optional profile. New IDs
are deterministic high integer IDs, disjoint from the existing base range.
Title-only identity is a declared limited deduplication screen, not a DOI-complete
cross-version identity audit.

## IdeaScientist integration

`install.py <collection>` verifies the QNAP publication hash, copies and verifies
the local replica, backs up the runtime corpus module, installs an optional
retrieval adapter and writes a versioned `finance-env-<collection>.sh` profile.
Existing `env.sh` and running processes retain their settings. For a new current
literature run, source this profile and invoke the patched `run_ideation.py`
directly; the older shell wrapper sources its own original environment.
Alternatively, `run.py <local-collection-dir> <problem.txt> <new-output-dir>`
selects this profile explicitly and launches Spark with Astra reviewing, using
32 main turns, an eight-turn writer reserve and eight turns per nested role.

The profile merges the base keyword hits with full-text financial hits, reserving
every fourth rank for a matching financial paper. BM25 values from different
indexes are not compared numerically. Results expose the corpus and rank.
Bibliography and reader lookup resolve the same IDs. Metadata-only records are
cataloged but not inserted into the body-search index; an abstract is never
returned as full text. New papers do not have fabricated results-masked records
or embedding vectors. Embedding novelty scoring is unsupported for this extension.

The extension conservatively fences version availability by collection date.
Publication dates are retained for citation, but an old first-publication date
cannot make a newly captured current PDF admissible to a historical cutoff.
The current-literature profile uses tomorrow's UTC date as its exclusive cutoff.
The original base search's conservative year cutoff remains unchanged. This is
a current ideation resource, not a restored historical-vintage benchmark.

## Commands

`resolve.py <finance.db> <new-discovery-dir>` finds public alternative locations
for metadata-only entries through exact-title OpenAlex matching and selected
author/institution pages. It retains raw discovery responses and candidate URLs;
discovery is not full-text acceptance. Collect its seeds with `--no-discover
--prior-records <previous-collection>/records.json` into a new collection. The
collector canonicalizes markup and UTF-8 decoding artifacts before deduplication.
An optional bibliography review in a seed binds manual title/author corrections
to the exact PDF SHA256, preserving original source snapshots.

```bash
source /home/ikkipipi/openalice/scripts/openalice_python_env.sh
PYTHONPATH=/usr/lib/python3/dist-packages $OPENALICE_PYTHON \
  scripts/finance_literature/collect.py <seeds.json> --collection <new-id>
$OPENALICE_PYTHON scripts/finance_literature/install.py <qnap-collection-dir>
$OPENALICE_PYTHON scripts/finance_literature/search.py <finance.db> 'adaptive context factor prediction'
$OPENALICE_PYTHON scripts/finance_literature/run.py <local-collection-dir> <problem.txt> <new-output-dir>
$OPENALICE_PYTHON -m unittest discover -s scripts/finance_literature -p test_overlay.py
```

The collector refuses an unmounted QNAP path, writes exclusive new snapshots,
uses three network workers, a 25-second request timeout and 32 MiB download cap.
Supervise long batches in a user systemd unit with bounded memory, no additional
swap, CPU quota and wall time. The host venv uses the system BeautifulSoup package
through the explicitly pinned `PYTHONPATH`; the overlay itself is stdlib-only.
