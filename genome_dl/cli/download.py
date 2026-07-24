#! /usr/bin/env python3
import json
import logging
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import rich_click as click
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TransferSpeedColumn,
)

import genome_dl
from genome_dl.constants import (
    ASSEMBLY_LEVELS,
    FORMATS,
    FTP_BASE,
    JSON_SUFFIX,
    METADATA_COLUMNS,
    METADATA_SUFFIX,
    SUMMARY_SUFFIX,
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
from genome_dl.utils import parse_accession, read_accessions, write_json, write_tsv

# Shared stderr console so log lines and the live progress display coordinate
# instead of clobbering each other.
CONSOLE = Console(stderr=True)

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
                "--json",
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
    default=10,
    show_default=True,
    type=int,
    help="Max assemblies to download for --species (0 = no limit).",
)
@click.option(
    "--seed",
    default=42,
    show_default=True,
    type=int,
    help="Random seed for reproducible --species subsetting.",
)
@click.option(
    "-m",
    "--max-attempts",
    default=3,
    show_default=True,
    type=int,
    help="Maximum number of download attempts.",
)
@click.option(
    "-s",
    "--sleep",
    default=10,
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
    "-o",
    "--outdir",
    default="./",
    show_default=True,
    help="Directory to write downloads to.",
)
@click.option(
    "--prefix",
    default="genome-dl",
    show_default=True,
    help="Prefix for the metadata TSV file.",
)
@click.option(
    "--cpus",
    default=3,
    show_default=True,
    type=int,
    help="Number of concurrent downloads.",
)
@click.option(
    "--json",
    "emit_json",
    is_flag=True,
    help="Emit the run report as compact JSON to stdout for piping into other tools.",
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
    outdir,
    prefix,
    cpus,
    emit_json,
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
                    console=CONSOLE,
                    log_time_format="%Y-%m-%d %H:%M:%S",
                )
            ],
        )
    root_logger.setLevel(
        logging.ERROR if silent else logging.DEBUG if verbose else logging.INFO
    )

    if not verbose:
        logging.getLogger("urllib3").setLevel(logging.ERROR)

    api_key = os.environ.get("NCBI_API_KEY")

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
            emit_json=emit_json,
            show_progress=progress,
        )
    except KeyboardInterrupt:
        logging.warning("Aborted by user.")
        sys.exit(130)
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


def _write_summary(
    path: Path,
    params: list[tuple[str, object]],
    n_success: int,
    failures: dict[str, str],
    run_at: str,
) -> None:
    """Write a run summary (version, parameters, results) for reproducibility."""
    lines = [
        f"genome-dl {genome_dl.__version__}",
        f"Run at: {run_at}",
        "",
        "Parameters:",
    ]
    lines += [f"    --{flag} {value}" for flag, value in params]
    lines += [
        "",
        "Results:",
        f"    Assemblies downloaded: {n_success}",
        f"    Assemblies failed: {len(failures)}",
    ]
    if failures:
        lines.append(f"    Failed: {', '.join(failures)}")
    path.write_text("\n".join(lines) + "\n")


def _assembly_json(asm, files: list) -> dict:
    """Build one assembly's JSON object: metadata_row with files as a list."""
    row = metadata_row(asm, files)
    row["files"] = sorted(p.name for p in files)
    return row


def _build_report(
    params: list[tuple[str, object]],
    assemblies: list[dict],
    failures: dict[str, str],
    dry_run: bool,
    run_at: str,
) -> dict:
    """Build the machine-readable run report (version, params, results, assemblies)."""
    return {
        "genome_dl_version": genome_dl.__version__,
        "run_at": run_at,
        "dry_run": dry_run,
        "parameters": dict(params),
        "results": {
            "downloaded": 0 if dry_run else len(assemblies),
            "failed": len(failures),
            "failures": failures,
        },
        "assemblies": assemblies,
    }


