"""Direct FTP download provider for NCBI genome assemblies.

Assemblies are fetched directly from ``ftp.ncbi.nlm.nih.gov/genomes`` where the
files are already gzipped and md5-verifiable. Output files are written flat as
``{accession}.{ext}``.
"""

import logging
import re
import time
from pathlib import Path
from typing import NamedTuple, Optional

import requests

from genome_dl.constants import FORMATS
from genome_dl.exceptions import DownloadError
from genome_dl.providers.datasets import Assembly
from genome_dl.utils import md5sum

CHUNK_SIZE = 1024 * 1024


class AssemblyDownload(NamedTuple):
    """Result of downloading one assembly's requested formats."""

    files: list[Path]
    unavailable: list[str]


def _sanitize(assembly_name: str) -> str:
    """Sanitize an assembly name the way NCBI does for FTP directory names."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", assembly_name)


def assembly_dir_url(base_url: str, accession: str, assembly_name: str) -> str:
    """Construct the FTP directory URL for an assembly.

    e.g. GCF_000005845.2 + ASM584v2 ->
    {base_url}/all/GCF/000/005/845/GCF_000005845.2_ASM584v2/
    """
    prefix = accession[:3]
    digits = accession[4:].split(".")[0]
    d1, d2, d3 = digits[0:3], digits[3:6], digits[6:9]
    san = _sanitize(assembly_name)
    return f"{base_url}/all/{prefix}/{d1}/{d2}/{d3}/{accession}_{san}/"


def resolve_dir(
    session: requests.Session, base_url: str, accession: str, assembly_name: str
) -> tuple[str, dict[str, str]]:
    """Return the FTP directory URL and parsed md5checksums for an assembly.

    Builds the candidate path from the (sanitized) assembly name and confirms
    it by fetching ``md5checksums.txt``, reusing that response as the md5
    manifest. Falls back to listing the parent digit directory and matching
    ``{accession}_*`` if the candidate 404s.
    """
    candidate = assembly_dir_url(base_url, accession, assembly_name)
    try:
        resp = session.get(f"{candidate}md5checksums.txt")
    except requests.RequestException as err:
        raise DownloadError(
            f"could not reach FTP for {accession}: {err}", accession=accession
        ) from err
    if resp.ok:
        return candidate, _parse_md5(resp.text)

    # Fallback: list the parent directory and find the accession's subdir.
    parent = candidate.rsplit("/", 2)[0] + "/"
    try:
        listing = session.get(parent)
    except requests.RequestException as err:
        raise DownloadError(
            f"could not reach FTP for {accession}: {err}", accession=accession
        ) from err
    if listing.ok:
        match = re.search(rf'href="({re.escape(accession)}_[^"/]+)/"', listing.text)
        if match:
            dir_url = f"{parent}{match.group(1)}/"
            return dir_url, fetch_md5(session, dir_url)

    raise DownloadError(f"no FTP directory for {accession}", accession=accession)


def _parse_md5(text: str) -> dict[str, str]:
    """Parse ``md5checksums.txt`` content into {filename: md5}."""
    md5s: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        checksum, name = parts
        md5s[name.lstrip("./")] = checksum
    return md5s


def fetch_md5(session: requests.Session, dir_url: str) -> dict[str, str]:
    """Fetch and parse ``md5checksums.txt`` into {filename: md5}."""
    try:
        resp = session.get(f"{dir_url}md5checksums.txt")
    except requests.RequestException as err:
        raise DownloadError(
            f"could not fetch md5checksums.txt from {dir_url}: {err}"
        ) from err
    if not resp.ok:
        raise DownloadError(f"could not fetch md5checksums.txt from {dir_url}")
    return _parse_md5(resp.text)


def _download_file(
    session: requests.Session,
    url: str,
    target: Path,
    expected_md5: Optional[str],
    max_attempts: int,
    sleep: int,
    progress,
    label: str,
) -> None:
    """Download one file with retries, md5 verification, and atomic rename."""
    part = target.with_suffix(target.suffix + ".part")
    last_error = None
    for attempt in range(1, max_attempts + 1):
        task_id = None
        try:
            with session.get(url, stream=True) as resp:
                if not resp.ok:
                    last_error = f"HTTP {resp.status_code}"
                    raise DownloadError(last_error)
                total = int(resp.headers.get("Content-Length", 0)) or None
                if progress is not None:
                    task_id = progress.add_task(label, total=total)
                with open(part, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        if progress is not None:
                            progress.update(task_id, advance=len(chunk))
            if expected_md5 is not None:
                actual = md5sum(part)
                if actual != expected_md5:
                    last_error = f"md5 mismatch (expected {expected_md5}, got {actual})"
                    raise DownloadError(last_error)
            part.replace(target)
            return
        except (requests.RequestException, DownloadError) as err:
            last_error = str(err)
            part.unlink(missing_ok=True)
            if attempt < max_attempts:
                logging.debug(f"Retry {attempt}/{max_attempts} for {label}: {err}")
                time.sleep(sleep)
        finally:
            if progress is not None and task_id is not None:
                progress.remove_task(task_id)

    raise DownloadError(
        f"failed to download {label}: {last_error}",
    )


def download_assembly(
    session: requests.Session,
    download_session: requests.Session,
    asm: Assembly,
    formats: list[str],
    outdir: Path,
    base_url: str,
    force: bool,
    ignore_md5: bool,
    max_attempts: int,
    sleep: int,
    progress=None,
) -> AssemblyDownload:
    """Download the requested formats for one assembly to ``{accession}.{ext}``.

    Returns an ``AssemblyDownload`` with the written file paths and the
    requested formats that were unavailable. Raises DownloadError on failure.
    """
    dir_url, md5s = resolve_dir(session, base_url, asm.accession, asm.assembly_name)
    san = _sanitize(asm.assembly_name)

    written: list[Path] = []
    unavailable: list[str] = []
    for fmt in formats:
        suffix, ext = FORMATS[fmt]
        src = f"{asm.accession}_{san}{suffix}"
        target = outdir / f"{asm.accession}.{ext}"
        expected = md5s.get(src)
        verify = None if ignore_md5 else expected

        if expected is None:
            unavailable.append(fmt)
            continue

        if (
            target.exists()
            and not force
            and (verify is None or md5sum(target) == verify)
        ):
            logging.debug(f"{target.name} already present; skipping")
            written.append(target)
            continue

        _download_file(
            download_session,
            f"{dir_url}{src}",
            target,
            verify,
            max_attempts,
            sleep,
            progress,
            f"{asm.accession}.{ext}",
        )
        written.append(target)

    return AssemblyDownload(written, unavailable)
