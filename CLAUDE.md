# CLAUDE.md - genome-dl Development Guide

## Project Overview

**genome-dl** is a Python CLI tool for downloading genome assemblies from NCBI. It
accepts a single accession, a file of accessions (one per line), or a species name.
It uses the **NCBI Datasets v2 REST API** for all metadata and resolution (accession
versioning, suppression detection, taxonomy verification, species listing) and
downloads sequence files **directly from the NCBI FTP site**, where files are already
gzipped and md5-verifiable. Downloaded files are written flat as `{ACCESSION}.{EXT}`,
alongside a metadata TSV. It is intended to replace `ncbi-genome-download` in Bactopia.

- **Version**: 0.1.0
- **License**: MIT
- **Python**: >=3.10, <3.14
- **Repository**: https://github.com/rpetit3/genome-dl

## Quick Reference

Always check for and use the `genome-dl` conda environment first (it has the
project's dependencies, including `pytest`, `ruff`, and `just`):

```bash
# Activate the project's conda env before running anything
conda activate genome-dl
# If it does not exist, create it, then install deps with poetry
```

With that environment active:

```bash
# Install dependencies
poetry install

# Run tests (unit only, excludes integration)
just test-cov

# Run integration tests (makes real API/FTP calls)
just test-integration

# Format code
just fmt

# Lint code
just lint

# Full check (format + lint)
just check

# Build package
just build
```

## Project Structure

```
genome-dl/
├── genome_dl/                   # Main package
│   ├── __init__.py              # Version from importlib.metadata
│   ├── cli/
│   │   ├── __init__.py
│   │   └── download.py          # CLI entry point (rich-click based)
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── datasets.py          # NCBI Datasets REST: resolution, taxonomy, species
│   │   └── ftp.py               # Direct FTP downloads + md5 verification
│   ├── constants.py             # Shared constants (URLs, formats, columns, defaults)
│   ├── exceptions.py            # Custom exception hierarchy
│   └── utils.py                 # Utilities (md5sum, parse_accession, write_tsv, ...)
├── tests/                       # Test suite
│   ├── conftest.py              # Shared fixtures
│   ├── test_cli.py              # CLI option/exit-code tests
│   ├── test_providers_datasets.py # Datasets provider + resolution logic tests
│   ├── test_providers_ftp.py    # FTP path construction + download tests
│   ├── test_utils.py            # Utility function tests
│   └── test_integration.py      # Real API/FTP integration tests
├── .claude/
│   └── skills/
│       ├── deep-dive-review/     # Adversarial source-grounded review process
│       │   ├── SKILL.md
│       │   └── references/genome-dl-context.md
│       └── update-catalog/
│           ├── SKILL.md             # Skill definition for /update-catalog
│           └── scripts/
│               └── update_catalog.py # AST-based catalog/llms.txt generator
├── catalog.json                 # Machine-readable project metadata (generated)
├── llms.txt                     # AI-discovery document (generated)
├── justfile                     # Task runner recipes
└── pyproject.toml               # Poetry packaging + tooling config
```

## Architecture

genome-dl follows a hybrid design: the **Datasets REST API** does all the thinking,
and the **FTP site** delivers the bytes.

1. **CLI Layer** (`genome_dl/cli/download.py`): rich-click command that parses
   arguments, configures logging, resolves targets, runs downloads concurrently,
   writes the metadata TSV, and maps exceptions to exit codes.

2. **Provider Layer** (`genome_dl/providers/`):
   - `datasets.py` — Datasets v2 REST queries: `resolve_accessions` (versioning +
     suppression via the `all_assemblies` filter), `select_for_input` (latest /
     superseded / suppressed / not-found decision), `verify_taxon`, and
     `list_taxon_assemblies` (species listing with source/level filters).
   - `ftp.py` — constructs the assembly's FTP directory from accession + assembly
     name, verifies via `md5checksums.txt`, and downloads each requested format to
     `{accession}.{ext}` with retries and md5 verification.

3. **Utilities Layer** (`genome_dl/utils.py`): MD5 checksums, accession parsing and
   validation, accession-file reading, and TSV output.

### Data Flow

```
CLI (accession / accessions file / species)
 → parse_accession()        → validate accession format
 → resolve_accessions()     → all versions + status (accession input)
   verify_taxon() + list_taxon_assemblies()  → species input
 → select_for_input()       → pick latest, warn on superseded, fail on suppressed
 → download_assembly()      → FTP download + md5 verify → {accession}.{ext}
 → write_tsv()              → {prefix}-metadata.tsv
```

## Exit Codes

- `0` — success
- `1` — validation / API / download error
- `2` — not found / empty result / unrecognized taxon
- `3` — partial download (some accessions succeeded, some failed)

## Testing

- Unit tests mock HTTP with `responses` and the CLI with `pytest-mock`; they never
  touch the network and enforce ≥70% coverage.
- Integration tests are marked `@pytest.mark.integration` and are deselected by
  default; they make real NCBI Datasets API and FTP requests.
- After changing modules, functions, CLI options, constants, or the exception
  hierarchy, regenerate the context files with the `update-catalog` skill.

## Skills

Agent skills live in `.claude/skills/`; read a skill's `SKILL.md` before using
it. They are also enumerated in the generated `llms.txt` and `catalog.json`.

- **deep-dive-review** — adversarial, source-grounded review process: pairs an
  independent fresh-context reviewer with live verification, reconciles the two,
  and confirms scope before any code change. Use for deep-dive / second-pass
  reviews, audits, or correctness / robustness / thread-safety passes.
- **update-catalog** — regenerate `catalog.json` and `llms.txt` from source via
  the AST-based generator. Run after changing modules, functions, CLI options,
  constants, the exception hierarchy, or the set of skills.
