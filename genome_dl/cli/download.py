#! /usr/bin/env python3
import logging
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import rich_click as click
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TransferSpeedColumn,
)

import genome_dl
from genome_dl.constants import (
    ASSEMBLY_LEVELS,
    DEFAULT_CPUS,
    DEFAULT_LIMIT,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_PREFIX,
    DEFAULT_SLEEP,
    FORMATS,
    FTP_BASE,
    METADATA_COLUMNS,
    METADATA_SUFFIX,
)
from genome_dl.exceptions import (
    AccessionNotFoundError,
    ApiError,
    DownloadError,
    EmptyResultError,
    GenomeDLError,
    PartialDownloadError,
    TaxonError,
    ValidationError,
)
from genome_dl.providers.datasets import (
    list_taxon_assemblies,
    make_session,
    metadata_row,
    resolve_accessions,
    select_for_input,
    verify_taxon,
)
from genome_dl.providers.ftp import download_assembly
from genome_dl.utils import parse_accession, read_accessions, write_tsv

click.rich_click.USE_RICH_MARKUP = True
click.rich_click.OPTION_GROUPS = {
    "genome-dl": [
        {
            "name": "Input Options (choose one)",
            "options": ["--accession", "--accessions", "--species"],
        },
        {
            "name": "Filter Options",
            "options": [
                "--section",
                "--assembly-level",
                "--formats",
                "--limit",
                "--seed",
            ],
        },
        {
            "name": "Download Options",
            "options": [
                "--max-attempts",
                "--sleep",
                "--force",
                "--ignore",
                "--api-key",
            ],
        },
        {
            "name": "Additional Options",
            "options": [
                "--outdir",
                "--prefix",
                "--cpus",
                "--dry-run",
                "--progress",
                "--silent",
                "--verbose",
                "--version",
                "--help",
            ],
        },
    ]
}


