"""Utility functions for genome-dl."""

import csv
import hashlib
import re
from pathlib import Path
from typing import Optional, Union

from genome_dl.exceptions import ValidationError

PathLike = Union[str, Path]

ACCESSION_RE = re.compile(r"^GC[AF]_\d{9}(?:\.(\d+))?$")


def md5sum(path: PathLike) -> Optional[str]:
    """Calculate the MD5 checksum of a file.

    Source: https://stackoverflow.com/a/3431838/5299417

    Args:
        path (PathLike): Input file to calculate the MD5 checksum for.

    Returns:
        str: Calculated MD5 checksum, or None if the file does not exist.
    """
    path = Path(path)
    megabyte = 1_048_576
    buffer_size = 10 * megabyte
    if path.exists():
        hash_md5 = hashlib.md5()
        with open(path, "rb") as fp:
            for chunk in iter(lambda: fp.read(buffer_size), b""):
                hash_md5.update(chunk)

        return hash_md5.hexdigest()
    else:
        return None


def parse_accession(token: str) -> tuple[str, Optional[int]]:
    """Parse and validate an NCBI assembly accession.

    Accepts RefSeq (GCF) or GenBank (GCA) accessions, with or without a version
    suffix (e.g. ``GCF_000005845`` or ``GCF_000005845.2``).

    Args:
        token (str): The accession to parse.

    Returns:
        tuple: ``(base, version)`` where ``base`` is the accession without a
        version (e.g. ``GCF_000005845``) and ``version`` is the integer version
        or ``None`` when unversioned.

    Raises:
        ValidationError: If the token is not a valid accession.
    """
    accession = token.strip().upper()
    match = ACCESSION_RE.match(accession)
    if not match:
        raise ValidationError(f"invalid accession: {token!r}")

    base = accession.split(".")[0]
    version = int(match.group(1)) if match.group(1) else None
    return base, version


def read_accessions(path: PathLike) -> list[str]:
    """Read accessions from a file, one per line.

    Blank lines and lines beginning with ``#`` are ignored.

    Args:
        path (PathLike): Path to the accession list file.

    Returns:
        list[str]: The stripped, non-comment, non-blank lines.
    """
    accessions = []
    with open(path) as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            accessions.append(stripped)
    return accessions


def write_tsv(rows: list[dict], path: str, columns: list[str]) -> None:
    """Write a list of dictionaries to a TSV file with a fixed column order.

    Missing keys in any row are written as empty strings. Extra keys not in
    ``columns`` are ignored.

    Args:
        rows (list[dict]): The rows to write.
        path (str): Output TSV path.
        columns (list[str]): Ordered column names (the header).
    """
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=columns,
            delimiter="\t",
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in columns})
