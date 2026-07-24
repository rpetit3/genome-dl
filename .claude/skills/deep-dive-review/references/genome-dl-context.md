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

### Round 4 — (commit pending)
Input-boundary hardening. Prior rounds hardened the API/concurrency/transport
core; this round found the remaining defects all live at the CLI option boundary.
Every finding was reproduced (live or by driving the real code) before fixing;
non-issues were probed and dropped rather than filed.
- **F1 (HIGH): empty `--formats ""` (or `","`) exited 0 having downloaded
  nothing.** `_parse_formats` filtered empty tokens to `[]`; `download_assembly`'s
  loop was skipped; the zero-file guard `if not written and (failed or
  unavailable)` was False, so it returned `AssemblyDownload([],[],[])` — a metadata
  TSV with an empty `files` column and exit 0 (worst case for a Bactopia pipeline).
  Fix: `_parse_formats`/`_parse_levels` now raise `ValidationError` on empty input.
- **F2/F3/F4/F5 (numeric bounds): added `click.IntRange`** — `--max-attempts`
  min 1 (0 made `range(1,1)` empty → every download failed with `"...: None"`),
  `--cpus` min 1 (0 → uncaught `ValueError` from `ThreadPoolExecutor`, created
  before the try → raw traceback), `--sleep` min 0 (negative → `time.sleep(-n)`
  `ValueError` escaped the retry `except` and turned a retryable failure into a
  permanent one), `--limit` min 0 (negative silently aliased to "no limit" and
  downloaded the whole taxon). `--seed` left unbounded (any int is valid).
- **F6 (BOM): `read_accessions` now opens with `encoding="utf-8-sig"`.** An
  Excel/Windows export starting with a UTF-8 BOM dropped its first accession —
  `str.strip()` does not remove `\ufeff`, so `ACCESSION_RE` rejected it; a
  single-accession file falsely exited 2.
- **F7 (outdir): `outdir.mkdir` `OSError` → `ValidationError`** (clean exit 1
  instead of a traceback when `--outdir` names a file or an unwritable path).
- **F8 (non-JSON 200, defensive): `_request` renamed to `_request_json`** and now
  parses the body, raising `ApiError` on a non-JSON 200 (captive-portal/proxy).
  Not reproducible against NCBI (they return proper 404s + JSON) — defensive only.
- Added regression tests: `TestOptionBounds` (7 CLI tests: empty formats/levels,
  cpus/max-attempts/sleep/limit bounds, outdir-is-file), a BOM read_accessions
  test, and a non-JSON-200 `ApiError` test. 96 unit tests pass; coverage 87.85%.

Non-issues probed live and deliberately NOT filed this round (confirmed sound):
- POST `dataset_report` accession pagination terminates cleanly: with 2 versions
  and `page_size=1`, page 3 returns `reports:[]` + `next_page_token: null`, so the
  `resolve_accessions` token loop always ends (no infinite loop from a multi-
  version-per-base page overflow).
- Taxon GET returns `total_count` + `next_page_token`; the first-page-only
  `total_count` empty-check in `list_taxon_assemblies` is correct.
- `resolve_dir` parent-listing fallback regex embeds the versioned accession, so
  it disambiguates versions within a shared digit directory (single match).
- Concurrency/Ctrl-C, TSV/JSON metadata consistency, and `select_for_input`
  branch logic re-reviewed and confirmed sound.

