# genome-dl review context (rolling — update after each round)

This is the standing context for deep-dive reviews of genome-dl. Read it before
reviewing; append to the "Review rounds" and "Deferred" sections when you finish
a round so the next reviewer never re-litigates settled findings.

## What genome-dl is

A Python/Poetry CLI that downloads NCBI genome assemblies, written to replace
ncbi-genome-download (ngd) in Bactopia. ngd broke because it parses NCBI's
`assembly_summary.txt` (fixed-column TSV) and NCBI added a `submitter` column
with unescaped tabs (kblin/ncbi-genome-download#237, bactopia/bactopia#674;
closed as unfixable). The official NCBI `datasets` CLI was avoided because it
delivers a single zip bundle.

Design (hybrid): the **Datasets v2 REST API (JSON)** does all resolution and
metadata (immune to the TSV breakage); sequence files are downloaded
individually and in parallel straight from the **NCBI FTP site** (already gzipped
and md5-verifiable), written flat as `{ACCESSION}.{EXT}` plus a metadata TSV and
JSON report. Mirrors fastq-dl's structure. In Bactopia the module is named
`ncbigenomedownload` (see ~/repos/bactopia/bactopia/catalog.json).

- Input: exactly one of `--accession` / `--accessions` (file) / `--species`.
- Exit codes: `0` success, `1` validation/API/download error, `2` not
  found/empty/unrecognized taxon, `3` partial download.
- Layout: `genome_dl/cli/download.py` (CLI + workflow + ThreadPoolExecutor +
  exit codes), `genome_dl/providers/datasets.py` (REST resolution/metadata),
  `genome_dl/providers/ftp.py` (FTP dir resolution + downloads + md5), plus
  `constants.py`, `exceptions.py`, `utils.py`. Tests under `tests/` (unit mock
  HTTP via `responses`; `@pytest.mark.integration` hit live NCBI, deselected by
  default). ruff + pytest with a 70% coverage gate.

## Review rounds (most recent last)

### Round 1 — commit a049530
Three correctness bugs fixed:
1. FTP fallback rebuilt filenames from the re-sanitized assembly name instead of
   the resolved directory URL (silently produced zero files with exit 0).
2. Distinct tokens resolving to the same accession raced on the same
   .part/output file — de-duplicated by accession.
3. All-resolved-but-all-downloads-failed exited 2 ("not found") instead of 1.

### Round 2 — commit 624b19c
Robustness/correctness hardening, all verified against live NCBI:
- **datasets:** multi-level `--assembly-level` was sent comma-joined -> Datasets
  REST API rejects it with HTTP 400; now sent as repeated params (a list value,
  which `requests` encodes as repeated keys). Retry responses dropped mid-body
  (`ChunkedEncodingError`, "Response ended prematurely") in `_request` — the
  HTTPAdapter Retry only covers connect/status, not non-streamed body reads.
  Batch large `--accessions` into 1000-base POSTs. Coalesce null nested JSON
  objects (`.get(k) or {}`). `quote(name, safe="")` for taxon URLs.
- **ftp:** partial success — keep files from formats that succeed when a later
  format fails (new `failed` field on `AssemblyDownload`); an assembly yielding
  zero files is now a failure, not a silent exit-0 success; verify
  `Content-Length` even under `--ignore` to catch truncated streams; convert
  `OSError` to a retriable `DownloadError`.
- **cli:** record unexpected per-assembly errors as failures (exit 1) instead of
  aborting the batch; log failed formats; reject `--prefix` path traversal.

Live facts confirmed this round (reuse instead of re-deriving):
- `assembly_status` values are `current` / `previous` / `suppressed`; the
  `all_assemblies` filter returns every version.
- `md5checksums.txt` DOES include `_assembly_report.txt` and
  `_assembly_stats.txt` (those formats are downloadable).
- The API **omits** absent keys rather than returning `null` (probed across
  suppressed/human/MAG/old-GenBank records) — the null-crash path is defensive,
  not observed.
- `refseq_category` lives under `assembly_info` and IS returned by the POST
  accession endpoint.
- A single dataset_report POST accepts at least 1000 accessions (HTTP 200).
- NCBI parent digit-directory HTML uses bare `href="GCF_..._STEM/"` — the
  fallback regex matches it exactly.
- Multi-value GET filters require repeated params, not comma-joined (400 on
  comma).