@click.command()
@click.version_option(genome_dl.__version__, "--version", "-V")
@click.option(
    "--accession",
    help="A single NCBI assembly accession to download (e.g. GCF_000005845.2).",
)
@click.option(
    "--accessions",
    help="Path to a file of accessions, one per line.",
)
@click.option(
    "--species",
    help="A species (or any taxon) name to download assemblies for.",
)
@click.option(
    "--section",
    default="refseq",
    show_default=True,
    type=click.Choice(["refseq", "genbank", "all"], case_sensitive=False),
    help="Assembly source to query for --species.",
)
@click.option(
    "--assembly-level",
    default="all",
    show_default=True,
    help="Comma-separated assembly levels for --species "
    "(complete,chromosome,scaffold,contig or all).",
)
@click.option(
    "--formats",
    default="fasta",
    show_default=True,
    help="Comma-separated formats to download "
    "(fasta,genbank,gff,gtf,protein,cds,rna,feature-table,"
    "assembly-report,assembly-stats or all).",
)
@click.option(
    "--limit",
    default=DEFAULT_LIMIT,
    show_default=True,
    type=int,
    help="Max assemblies to download for --species (0 = no limit).",
)
@click.option(
    "--seed",
    default=None,
    type=int,
    help="Random seed for reproducible --species subsetting.",
)
@click.option(
    "-m",
    "--max-attempts",
    default=DEFAULT_MAX_ATTEMPTS,
    show_default=True,
    type=int,
    help="Maximum number of download attempts.",
)
@click.option(
    "-s",
    "--sleep",
    default=DEFAULT_SLEEP,
    show_default=True,
    type=int,
    help="Seconds to sleep between download retries.",
)
@click.option(
    "-F",
    "--force",
    is_flag=True,
    help="Overwrite existing files.",
)
@click.option(
    "-I",
    "--ignore",
    "ignore_md5",
    is_flag=True,
    help="Skip MD5 validation of downloaded files.",
)
@click.option(
    "--api-key",
    default=lambda: os.environ.get("NCBI_API_KEY"),
    help="NCBI API key (defaults to the NCBI_API_KEY environment variable).",
)
@click.option(
    "-o",
    "--outdir",
    default="./",
    show_default=True,
    help="Directory to write downloads to.",
)
@click.option(
    "--prefix",
    default=DEFAULT_PREFIX,
    show_default=True,
    help="Prefix for the metadata TSV file.",
)
@click.option(
    "--cpus",
    default=DEFAULT_CPUS,
    show_default=True,
    type=int,
    help="Number of concurrent downloads.",
)
@click.option("--dry-run", is_flag=True, help="List assemblies without downloading.")
@click.option("--progress", is_flag=True, help="Show per-file download progress.")
@click.option("--silent", is_flag=True, help="Only critical errors will be printed.")
@click.option("--verbose", "-v", is_flag=True, help="Print debug related text.")
@click.help_option("--help", "-h")
def genomedl(
    accession,
    accessions,
    species,
    section,
    assembly_level,
    formats,
    limit,
    seed,
    max_attempts,
    sleep,
    force,
    ignore_md5,
    api_key,
    outdir,
    prefix,
    cpus,
    dry_run,
    progress,
    silent,
    verbose,
):
    """Download genomes from NCBI Datasets."""
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            format="%(message)s",
            handlers=[
                RichHandler(
                    rich_tracebacks=True,
                    console=Console(stderr=True),
                    log_time_format="%Y-%m-%d %H:%M:%S",
                )
            ],
        )
    root_logger.setLevel(
        logging.ERROR if silent else logging.DEBUG if verbose else logging.INFO
    )

    try:
        _run_download(
            accession=accession,
            accessions=accessions,
            species=species,
            section=section.lower(),
            assembly_level=assembly_level,
            formats=formats,
            limit=limit,
            seed=seed,
            max_attempts=max_attempts,
            sleep=sleep,
            force=force,
            ignore_md5=ignore_md5,
            api_key=api_key,
            outdir=outdir,
            prefix=prefix,
            cpus=cpus,
            dry_run=dry_run,
            show_progress=progress,
        )
    except ValidationError as e:
        logging.error(str(e))
        sys.exit(1)
    except TaxonError as e:
        logging.error(f"Taxon error: {e}")
        sys.exit(2)
    except EmptyResultError as e:
        logging.error(str(e))
        sys.exit(2)
    except AccessionNotFoundError as e:
        logging.error(str(e))
        sys.exit(2)
    except PartialDownloadError as e:
        logging.error(str(e))
        sys.exit(3)
    except ApiError as e:
        logging.error(f"API error: {e}")
        sys.exit(1)
    except DownloadError as e:
        logging.error(f"Download error: {e}")
        sys.exit(1)
    except GenomeDLError as e:
        logging.error(f"Error: {e}")
        sys.exit(1)


def _parse_formats(formats: str) -> list[str]:
    """Parse and validate the --formats option into a list of keys."""
    values = [f.strip() for f in formats.split(",") if f.strip()]
    if values == ["all"]:
        return list(FORMATS)
    for value in values:
        if value not in FORMATS:
            raise ValidationError(
                f"unknown format {value!r}; choose from {', '.join(FORMATS)} or all"
            )
    return values


def _parse_levels(assembly_level: str) -> list[str]:
    """Parse and validate the --assembly-level option into a list of keys."""
    values = [level.strip() for level in assembly_level.split(",") if level.strip()]
    if values == ["all"]:
        return ["all"]
    for value in values:
        if value not in ASSEMBLY_LEVELS:
            raise ValidationError(
                f"unknown assembly level {value!r}; choose from "
                f"{', '.join(ASSEMBLY_LEVELS)} or all"
            )
    return values


def _resolve_targets(session, accession, accessions, failures):
    """Resolve accession input(s) into target assemblies, recording failures."""
    if accession:
        tokens = [accession]
    else:
        tokens = read_accessions(accessions)

    parsed = {}
    for token in tokens:
        try:
            base, version = parse_accession(token)
            parsed[token] = (base, version)
        except ValidationError:
            logging.error(f"{token} is not a valid accession")
            failures[token] = "invalid"

    if not parsed:
        return []

    bases = sorted({base for base, _ in parsed.values()})
    resolved = resolve_accessions(session, bases)

    targets = []
    for token, (base, version) in parsed.items():
        asm, action = select_for_input(base, version, resolved.get(base, {}))
        if action == "selected":
            targets.append(asm)
        elif action == "superseded":
            logging.warning(f"{token} is superseded; selecting {asm.accession}")
            targets.append(asm)
        elif action == "suppressed":
            logging.error(f"{token} is suppressed on NCBI")
            failures[token] = "suppressed"
        else:
            logging.error(f"{token} not found")
            failures[token] = "notfound"
    return targets