def _emit_json(report: dict) -> None:
    """Print the report to stdout as compact single-line JSON for piping."""
    print(json.dumps(report, separators=(",", ":"), default=str))


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
    seen: set[str] = set()
    for token, (base, version) in parsed.items():
        asm, action = select_for_input(base, version, resolved.get(base, {}))
        if action == "selected":
            logging.info(f"Resolved {token} to {asm.accession} {asm.organism_name}")
        elif action == "superseded":
            logging.warning(f"{token} is superseded; selecting {asm.accession}")
        elif action == "suppressed":
            logging.error(f"{token} is suppressed on NCBI")
            failures[token] = "suppressed"
            continue
        else:
            logging.error(f"{token} not found")
            failures[token] = "notfound"
            continue
        # De-duplicate: distinct tokens can resolve to the same accession
        # (e.g. versioned and unversioned forms), which would otherwise race
        # on the same output file when downloaded concurrently.
        if asm.accession in seen:
            logging.debug(f"{asm.accession} already resolved; skipping duplicate")
            continue
        seen.add(asm.accession)
        targets.append(asm)
    return targets


def _log_asm_result(i: int, total: int, asm, result) -> None:
    """Log one assembly's outcome: files written and formats unavailable."""
    n = len(result.files)
    noun = "file" if n == 1 else "files"
    extra = ""
    if result.unavailable:
        u = len(result.unavailable)
        fnoun = "format" if u == 1 else "formats"
        extra = f", {u} {fnoun} unavailable"
    if result.failed:
        f = len(result.failed)
        fnoun = "format" if f == 1 else "formats"
        extra += f", {f} {fnoun} failed"
    log = logging.warning if n == 0 else logging.info
    log(f"[{i}/{total}] {asm.accession} {asm.organism_name} ({n} {noun}{extra})")


