[![GitHub release (latest by date)](https://img.shields.io/github/v/release/rpetit3/genome-dl)](https://github.com/rpetit3/genome-dl/releases)
[![Anaconda-Server Badge](https://anaconda.org/bioconda/genome-dl/badges/downloads.svg)](https://anaconda.org/bioconda/genome-dl)

# genome-dl

Download genome assemblies from NCBI Datasets.

## Introduction

`genome-dl` resolves and downloads genome assemblies from NCBI. It uses the
[NCBI Datasets v2 REST API](https://www.ncbi.nlm.nih.gov/datasets/docs/v2/api/) for metadata and
resolution (accession versioning, suppression detection, taxonomy verification, and species
listing), then downloads the sequence files directly from the
[NCBI FTP site](https://ftp.ncbi.nlm.nih.gov/genomes), where they are already gzip-compressed and
md5-verifiable.

`genome-dl` was written to be a drop-in replacement for `ncbi-genome-download` in
[Bactopia](https://bactopia.github.io/), and mirrors the structure of
[fastq-dl](https://github.com/rpetit3/fastq-dl).

## Installation

### Bioconda

`genome-dl` is available from [Bioconda](https://bioconda.github.io/), and I highly recommend you
go this route for installation, as it will handle dependencies as well.

```bash
conda create -n genome-dl -c conda-forge -c bioconda genome-dl
conda activate genome-dl
genome-dl --help
```

### PyPi

`genome-dl` is also available from [PyPi](https://pypi.org/project/genome-dl/), so you can use
`pip` to install it.

```bash
pip install genome-dl
genome-dl --version
genome-dl --help
```

### From Source

You can also install `genome-dl` from source using [Poetry](https://python-poetry.org/).

```bash
git clone https://github.com/rpetit3/genome-dl.git
cd genome-dl
poetry install
poetry run genome-dl --help
```

## Usage

```bash
genome-dl --help

 Usage: genome-dl [OPTIONS]

 Download genomes from NCBI Datasets.

╭─ Input Options (choose one) ─────────────────────────────────────────────────╮
│ --accession   TEXT  A single NCBI assembly accession to download (e.g.       │
│                     GCF_000005845.2).                                        │
│ --accessions  TEXT  Path to a file of accessions, one per line.              │
│ --species     TEXT  A species (or any taxon) name to download assemblies     │
│                     for.                                                     │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Filter Options ─────────────────────────────────────────────────────────────╮
│ --section         [refseq|genbank|all]  Assembly source to query for         │
│                                         --species. [default: refseq]         │
│ --assembly-level  TEXT                  Comma-separated assembly levels for  │
│                                         --species                            │
│                                         (complete,chromosome,scaffold,contig │
│                                         or all). [default: all]              │
│ --formats         TEXT                  Comma-separated formats to download  │
│                                         (fasta,genbank,wgs,gff,gtf,protein,g │
│                                         enpept,cds,translated-cds,rna,featur │
│                                         e-table,assembly-report,assembly-sta │
│                                         ts or all). [default: fasta]         │
│ --limit           INTEGER RANGE [x>=0]  Download the first N assemblies for  │
│                                         --species (NCBI relevance order,     │
│                                         reference first; 0 = no limit).      │
│                                         [default: 10]                        │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Download Options ───────────────────────────────────────────────────────────╮
│ --max-attempts    -m  INTEGER RANGE [x>=1]  Maximum number of download       │
│                                             attempts. [default: 3]           │
│ --sleep           -s  INTEGER RANGE [x>=0]  Seconds to sleep between         │
│                                             download retries. [default: 10]  │
│ --force           -F                        Overwrite existing files.        │
│ --ignore          -I                        Skip MD5 validation of           │
│                                             downloaded files.                │
│ --allow-outdated                            Download an explicitly requested │
│                                             outdated (superseded) accession  │
│                                             version instead of erroring.     │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Additional Options ─────────────────────────────────────────────────────────╮
│ --outdir    -o  TEXT                  Directory to write downloads to.       │
│                                       [default: ./]                          │
│ --prefix        TEXT                  Prefix for the metadata TSV file.      │
│                                       [default: genome-dl]                   │
│ --cpus          INTEGER RANGE [x>=1]  Number of concurrent FTP downloads     │
│                                       (values above 16 may strain NCBI).     │
│                                       [default: 3]                           │
│ --dry-run                             List assemblies without downloading.   │
│ --progress                            Show per-file download progress.       │
│ --json                                Emit the run report as compact JSON to │
│                                       stdout for piping into other tools.    │
│ --silent                              Only critical errors will be printed.  │
│ --verbose   -v                        Print debug related text.              │
│ --version   -V                        Show the version and exit.             │
│ --help      -h                        Show this message and exit.            │
╰──────────────────────────────────────────────────────────────────────────────╯
```

`genome-dl` requires exactly one of `--accession`, `--accessions`, or `--species` as input.
Providing none, or more than one, is an error.

### --accession

A single NCBI assembly accession (e.g. `GCF_000005845.2` or `GCA_000005845.2`).

- A versionless accession (e.g. `GCF_000005845`) resolves to the current version.
- An explicit version that is still current is downloaded as requested.
- An explicit version that is outdated (a newer version supersedes it) is refused by
  default with an error naming the current version. Omit the version to fetch the
  current one, or pass `--allow-outdated` to download the exact version requested (a
  warning notes that a newer version exists).
- If the requested accession is suppressed on NCBI, the run fails.

### --accessions

A path to a file of accessions, one per line. Blank lines and lines beginning with `#` are
ignored. Each accession is resolved and downloaded following the same rules as `--accession`.

### --species

A species (or any taxon) name, verified against NCBI Taxonomy, to download assemblies for. Use
`--section`, `--assembly-level`, and `--limit` to control which and how many assemblies
are selected.

### --section

The assembly source to query for `--species`: `refseq` (default), `genbank`, or `all`.

### --assembly-level

A comma-separated list of assembly levels to include for `--species`: any of `complete`,
`chromosome`, `scaffold`, `contig`, or `all` (default `all`).

### --formats

A comma-separated list of file formats to download (default `fasta`). Use `all` to download every
format. Available formats and their output extensions:

| Format            | Output extension              |
|-------------------|-------------------------------|
| `fasta`           | `.fna.gz`                     |
| `genbank`         | `.gbff.gz`                    |
| `wgs`             | `.wgsmaster.gbff.gz`          |
| `gff`             | `.gff.gz`                     |
| `gtf`             | `.gtf.gz`                     |
| `protein`         | `.faa.gz`                     |
| `genpept`         | `.gpff.gz`                    |
| `cds`             | `.cds.fna.gz`                 |
| `translated-cds`  | `.translated_cds.faa.gz`      |
| `rna`             | `.rna.fna.gz`                 |
| `feature-table`   | `.feature_table.txt.gz`       |
| `assembly-report` | `.assembly_report.txt`        |
| `assembly-stats`  | `.assembly_stats.txt`         |

Not every format is available for every assembly; formats that do not exist for an assembly are
skipped and reported.

### --limit

For `--species`, `--limit` sets how many assemblies to download (default `10`; `0` means no
limit). The first N assemblies in NCBI's default relevance order are taken, which ranks the
reference/representative genome first. For a fully reproducible, explicit set of assemblies, pass
`--accessions` with a list instead.

### --ignore

Skip MD5 validation of downloaded files. The files are still downloaded and their availability is
still checked; only the checksum verification is skipped.

### NCBI API key

An NCBI API key is read from the `NCBI_API_KEY` environment variable (matching NCBI's own
convention), which raises the Datasets API rate limit from 5 to 10 requests/second. There is no
`--api-key` flag; export the variable instead:

```bash
export NCBI_API_KEY=your_key_here
genome-dl --species "Escherichia coli" -o outdir
```

## Output Files

Downloaded assembly files are written flat as `{ACCESSION}.{EXT}` (e.g. `GCF_000005845.2.fna.gz`),
alongside the run report files below.

| Filename                 | Description                                                                    |
|--------------------------|--------------------------------------------------------------------------------|
| `{ACCESSION}.{EXT}`      | The downloaded assembly file(s), one per requested format                      |
| `{PREFIX}-metadata.tsv`  | Tab-delimited metadata for each downloaded assembly                            |
| `{PREFIX}-summary.txt`   | Human-readable run summary (version, parameters, and results)                  |
| `{PREFIX}.json`          | Machine-readable run report (parameters, results, and per-assembly metadata)   |

`{PREFIX}` defaults to `genome-dl` and is set with `--prefix`.

### Example `{PREFIX}-metadata.tsv`

The metadata TSV (and the `assemblies` entries in the JSON report) contain the following columns,
extracted from the NCBI Datasets assembly report:

| Column                  | Description                                             |
|-------------------------|---------------------------------------------------------|
| `accession`             | The resolved assembly accession                         |
| `source_database`       | The source database (RefSeq or GenBank)                 |
| `assembly_name`         | The assembly name                                       |
| `assembly_level`        | The assembly level (complete, chromosome, etc.)         |
| `assembly_status`       | The assembly status                                     |
| `organism_name`         | The organism name                                       |
| `tax_id`                | The NCBI Taxonomy ID                                    |
| `strain`                | The strain                                              |
| `biosample`             | The BioSample accession                                 |
| `bioproject`            | The BioProject accession                                |
| `submitter`             | The submitter                                           |
| `release_date`          | The release date                                        |
| `refseq_category`       | The RefSeq category                                     |
| `paired_accession`      | The paired GenBank/RefSeq accession                     |
| `total_sequence_length` | The total sequence length                               |
| `number_of_contigs`     | The number of contigs                                   |
| `contig_n50`            | The contig N50                                          |
| `gc_percent`            | The GC percent                                          |
| `files`                 | The downloaded files for the assembly                   |

## Example Usage

### Download a single assembly

```bash
genome-dl --accession GCF_000005845.2 --formats fasta,gff -o outdir
```

```
INFO  Resolved GCF_000005845.2 to GCF_000005845.2 Escherichia coli str. K-12 substr. MG1655
INFO  Downloading 2 file formats for GCF_000005845.2 to outdir
INFO  [1/1] GCF_000005845.2 Escherichia coli str. K-12 substr. MG1655 (2 files)
INFO  Wrote metadata to outdir/genome-dl-metadata.tsv
INFO  Wrote run summary to outdir/genome-dl-summary.txt
INFO  Wrote JSON report to outdir/genome-dl.json
```

The above command downloads the FASTA and GFF for the latest version of `GCF_000005845.2` into
`outdir/`, producing `GCF_000005845.2.fna.gz` and `GCF_000005845.2.gff.gz` along with the run
report files.

### Download a file of accessions

```bash
genome-dl --accessions accessions.txt -o outdir
```

Each accession in `accessions.txt` (one per line, `#` comments and blank lines ignored) is resolved
and downloaded.

### Download assemblies for a species

```bash
genome-dl --species "Escherichia coli" --limit 5 -o outdir
```

The species name is verified against NCBI Taxonomy, then the first 5 RefSeq assemblies (NCBI
relevance order, reference genome first) are downloaded.

### Pipe the run report as JSON

Pass `--json` to also print the run report as compact single-line JSON to stdout (logs stay on
stderr), for piping into other tools:

```bash
genome-dl --accession GCF_000005845.2 --json | jq '.assemblies[].accession'
```

## Exit Codes

| Code | Meaning                                                            |
|------|-------------------------------------------------------------------|
| `0`  | Success                                                           |
| `1`  | Validation / API / download error                                 |
| `2`  | Not found / empty result / unrecognized taxon                     |
| `3`  | Partial download (some accessions succeeded, some failed)         |

## Citation

If you use this tool, please cite the following:

_Petit III RA [genome-dl: Download genomes from NCBI Datasets](https://github.com/rpetit3/genome-dl) (GitHub)_

## Disclaimer

_AI tools were used in the development of this project._
