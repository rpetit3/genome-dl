[![GitHub release (latest by date)](https://img.shields.io/github/v/release/rpetit3/genome-dl)](https://github.com/rpetit3/genome-dl/releases)
[![Anaconda-Server Badge](https://anaconda.org/bioconda/genome-dl/badges/downloads.svg)](https://anaconda.org/bioconda/genome-dl)

# genome-dl

Download genome assemblies from NCBI Datasets.

## Introduction

`genome-dl` takes an accession (RefSeq or GenBank), accessions, or a species name to download
associated files from [NCBI Datasets](https://www.ncbi.nlm.nih.gov/datasets/). First, it queries
the [NCBI Datasets v2 REST API](https://www.ncbi.nlm.nih.gov/datasets/docs/v2/api/) for metadata,
then from there it downloads files directly from the [NCBI FTP site](https://ftp.ncbi.nlm.nih.gov/genomes)

## Installation

### Bioconda

`genome-dl` is available from [Bioconda](https://bioconda.github.io/). I personally will be using
this installation method, and recommend you go this route as well.

```bash
conda create -n genome-dl -c conda-forge -c bioconda genome-dl
conda activate genome-dl
genome-dl --version
genome-dl --help
```

### PyPi

`genome-dl` is also available from [PyPi](https://pypi.org/project/genome-dl/). Being pure Python,
this method should be just as easy as `conda` using `pip` instead.

```bash
pip install genome-dl
genome-dl --version
genome-dl --help
```

### From Source

Finally, you can also install `genome-dl` from source using [Poetry](https://python-poetry.org/).

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
These cannot be used in combination of one another.

### `--accession`

A single NCBI assembly accession (e.g. `GCF_000005845` or `GCA_000005845.2`).

A quick note, NCBI uses versioning for their assembly accessions and `genome-dl` resolves them
according to the following rules:

- A version-less accession (e.g. `GCF_000005845`) will be resolved to the latest version (e.g. `GCF_000005845.2`)
- An explicit version (e.g. `GCF_000005845.2`) that is still the latest version, will be downloaded
- An explicit version (e.g. `GCF_000005845.1`) that is outdated (it's not the latest version) will by default be refused unless `--allow-outdated` is passed.
- If the requested accession is suppressed on NCBI, the run will fail with and error message and you will need to investigate what to do next

**NOTE:** I tend to always use version-less accessions to fetch the latest version.

### `--accessions`

A path to a file of accessions, one per line. Blank lines and lines beginning with `#` are
ignored. Each accession is resolved and downloaded following the same rules as `--accession`.

Honestly, if you are using a file of accessions, I would recommend using version-less
accessions.

### `--species`

A species (or any taxon) name, verified against NCBI Taxonomy, to download assemblies for. Use
`--section`, `--assembly-level`, and `--limit` to control which and how many assemblies
are selected.

### `--section`

The assembly source to query for `--species`: `refseq` (default), `genbank`, or `all`.

### `--assembly-level`

A comma-separated list of assembly levels to include for `--species`: any of `complete`,
`chromosome`, `scaffold`, `contig`, or `all` (default `all`).

### `--limit`

For `--species`, `--limit` sets how many accessions to download requested files from. When set
(the default is `10`), only the first `N` assemblies returned by our API query will be downloaded.

If you want to download all assemblies for a species, set `--limit 0`.

**NOTE:** For a fully reproducible, explicit set of assemblies, pass `--accessions` with a
list instead. Overtime the first `N` assemblies returned by the API is not guaranteed to be the
same.

### `--formats`

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

Not every format is available for every assembly. If a format does not exist for an assembly,
it will be skipped and reported.

### `--ignore`

Skip MD5 validation of downloaded files.

### NCBI API key

`genome-dl` has built in request limits to play nicely with NCBI's servers. The default for
non-authenticated requests is 5 requests per second (rps). If you find that is too slow, or
you are running many things in parallel, consider setting up an NCBI API key in increase usage
limits to 10 rps.`

If you do have an NCBI API key, `genome-dl` reads it from the `NCBI_API_KEY` environment
variable to match NCBI's convention.

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

The metadata TSV (and the `assemblies` entries in the JSON report) will typically contain the
following columns, extracted from the NCBI Datasets assembly report:

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

**NOTE:** There may be additional columns in the metadata TSV depending on what was provided
at submission time.

## Example Usage

### Download a single assembly

```bash
genome-dl --accession GCF_000005845 --formats fasta,gff -o outdir
INFO  Resolved GCF_000005845 to GCF_000005845.2 Escherichia coli str. K-12 substr. MG1655
INFO  Downloading 2 file formats for GCF_000005845.2 to outdir
INFO  [1/1] GCF_000005845.2 Escherichia coli str. K-12 substr. MG1655 (2 files)
INFO  Wrote metadata to outdir/genome-dl-metadata.tsv
INFO  Wrote run summary to outdir/genome-dl-summary.txt
INFO  Wrote JSON report to outdir/genome-dl.json
```

The above command will download the FASTA and GFF for the latest version of `GCF_000005845` into
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

The species name is verified against NCBI Taxonomy, then the first 5 RefSeq assemblies returned
by NCBI are downloaded.

### Pipe the run report as JSON

If you need to use this as part of some analysis chain, you can pass `--json` to print all
STDOUT in JSON format. It has the same contents as the JSON output file, but is compacted
into a single line.

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

## Naming

Not much to say here, I already had [fastq-dl](https://github.com/rpetit3/fastq-dl) so why not
`genome-dl`?

## Citation

If you use this tool, please cite the following:

_Petit III RA [genome-dl: Download genomes from NCBI Datasets](https://github.com/rpetit3/genome-dl) (GitHub)_

## Disclaimer

_I used AI tools to assist in developing `genome-dl`. Haha, there was a lot of back and forth.
I also wanted to use it as an opportunity to test out [oh-my-pi](https://github.com/can1357/oh-my-pi). Verdict: I like it!_

Also, I should mention, I plan to mostly use `genome-dl` indirectly through [Bactopia](https://bactopia.io). So, there is a good chance I might have missed somethings by basing some design decisions on my
expected usage. However, don't let that stop you from making suggestions!