def _run_download(
    accession,
    accessions,
    species,
    section,
    assembly_level,
    formats,
    limit,
    seed,
    max_attempts,
    sleep,
    force,
    ignore_md5,
    api_key,
    outdir,
    prefix,
    cpus,
    dry_run,
    show_progress,
):
    """Core workflow. Raises GenomeDLError subclasses handled by the CLI."""
    provided = [
        name
        for name, val in (
            ("--accession", accession),
            ("--accessions", accessions),
            ("--species", species),
        )
        if val
    ]
    if len(provided) != 1:
        raise ValidationError(
            "provide exactly one of --accession, --accessions, or --species"
        )

    fmt_list = _parse_formats(formats)
    level_list = _parse_levels(assembly_level)

    session = make_session(max_attempts, api_key)
    outdir = Path(outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    failures: dict[str, str] = {}

    if species:
        taxon = verify_taxon(session, species)
        logging.info(f"Verified taxon: {taxon['name']} (tax_id {taxon['tax_id']})")
        targets = list_taxon_assemblies(session, species, section, level_list)
        logging.info(f"Found {len(targets)} assemblies for {taxon['name']}")
        if limit > 0 and len(targets) > limit:
            targets = random.Random(seed).sample(targets, limit)
            logging.info(f"Randomly selected {len(targets)} assemblies (limit {limit})")
    else:
        targets = _resolve_targets(session, accession, accessions, failures)

    if dry_run:
        for asm in targets:
            print(f"{asm.accession}\t{asm.organism_name}\t{asm.assembly_name}")
        if failures and not targets:
            raise AccessionNotFoundError(
                f"{len(failures)} accession(s) failed: {', '.join(failures)}",
                failed=list(failures),
            )
        if failures:
            raise PartialDownloadError(
                f"{len(failures)} accession(s) failed: {', '.join(failures)}",
                failed=list(failures),
                successful=[a.accession for a in targets],
            )
        return

    successful: list[tuple] = []
    total = len(targets)
    progress = None
    if show_progress and targets:
        progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            console=Console(stderr=True),
        )
        progress.start()

    try:
        with ThreadPoolExecutor(max_workers=cpus) as executor:
            future_to_asm = {
                executor.submit(
                    download_assembly,
                    session,
                    asm,
                    fmt_list,
                    outdir,
                    FTP_BASE,
                    force,
                    ignore_md5,
                    max_attempts,
                    sleep,
                    progress,
                ): asm
                for asm in targets
            }
            for i, future in enumerate(as_completed(future_to_asm), start=1):
                asm = future_to_asm[future]
                try:
                    files = future.result()
                    successful.append((asm, files))
                    logging.info(f"[{i}/{total}] {asm.accession} {asm.organism_name}")
                except DownloadError as e:
                    logging.error(f"[{i}/{total}] {asm.accession} failed: {e}")
                    failures[asm.accession] = "download"
    finally:
        if progress is not None:
            progress.stop()

    if successful:
        rows = [metadata_row(asm, files) for asm, files in successful]
        tsv_path = outdir / f"{prefix}{METADATA_SUFFIX}"
        write_tsv(rows, str(tsv_path), METADATA_COLUMNS)
        logging.info(f"Wrote metadata to {tsv_path}")

    if failures and not successful:
        raise AccessionNotFoundError(
            f"{len(failures)} accession(s) failed: {', '.join(failures)}",
            failed=list(failures),
        )
    if failures:
        raise PartialDownloadError(
            f"downloaded {len(successful)} of {len(successful) + len(failures)}; "
            f"failed: {', '.join(failures)}",
            failed=list(failures),
            successful=[a.accession for a, _ in successful],
        )


def main():
    if len(sys.argv) == 1:
        genomedl(["--help"])
    else:
        genomedl()


if __name__ == "__main__":
    main()
