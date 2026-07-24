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


class _PermanentDownloadError(DownloadError):
    """A download failure that must not be retried (e.g. an HTTP 4xx)."""


class AssemblyDownload(NamedTuple):
    """Result of downloading one assembly's requested formats."""

    files: list[Path]
    unavailable: list[str]
    failed: list[str]


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
            f"could not reach the NCBI FTP site for {accession}: {err} "
            "(check your network connection or retry later)",
            accession=accession,
        ) from err
    if resp.ok:
        return candidate, _parse_md5(resp.text)

    # Fallback: list the parent directory and find the accession's subdir.
    parent = candidate.rsplit("/", 2)[0] + "/"
    try:
        listing = session.get(parent)
    except requests.RequestException as err:
        raise DownloadError(
            f"could not reach the NCBI FTP site for {accession}: {err} "
            "(check your network connection or retry later)",
            accession=accession,
        ) from err
    if listing.ok:
        match = re.search(rf'href="({re.escape(accession)}_[^"/]+)/"', listing.text)
        if match:
            dir_url = f"{parent}{match.group(1)}/"
            return dir_url, fetch_md5(session, dir_url)

    # Neither the candidate manifest nor the parent listing yielded a directory.
    # Distinguish a transient server error from a genuinely absent assembly so
    # the message says whether to retry or to check the accession.
    if resp.status_code >= 500 or listing.status_code >= 500:
        raise DownloadError(
            f"NCBI FTP server error resolving {accession} "
            f"(HTTP {resp.status_code}); the server may be busy -- retry later",
            accession=accession,
        )
    raise DownloadError(
        f"no FTP directory for {accession}; it may have been removed or "
        "suppressed at NCBI (verify the accession and version)",
        accession=accession,
    )


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
                    # A 4xx (other than the retriable 408/429) is permanent: the
                    # file is absent or forbidden, so retrying only wastes
                    # attempts and sleeps. 5xx/408/429 fall through to retry.
                    if 400 <= resp.status_code < 500 and resp.status_code not in (
                        408,
                        429,
                    ):
                        raise _PermanentDownloadError(
                            f"{label} unavailable: HTTP {resp.status_code} "
                            "(the file may have been removed or superseded at "
                            "NCBI; verify the accession and --formats)"
                        )
                    last_error = f"HTTP {resp.status_code}"
                    raise DownloadError(last_error)
                total = int(resp.headers.get("Content-Length", 0)) or None
                if progress is not None:
                    task_id = progress.add_task(label, total=total)
                bytes_written = 0
                with open(part, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        bytes_written += len(chunk)
                        if progress is not None:
                            progress.update(task_id, advance=len(chunk))
            # Verify completeness even when md5 is skipped (--ignore): a
            # truncated-but-clean stream would otherwise be saved as success.
            if total is not None and bytes_written != total:
                last_error = (
                    f"incomplete download ({bytes_written} of {total} bytes; "
                    "the connection dropped mid-transfer)"
                )
                raise DownloadError(last_error)
            if expected_md5 is not None:
                actual = md5sum(part)
                if actual != expected_md5:
                    last_error = (
                        f"md5 mismatch (expected {expected_md5}, got {actual}; "
                        "the file was corrupted in transit)"
                    )
                    raise DownloadError(last_error)
            part.replace(target)
            return
        except _PermanentDownloadError:
            # Not retriable: clean up the partial file and surface immediately.
            part.unlink(missing_ok=True)
            raise
        except (requests.RequestException, DownloadError, OSError) as err:
            last_error = str(err)
            part.unlink(missing_ok=True)
            if attempt < max_attempts:
                logging.debug(f"Retry {attempt}/{max_attempts} for {label}: {err}")
                time.sleep(sleep)
        finally:
            if progress is not None and task_id is not None:
                progress.remove_task(task_id)

    raise DownloadError(
        f"failed to download {label} after {max_attempts} attempt(s): "
        f"{last_error} (transient network/server error -- retry later, or "
        "raise --max-attempts / --sleep)"
    )


def download_assembly(
    resolve_session: requests.Session,
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

    Returns an ``AssemblyDownload`` with the written file paths, the requested
    formats that were unavailable (absent from the manifest), and the formats
    that errored. Files from successful formats are kept even if others fail;
    DownloadError is raised only when the assembly yields zero files.
    """
    dir_url, md5s = resolve_dir(
        resolve_session, base_url, asm.accession, asm.assembly_name
    )
    # Derive the file-name stem from the resolved directory (``{accession}_{stem}``)
    # so it is correct even when resolve_dir's fallback found a directory whose
    # NCBI stem differs from our sanitized assembly name.
    stem = dir_url.rstrip("/").rsplit("/", 1)[-1]

    written: list[Path] = []
    unavailable: list[str] = []
    failed: list[str] = []
    for fmt in formats:
        suffix, ext = FORMATS[fmt]
        src = f"{stem}{suffix}"
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

        try:
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
        except DownloadError as err:
            # Keep other formats' files; record this format as failed so the
            # assembly can still be reported as a partial success.
            logging.warning(f"{asm.accession}: {fmt} failed: {err}")
            failed.append(fmt)
            continue
        written.append(target)

    # A resolved assembly that yields zero files is a failure, not a silent
    # success -- otherwise the run exits 0 with an empty metadata row.
    if not written and (failed or unavailable):
        if failed:
            raise DownloadError(
                f"all requested formats failed for {asm.accession}: "
                f"{', '.join(failed)} (see the per-format errors above; "
                "retry later or raise --max-attempts / --sleep)",
                accession=asm.accession,
            )
        raise DownloadError(
            f"no requested formats available for {asm.accession}: "
            f"{', '.join(unavailable)} (this version may be superseded and "
            "retain only metadata; omit the version to get the current "
            "assembly, or request different --formats)",
            accession=asm.accession,
        )

    return AssemblyDownload(written, unavailable, failed)