### Round 5 — (commit pending)
A metadata-fidelity + scale spot-check (per R4's convergence guidance), not a
general sweep. An independent `code-reviewer` and live NCBI probes ran
concurrently and converged: **no critical/high bugs; the R1–R4 core is intact.**
Three substantive findings, all fixed, plus a design simplification the user
drove:
- **Scale (was the deferred `--species` memory item): 10–14 GB OOM on large
  taxa — FIXED by redefining `--limit`.** Measured live: 18,080 Salmonella
  RefSeq assemblies retained 283 MB (~21.6 KB deep-size per `Assembly`, the
  `report` dict dominates); *Salmonella enterica* is 648,104 assemblies total →
  ~10–14 GB just to pick `--limit 10`, then OOM. Root design flaw: the old code
  paged the ENTIRE taxon into memory, then `random.Random(seed).sample(...)`.
  Fix: **`--limit` now means "the first N assemblies"** in NCBI's default
  relevance order (reference/representative first — verified: E. coli and
  Salmonella both return the reference genome first). `list_taxon_assemblies`
  stops paginating once it has N (`page_size=min(limit,1000)`) and returns
  `(assemblies, total_count)` so the "Found N; downloading first X" log still
  reports the full population. Smoke test: `--species "Salmonella enterica"
  --limit 2` → **36 MB peak RSS, 2 s**, downloads the reference first. `--limit
  0` still fetches all (unavoidable, and you're then downloading everything).
- **`--seed` REMOVED (breaking, clean cutover).** First-X is deterministic
  within a release; there is no random subset to seed. `--seed` reproducibility
  was always best-effort anyway (it depended on NCBI page order AND a frozen
  population; probed live — the taxon GET order is stable-within-session but not
  accession-sorted and not guaranteed stable across releases). Hard
  reproducibility = pass an explicit `--accessions` list. Considered hash
  bottom-k streaming (order-independent, growth-stable, O(limit)) but first-X is
  simpler and the user chose it; NCBI relevance order gives better defaults than
  a random sample.
- **M2 (metadata fidelity): `strain` column silently dropped isolate/other
  infraspecific identifiers — FIXED.** Live-verified: `GCA_016906955.1`
  (`{isolate: WHEZ1, sex: female}`, no strain) and MAG `GCA_002718135.1`
  (`{isolate: SP346}`). `metadata_row` now emits every non-strain
  `infraspecific_names` key; `_write_run_outputs` computes the column union
  **from the current run only** (no fixed superset — submitters can use
  arbitrary keys) and inserts them after `strain`. `strain` stays a fixed column
  for back-compat. Verified end-to-end: isolate run's TSV gains `isolate`+`sex`
  columns; strain-only runs keep the standard 19.
- **P1 (perf): connection-pool churn at `--cpus > 10` — FIXED.** `make_session`
  takes `pool_maxsize` (default 10); the thread-shared ftp/download sessions get
  `max(cpus, 10)` so urllib3 stops discarding connections above 10 workers.
  `--cpus` stays unbounded (`IntRange(min=1)`) but now warns above
  `CPUS_WARN_THRESHOLD` (16) that many parallel FTP connections strain NCBI —
  `--cpus` is FTP-download concurrency only; the 5/10 rps API ceiling is a
  separate main-thread `_RateLimiter` concern decoupled from it.
- Tests: unit (metadata dynamic keys, first-X early-stop + page_size + total,
  cpus warn/no-warn) and live integration (first-X reference-first, isolate
  metadata). 100 unit pass, coverage 87.7%; 9 integration pass live. Catalog +
  README + llms.txt updated (20 CLI options, `--seed` gone).

Live facts confirmed this round (reuse instead of re-deriving):
- NCBI taxon listing has **no random/shuffle sort**; `sort.field` (POST body /
  GET query) accepts only field names with `ASCENDING`/`DESCENDING`. So a
  1-call uniform random sample is impossible; uniform sampling requires
  enumerating the whole population.
- Default (unsorted) order is a **stable, reference-first relevance ranking**
  (byte-identical on repeat calls within a session; GCA/GCF pairs adjacent when
  `--section all`). `--section refseq` (default) returns GCF only (no pairing).
- `total_count` is returned on the first page, so first-X can report the full
  population size while fetching only N.


## Deferred / known (raise only if you think they now matter)

- gpff/genpept + `_translated_cds.faa.gz` + wgs format mapping is absent from
  `constants.FORMATS` (the FTP dir does expose `_protein.gpff.gz` and
  `_translated_cds.faa.gz`).
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

## Convergence — how many more rounds, and where the value is

Read this before opening a 5th general round. The finding severity has decayed in
the classic signature of convergence:
- R1–R3 findings were **data/correctness/security** (silent zero-file exit-0,
  output-file race, HTTP 400 filter, truncation, text formats 100% broken,
  version-pin mis-naming, api-key leak).
- R4 findings were **mostly input-validation/UX** (numeric bounds, BOM, mkdir/
  JSON guards). The one exception was empty-`--formats`, a real correctness
  landmine (exit-0 with nothing downloaded) wearing a UX costume.

When findings shift from "corrupts/omits output silently" to "ugly error / needs
a bound," the well is nearly dry. **"Done" = a round that returns only nitpicks
and speculative-needs-a-live-probe items and ZERO reproduced correctness bugs.**
R4 was most of the way there; a 5th *general* line-by-line sweep will very likely
return only nitpicks. Do NOT keep running broad sweeps to manufacture findings —
that is exactly how non-existent issues get filed.

Higher-value than another general sweep (do these instead, each narrow):
1. **Metadata-fidelity + scale spot-check.** Run against genuinely weird records —
   MAGs/metagenomes, GenBank-only (`GCA` with no RefSeq), atypical `assembly_name`,
   and a large `--species` run (the deferred full-pagination/RSS item). Field
   omissions and memory blowups hide here, not in code a reviewer can eyeball.
2. **Dogfood the real Bactopia integration and run `just test-integration`**
   against live NCBI. The drop-in-replacement contract is the true acceptance
   test; it catches more than another reviewer would.

Close the ledger, don't re-review it: the Deferred items above are **decisions,
not bugs**. Explicitly accept (or fix) them once rather than re-litigating each
round.

## Next session — dogfooding & error-message hardening (NOT another review)

Reviews are converged (see above). The next session is a different activity:
**use the tool adversarially and polish how it fails.** Reviews answer "does the
code do the wrong thing"; dogfooding answers "does the tool handle the world
badly" — bad inputs, confusing errors, unhelpful exits. A Bactopia user sees
stderr + exit code, not the source, so that surface is the product.

Method: run each scenario, capture `exit code` + stderr, grade every message on
**"does it say what's wrong AND what to do?"** Fix the weak ones (wording + exit
consistency), one regression test per fix. Exit-code contract: 0 ok /
1 validation·API·download / 2 not-found·empty·bad-taxon / 3 partial.

1. **Headline gate — M2 variable-column TSV vs Bactopia's parser.** R5 made the
   metadata TSV column set run-dependent (isolate/sex/... appear only when
   present). Verified it writes correctly, NOT that the `ncbigenomedownload`
   Bactopia module's downstream TSV reader tolerates a variable schema. If it
   hard-codes columns/positions, that breaks the drop-in contract. Verify first.
2. **Adversarial input matrix** (grade the message each time):
   - Accessions: malformed, lowercase, whitespace, wrong prefix, valid-shape but
     nonexistent, versioned/unversioned, suppressed, withdrawn.
   - List files: BOM, CRLF, blank/comment lines, dupes, one bad line among good,
     empty file, not-a-file, huge file.
   - Species/taxon: typos, wrong rank, unicode, empty level×section combos,
     ambiguous names.
   - Filesystem: read-only outdir, missing parent, odd `--prefix`, existing files
     (`--force` vs not).
   - Network/NCBI: offline, DNS fail, 5xx, mid-download drop, 404 FTP dir, md5
     mismatch.
   - Flag combos: `--limit 0` on a huge taxon, `--dry-run --json`, conflicting
     inputs, `--cpus` extremes, `--ignore`.
3. **Exercise R5's new paths as break-targets:** first-X with `limit > total`,
   `limit` crossing page boundaries, `--section all` GCA/GCF pairing under
   `--limit`, empty taxon with early-stop.

Deliverable: a triage list of weak/missing messages → fixes + tests. Then run
`just test-integration` live and dogfood the actual Bactopia module end-to-end.

## Packaging note

Bactopia / Bioconda packaging is decided separately by the maintainer — do not
fold it into a review's scope.
