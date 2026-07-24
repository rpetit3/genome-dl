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

## Deferred / known (raise only if you think they now matter)

- gpff/genpept + `_translated_cds.faa.gz` + wgs format mapping is absent from
  `constants.FORMATS` (the FTP dir does expose `_protein.gpff.gz` and
  `_translated_cds.faa.gz`).
- Large `--species` runs page the full taxon list (retaining a full report dict
  per assembly) before random `--limit` subsetting (~90s / high RSS for big
  taxa). Random sampling needs the full population, but the retained reports are
  heavy.
- Shared `requests.Session` across download threads for FTP dir/md5 resolution
  (safe in practice on NCBI — no cookies/header mutation; also sends the api-key
  header to the FTP host, harmless). Left as-is.
- `_parse_md5` drops space-containing filenames and uses `lstrip("./")` (strips
  chars, not the literal prefix) — harmless for real NCBI names. Nitpick.
- `select_for_input` rare edges: versionless + no-current + any-suppressed is
  reported suppressed even if a downloadable "previous" exists; empty/unknown
  status falls through to "superseded". Low.
- rich-click `use_rich_markup` and poetry `[tool.poetry]` deprecation warnings
  (left as-is).

## Packaging note

Bactopia / Bioconda packaging is decided separately by the maintainer — do not
fold it into a review's scope.
