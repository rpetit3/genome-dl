# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-07-24

First stable release. `genome-dl` resolves and downloads genome assemblies from
NCBI, written as a drop-in replacement for `ncbi-genome-download`. Resolution and
metadata come from the **NCBI Datasets v2 REST API** (immune to the
`assembly_summary.txt` column breakage that retired ngd); sequence files are
downloaded directly from the **NCBI FTP site**, where they are already gzipped and
md5-verifiable.

### Added

- **Three ways to select assemblies** (exactly one required): `--accession` for a
  single accession, `--accessions` for a file of accessions (one per line), and
  `--species` for a taxon name.
- **Taxon queries** with `--section {refseq,genbank,all}`, `--assembly-level`
  (`complete,chromosome,scaffold,contig` or `all`), and `--limit` (the first N
  assemblies in NCBI relevance order, reference genome first; `0` for all).
- **13 downloadable formats** via `--formats` (comma-separated, or `all`), each
  written flat as `{ACCESSION}.{ext}`:

  | Format | Output extension |
  |---|---|
  | `fasta` | `.fna.gz` |
  | `genbank` | `.gbff.gz` |
  | `wgs` | `.wgsmaster.gbff.gz` |
  | `gff` | `.gff.gz` |
  | `gtf` | `.gtf.gz` |
  | `protein` | `.faa.gz` |
  | `genpept` | `.gpff.gz` |
  | `cds` | `.cds.fna.gz` |
  | `translated-cds` | `.translated_cds.faa.gz` |
  | `rna` | `.rna.fna.gz` |
  | `feature-table` | `.feature_table.txt.gz` |
  | `assembly-report` | `.assembly_report.txt` |
  | `assembly-stats` | `.assembly_stats.txt` |

- **Version-pin policy.** A versionless accession selects the current version; an
  explicit outdated pin (e.g. `GCF_x.1` when `.2` is current) is refused by
  default with a message naming the current version, and honored exactly with
  `--allow-outdated`. Suppressed versions always error.
- **Integrity checks.** Every download is verified against the FTP
  `md5checksums.txt` manifest and its `Content-Length`; `--ignore` skips md5 but
  still guards against truncated streams. `--force` re-downloads existing files.
- **Concurrent, resilient downloads.** `--cpus` parallel FTP workers with a
  per-file retry loop (`--max-attempts`, `--sleep` backoff). Transient errors
  (5xx, rate-limits, connection drops) are retried; permanent errors (4xx) fail
  fast. Partial successes are kept and reported. Ctrl-C cancels queued work and
  lets in-flight files finish (press again to force-quit).
- **Run outputs.** A metadata TSV (columns adapt to the infraspecific fields
  present in the run), a human-readable run summary, and a machine-readable JSON
  report. `--json` emits the report to stdout for piping; `--dry-run` lists
  targets without downloading.
- **API key support** via the `NCBI_API_KEY` environment variable, which raises
  the Datasets API rate limit from 5 to 10 requests/second. The key is never
  written to output files or attached to FTP traffic.
- **Ergonomics.** `--outdir`/`--prefix` for output location and naming,
  `--progress` for a live progress display, and `--silent`/`--verbose` log
  levels. Case-insensitive and de-duplicated `--formats`/`--assembly-level`.
- **Exit-code contract** for scripting: `0` success, `1` validation / API /
  download error, `2` not found / empty result / unrecognized taxon, `3` partial
  download.

### Requirements

- Python 3.11–3.13.

[1.0.0]: https://github.com/rpetit3/genome-dl/releases/tag/v1.0.0