def _execute_downloads(
    session,
    download_session,
    targets,
    fmt_list,
    outdir,
    force,
    ignore_md5,
    max_attempts,
    sleep,
    cpus,
    show_progress,
    failures,
):
    """Download all targets concurrently, returning [(asm, files)] for successes.

    Records per-accession failures in ``failures``. On the first Ctrl-C, queued
    downloads are cancelled and in-flight files are allowed to finish; a second
    Ctrl-C force-quits (leaving any '.part' files behind).
    """
    successful: list[tuple] = []
    total = len(targets)
    progress = None
    if show_progress and targets:
        progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TaskProgressColumn(),
            TransferSpeedColumn(),
            console=CONSOLE,
        )
        progress.start()

    executor = ThreadPoolExecutor(max_workers=cpus)
    try:
        future_to_asm = {
            executor.submit(
                download_assembly,
                session,
                download_session,
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
                result = future.result()
                successful.append((asm, result.files))
                _log_asm_result(i, total, asm, result)
            except DownloadError as e:
                logging.error(f"[{i}/{total}] {asm.accession} failed: {e}")
                failures[asm.accession] = "download"
            except Exception as e:
                logging.error(f"[{i}/{total}] {asm.accession} failed unexpectedly: {e}")
                failures[asm.accession] = "error"
    except KeyboardInterrupt:
        logging.warning(
            "Interrupt received; cancelling queued downloads and waiting for "
            "in-flight files to finish. Press Ctrl-C again to force-quit "
            "(incomplete '.part' files may remain)."
        )
        try:
            executor.shutdown(wait=True, cancel_futures=True)
        except KeyboardInterrupt:
            if progress is not None:
                progress.stop()
            logging.warning("Force-quit requested; exiting now.")
            os._exit(130)
        raise
    finally:
        executor.shutdown(wait=True)
        if progress is not None:
            progress.stop()

    return successful


def _write_run_outputs(
    outdir,
    prefix,
    summary_params,
    successful,
    failures,
    run_at,
    emit_json,
):
    """Write metadata TSV, run summary, and JSON report; optionally emit JSON."""
    if successful:
        rows = [metadata_row(asm, files) for asm, files in successful]
        tsv_path = outdir / f"{prefix}{METADATA_SUFFIX}"
        write_tsv(rows, str(tsv_path), METADATA_COLUMNS)
        logging.info(f"Wrote metadata to {tsv_path}")

    summary_path = outdir / f"{prefix}{SUMMARY_SUFFIX}"
    _write_summary(summary_path, summary_params, len(successful), failures, run_at)
    logging.info(f"Wrote run summary to {summary_path}")

    json_path = outdir / f"{prefix}{JSON_SUFFIX}"
    assemblies = [_assembly_json(asm, files) for asm, files in successful]
    report = _build_report(summary_params, assemblies, failures, False, run_at)
    write_json(report, str(json_path))
    logging.info(f"Wrote JSON report to {json_path}")
    if emit_json:
        _emit_json(report)


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
    emit_json,
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
    if prefix in ("", ".", "..") or prefix != Path(prefix).name:
        raise ValidationError(
            f"--prefix must be a bare filename, not a path: {prefix!r}"
        )

    if dry_run:
        logging.warning(
            "DRY RUN ACTIVE, showing what would be downloaded. "
            "Re-run without '--dry-run' to fetch files."
        )

    session = make_session(max_attempts, api_key)
    download_session = make_session(
        max_attempts, api_key, retries=False, rate_limit=False
    )
    outdir = Path(outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    # Run-start timestamp, shared by the summary and JSON report so both agree.
    run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    summary_params: list[tuple[str, object]] = []
    if species:
        summary_params += [
            ("species", species),
            ("section", section),
            ("assembly-level", assembly_level),
            ("limit", limit),
            ("seed", seed),
        ]
    elif accession:
        summary_params.append(("accession", accession))
    else:
        summary_params.append(("accessions", accessions))
    summary_params += [
        ("formats", formats),
        ("max-attempts", max_attempts),
        ("sleep", sleep),
        ("force", force),
        ("ignore", ignore_md5),
        ("api-key", "****" if api_key else None),
        ("outdir", outdir),
        ("prefix", prefix),
        ("cpus", cpus),
        ("progress", show_progress),
    ]

    failures: dict[str, str] = {}

    if species:
        taxon = verify_taxon(session, species)
        logging.info(f"Verified taxon: {taxon['name']} (tax_id {taxon['tax_id']})")
        targets = list_taxon_assemblies(session, species, section, level_list)
        logging.info(f"Found {len(targets)} assemblies for {taxon['name']}")
        if limit > 0 and len(targets) > limit:
            targets = random.Random(seed).sample(targets, limit)
            logging.info(
                f"Randomly selected {len(targets)} assemblies (--limit {limit} --seed {seed})"
            )
    else:
        targets = _resolve_targets(session, accession, accessions, failures)

    if dry_run:
        assemblies = [_assembly_json(asm, []) for asm in targets]
        if emit_json:
            _emit_json(
                _build_report(summary_params, assemblies, failures, True, run_at)
            )
        else:
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

    if targets:
        n_asm = len(targets)
        n_formats = len(fmt_list)
        which_format = (
            f"'{formats}' file" if n_formats == 1 else f"{n_formats} file formats"
        )
        who = targets[0].accession if n_asm == 1 else f"{n_asm} assemblies"
        logging.info(f"Downloading {which_format} for {who} to {outdir}")

    successful = _execute_downloads(
        session,
        download_session,
        targets,
        fmt_list,
        outdir,
        force,
        ignore_md5,
        max_attempts,
        sleep,
        cpus,
        show_progress,
        failures,
    )

    _write_run_outputs(
        outdir,
        prefix,
        summary_params,
        successful,
        failures,
        run_at,
        emit_json,
    )

    if failures and not successful:
        # Operational failures (transient download errors or unexpected I/O
        # errors) mean the accessions resolved fine, so they are a download
        # error (exit 1), not a "not found" (exit 2).
        if all(reason in ("download", "error") for reason in failures.values()):
            raise DownloadError(
                f"all {len(failures)} download(s) failed: {', '.join(failures)}"
            )
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
