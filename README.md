# genome-dl

Download genomes from NCBI Datasets.

`genome-dl` resolves and downloads genome assemblies from NCBI. It uses the
[NCBI Datasets v2 REST API](https://www.ncbi.nlm.nih.gov/datasets/docs/v2/api/)
for metadata and resolution (accession versioning, suppression detection,
taxonomy verification, and species listing) and downloads sequence files
directly from the NCBI FTP site, where they are already gzipped and
md5-verifiable. It is a drop-in replacement for `ncbi-genome-download` in
[Bactopia](https://bactopia.github.io/).

## Install

```bash
poetry install
```

## Usage

Provide exactly one of `--accession`, `--accessions`, or `--species`.

```bash
# A single accession (latest version is selected automatically)
genome-dl --accession GCF_000005845.2 -o outdir

# A file of accessions, one per line (# comments and blank lines ignored)
genome-dl --accessions accessions.txt -o outdir

# A species (verified against NCBI Taxonomy); default limit is 10
genome-dl --species "Escherichia coli" --limit 5 --seed 1 -o outdir

# Multiple formats at once
genome-dl --accession GCF_000005845.2 --formats fasta,gff,protein -o outdir
```

Downloaded files are written flat as `{ACCESSION}.{EXT}` (e.g.
`GCF_000005845.2.fna.gz`), alongside a `{prefix}-metadata.tsv` and a
machine-readable `{prefix}.json` (run parameters, results, and per-assembly
metadata) describing every downloaded assembly.

Pass `--json` to also print the run report as compact single-line JSON to
stdout (logs stay on stderr), for piping into other tools:

```bash
genome-dl --accession GCF_000005845.2 --json | jq '.assemblies[].accession'
```

### Accession behavior

- The latest version of an accession is always selected.
- If a newer version supersedes the one requested, a warning is logged and the
  newer version is downloaded.
- If the requested accession is suppressed on NCBI, it fails.

### Key options

| Option | Default | Description |
|--------|---------|-------------|
| `--accession` | | A single assembly accession. |
| `--accessions` | | File of accessions, one per line. |
| `--species` | | Taxon name to download assemblies for. |
| `--section` | `refseq` | Assembly source for `--species` (`refseq`, `genbank`, `all`). |
| `--assembly-level` | `all` | Comma-separated levels (`complete`, `chromosome`, `scaffold`, `contig`). |
| `--formats` | `fasta` | Comma-separated formats (`fasta`, `genbank`, `gff`, `gtf`, `protein`, `cds`, `rna`, `feature-table`, `assembly-report`, `assembly-stats`, `all`). |
| `--limit` | `10` | Max assemblies for `--species` (`0` = no limit). |
| `--seed` | `42` | Random seed for reproducible `--species` subsetting. |
| `-o, --outdir` | `./` | Output directory. |
| `--prefix` | `genome-dl` | Prefix for the metadata TSV. |
| `--cpus` | `3` | Concurrent downloads. |
| `-m, --max-attempts` | `3` | Maximum download attempts. |
| `-F, --force` | off | Overwrite existing files. |
| `--dry-run` | off | List assemblies without downloading. |
| `--progress` | off | Show per-file download progress. |
| `--json` | off | Emit the run report as compact JSON to stdout for piping. |

An NCBI API key is read from the `NCBI_API_KEY` environment variable (matching
NCBI's own convention), raising the rate limit from 5 to 10 requests/second.
There is no `--api-key` flag; export the variable instead:

```bash
export NCBI_API_KEY=your_key_here
genome-dl --species "Escherichia coli" -o outdir
```

### Exit codes

- `0` — success
- `1` — validation / API / download error
- `2` — not found / empty result / unrecognized taxon
- `3` — partial download (some accessions succeeded, some failed)

## License

MIT