### Round 3 — (commit pending)
Two live-confirmed HIGH fixes plus two hardening items, all verified against
live NCBI:
- **F1 (regression from R2): `assembly-report`/`assembly-stats` downloads failed
  100% of the time.** NCBI serves plain `.txt` formats with
  `Content-Encoding: gzip`; `requests.iter_content` decodes them, so
  `bytes_written` (decoded) never equals the compressed `Content-Length`, and the
  R2 completeness check raised "incomplete download" every attempt. Fix: new
  `make_session(..., identity_encoding=True)` sets `Accept-Encoding: identity` on
  the byte-download session so the header matches the bytes written. `.gz`
  formats and `feature-table` (`.txt.gz`) were never affected.
- **F2: explicit version pins are strict by default.** Requesting `GCF_x.1` (a
  `previous` version) used to silently download and mis-name the current `GCF_x.2`
  (data-fidelity bug). Now, by default an explicit outdated pin is a hard error
  (`select_for_input` returns the new `stale` action -> exit 2), with a message
  naming the current version and the `--allow-outdated` escape. Passing
  `--allow-outdated` honors the exact pinned version (`outdated` action) and warns
  a newer one exists. "Give me current" is spelled by omitting the version
  (versionless input auto-selects current, unchanged). The versionless-no-current
  best-effort path (`superseded` -> download highest) is deliberately left as-is.
  Suppressed pins still error regardless of the flag. Chose the boolean
  `--allow-outdated` over a `--version-policy {strict,upgrade,exact}` enum:
  `upgrade` overlaps with versionless syntax and the third value was speculative;
  the enum stays a clean non-breaking refactor if bulk list-upgrading is ever
  requested.
- **L1: FTP traffic no longer carries the api-key.** Three purpose-built
  sessions now: API (key + rate-limit + retries), FTP-resolve (keyless, retries
  for transient 5xx on dir/md5), FTP-download (keyless, no adapter retries — its
  manual loop is authoritative — + identity encoding).
- **L4: added real-executor concurrency + single-Ctrl-C propagation tests** plus
  live integration tests for text-format download (F1) and version-pin (F2).

Live facts confirmed this round:
- **Superseded RefSeq/GenBank versions retain only metadata stubs.** The
  previous-version FTP directory (e.g. `GCF_000005845.1_ASM584v1/`) exists but
  contains only `_assembly_report.txt`, `_assembly_stats.txt`, `assembly_status.txt`
  and `md5checksums.txt` — the `_genomic.fna.gz` and other sequence files are
  removed. So F2 correctly downloads retained formats for a pinned old version and
  fails honestly ("no requested formats available") for removed ones, instead of
  substituting the current sequence. LESSON: verify FILE presence in the manifest,
  not just directory existence.
- NCBI transfer-gzips plain `.txt` (Content-Encoding: gzip, compressed
  Content-Length); `.gz` files are served with no Content-Encoding and matching
  Content-Length. `Accept-Encoding: identity` makes `.txt` sizes align.
- Missing FTP paths return **404** (text/html body), not a 200 error page, so the
  reviewer's "200-error-body saved as data" concern is not reproducible against
  NCBI. NCBI sends `Content-Length` for static files.
- `refseq_category` lives under `assembly_info` on BOTH the POST-accession and
  GET-taxon report shapes — `metadata_row` is correct for both.
- `filters.assembly_source` accepts lowercase `refseq`/`genbank` (the value the
  CLI sends after `--section`.lower()).

## Deferred / known (raise only if you think they now matter)

- gpff/genpept + `_translated_cds.faa.gz` + wgs format mapping is absent from
  `constants.FORMATS` (the FTP dir does expose `_protein.gpff.gz` and
  `_translated_cds.faa.gz`).
- Large `--species` runs page the full taxon list (retaining a full report dict
  per assembly) before random `--limit` subsetting (~90s / high RSS for big
  taxa). Random sampling needs the full population, but the retained reports are
  heavy.
- Both FTP sessions (dir/md5 resolve + byte download) are still shared across
  download threads (safe in practice on NCBI — no cookies/header mutation). The
  api-key leak to the FTP host is FIXED in R3 (L1); only the thread-sharing
  remains, left as-is.
- `_parse_md5` drops space-containing filenames and uses `lstrip("./")` (strips
  chars, not the literal prefix) — harmless for real NCBI names. Nitpick.
- `select_for_input` rare edges: versionless + no-current + any-suppressed is
  reported suppressed even if a downloadable "previous" exists (note: explicit
  outdated pins are strict-by-default as of R3 — error unless `--allow-outdated`);
  empty/unknown status falls through to "superseded". Low.
- rich-click `use_rich_markup` and poetry `[tool.poetry]` deprecation warnings
  (left as-is).

## Packaging note

Bactopia / Bioconda packaging is decided separately by the maintainer — do not
fold it into a review's scope.
