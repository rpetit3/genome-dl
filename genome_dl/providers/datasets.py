"""NCBI Datasets v2 REST API provider.

Handles all metadata and resolution work: accession versioning, suppression
detection, taxonomy verification, and species (taxon) assembly listing. No
sequence bytes are downloaded here -- that is the FTP provider's job.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from genome_dl.constants import (
    ACCESSION_BATCH_SIZE,
    ASSEMBLY_LEVELS,
    DATASETS_API,
    DATASETS_RATE_LIMIT,
    DATASETS_RATE_LIMIT_WITH_KEY,
)
from genome_dl.exceptions import ApiError, EmptyResultError, TaxonError

# Backoff (seconds, multiplied by attempt number) between retries of a Datasets
# API request whose response stream was interrupted mid-body.
_STREAM_RETRY_BACKOFF = 0.5


class _RateLimiter:
    """Enforce a minimum interval between calls to respect an rps ceiling.

    Spacing consecutive requests at least ``1 / rps`` seconds apart guarantees
    the request rate never exceeds ``rps`` (no bursts). Thread-safe so the
    ceiling holds even if the session is shared across download workers.
    """

    def __init__(self, rps: float):
        self._min_interval = 1.0 / rps if rps > 0 else 0.0
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def acquire(self) -> None:
        """Block until the next request is allowed under the rps ceiling."""
        if self._min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait = self._next_allowed - now
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
            self._next_allowed = now + self._min_interval


@dataclass
class Assembly:
    """A single NCBI genome assembly and its source metadata."""

    accession: str
    assembly_name: str
    status: str
    source_database: str
    organism_name: str
    tax_id: Optional[int]
    report: dict = field(default_factory=dict, repr=False)


def _assembly_from_report(report: dict) -> Assembly:
    """Build an Assembly from a Datasets dataset_report entry."""
    ai = report.get("assembly_info") or {}
    org = report.get("organism") or {}
    return Assembly(
        accession=report.get("accession", ""),
        assembly_name=ai.get("assembly_name", ""),
        status=ai.get("assembly_status", ""),
        source_database=report.get("source_database", ""),
        organism_name=org.get("organism_name", ""),
        tax_id=org.get("tax_id"),
        report=report,
    )


def metadata_row(asm: Assembly, files: list[Path]) -> dict:
    """Flatten an assembly's report into METADATA_COLUMNS keys for the TSV."""
    report = asm.report
    ai = report.get("assembly_info") or {}
    org = report.get("organism") or {}
    stats = report.get("assembly_stats") or {}
    return {
        "accession": report.get("accession", asm.accession),
        "source_database": report.get("source_database", "").replace(
            "SOURCE_DATABASE_", ""
        ),
        "assembly_name": ai.get("assembly_name", ""),
        "assembly_level": ai.get("assembly_level", ""),
        "assembly_status": ai.get("assembly_status", ""),
        "organism_name": org.get("organism_name", ""),
        "tax_id": org.get("tax_id", ""),
        "strain": (org.get("infraspecific_names") or {}).get("strain", ""),
        "biosample": (ai.get("biosample") or {}).get("accession", ""),
        "bioproject": ai.get("bioproject_accession", ""),
        "submitter": ai.get("submitter", ""),
        "release_date": ai.get("release_date", ""),
        "refseq_category": ai.get("refseq_category", ""),
        "paired_accession": report.get("paired_accession", ""),
        "total_sequence_length": stats.get("total_sequence_length", ""),
        "number_of_contigs": stats.get("number_of_contigs", ""),
        "contig_n50": stats.get("contig_n50", ""),
        "gc_percent": stats.get("gc_percent", ""),
        "files": ";".join(sorted(p.name for p in files)),
    }


def make_session(
    max_attempts: int,
    api_key: Optional[str],
    retries: bool = True,
    rate_limit: bool = True,
    identity_encoding: bool = False,
) -> requests.Session:
    """Create a requests session with retry/backoff and optional API key."""
    session = requests.Session()
    total = max(max_attempts - 1, 0) if retries else 0
    retry = Retry(
        total=total,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "POST"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    if api_key:
        session.headers["api-key"] = api_key
    if identity_encoding:
        # NCBI transfer-gzips plain-text formats (assembly-report/-stats), so
        # requests would decode the body while Content-Length still reports the
        # compressed size -- tripping the completeness check on every attempt.
        # Requesting identity keeps Content-Length aligned with the bytes we
        # write. Harmless for already-gzipped (.gz) formats.
        session.headers["Accept-Encoding"] = "identity"
    if rate_limit:
        # Rate limiting is a Datasets API concern; the FTP download session
        # streams bytes from a host with no rps ceiling, so it opts out.
        rps = DATASETS_RATE_LIMIT_WITH_KEY if api_key else DATASETS_RATE_LIMIT
        session.rate_limiter = _RateLimiter(rps)
    # Attempts for the application-level stream-drop retry in ``_request``.
    session.max_attempts = max_attempts if retries else 1
    return session


def _base_of(accession: str) -> str:
    """Return the accession without its version suffix."""
    return accession.split(".")[0]


def _request(session, method, url, context, **kwargs):
    """Perform an HTTP request, converting failures into ApiError.

    The HTTPAdapter's Retry covers connection failures and retryable status
    codes, but a response interrupted mid-body (ChunkedEncodingError, "Response
    ended prematurely") surfaces only when the non-streamed body is read and is
    not covered by that adapter, so it is retried here.
    """
    limiter = getattr(session, "rate_limiter", None)
    attempts = getattr(session, "max_attempts", 1) or 1
    for attempt in range(1, attempts + 1):
        if limiter is not None:
            limiter.acquire()
        try:
            resp = session.request(method, url, **kwargs)
        except requests.exceptions.ChunkedEncodingError as err:
            if attempt < attempts:
                logging.debug(
                    f"Retry {attempt}/{attempts} for {context} after "
                    f"interrupted response stream: {err}"
                )
                time.sleep(_STREAM_RETRY_BACKOFF * attempt)
                continue
            raise ApiError(f"Datasets API request failed for {context}: {err}") from err
        except requests.RequestException as err:
            raise ApiError(f"Datasets API request failed for {context}: {err}") from err
        if not resp.ok:
            raise ApiError(
                f"Datasets API returned {resp.status_code} for {context}",
                status_code=resp.status_code,
            )
        return resp


def resolve_accessions(
    session: requests.Session, bases: list[str]
) -> dict[str, dict[int, Assembly]]:
    """Resolve accession bases to every known version and its status.

    Uses a single (paginated) POST to the dataset_report endpoint with the
    ``all_assemblies`` filter so that current, previous (replaced), and
    suppressed versions are all returned. Bases with no assembly are simply
    absent from the result.

    Returns:
        Mapping of base accession -> {version_int: Assembly}.
    """
    url = f"{DATASETS_API}/genome/dataset_report"
    grouped: dict[str, dict[int, Assembly]] = {}
    # Chunk bases so a large --accessions file does not produce one oversized
    # POST body that NCBI may reject.
    for start in range(0, len(bases), ACCESSION_BATCH_SIZE):
        batch = bases[start : start + ACCESSION_BATCH_SIZE]
        body = {
            "accessions": batch,
            "filters": {"assembly_version": "all_assemblies"},
            "page_size": 1000,
        }
        page_token = None
        while True:
            payload = dict(body)
            if page_token:
                payload["page_token"] = page_token
            resp = _request(session, "POST", url, "accession report", json=payload)
            data = resp.json()
            for report in data.get("reports", []) or []:
                accession = report.get("accession")
                if not accession:
                    continue
                base = _base_of(accession)
                try:
                    version = int(accession.split(".")[1])
                except (IndexError, ValueError):
                    continue
                grouped.setdefault(base, {})[version] = _assembly_from_report(report)
            page_token = data.get("next_page_token")
            if not page_token:
                break
    return grouped


def select_for_input(
    base: str,
    version: Optional[int],
    versions: dict[int, Assembly],
    allow_outdated: bool = False,
) -> tuple[Optional[Assembly], str]:
    """Decide which assembly to download for one requested accession.

    Returns ``(assembly, action)`` where action is one of ``selected``,
    ``outdated``, ``stale``, ``superseded``, ``suppressed``, ``notfound``.
    """
    if not versions:
        return None, "notfound"

    current = next((a for a in versions.values() if a.status == "current"), None)

    if version is None:
        if current is not None:
            return current, "selected"
        if any(a.status == "suppressed" for a in versions.values()):
            return None, "suppressed"
        highest = versions[max(versions)]
        return highest, "superseded"

    if version not in versions:
        return None, "notfound"

    asm = versions[version]
    if asm.status == "suppressed":
        return None, "suppressed"
    if asm.status == "current":
        return asm, "selected"
    # Explicitly requested a non-current (previous/replaced) version. Honor it
    # only with allow_outdated (the caller then warns a newer version exists);
    # otherwise refuse, so a stale pin is a loud error rather than silent drift.
    if allow_outdated:
        return asm, "outdated"
    return None, "stale"


def verify_taxon(session: requests.Session, name: str) -> dict:
    """Verify a taxon name against NCBI Taxonomy.

    Returns a dict with ``tax_id``, ``rank``, and ``name`` on success.

    Raises:
        TaxonError: If the name is not a recognized NCBI Taxonomy name.
        ApiError: If the API request fails.
    """
    url = f"{DATASETS_API}/taxonomy/taxon/{quote(name, safe='')}/dataset_report"
    resp = _request(session, "GET", url, "taxonomy report")
    data = resp.json()
    reports = data.get("reports") or []
    if not reports:
        raise TaxonError(f"no taxonomy record returned for {name!r}")
    report = reports[0]
    if report.get("errors"):
        raise TaxonError(report["errors"][0].get("reason", f"invalid taxon {name!r}"))
    taxonomy = report.get("taxonomy", {})
    return {
        "tax_id": taxonomy.get("tax_id"),
        "rank": taxonomy.get("rank"),
        "name": (taxonomy.get("current_scientific_name") or {}).get("name", name),
    }


def list_taxon_assemblies(
    session: requests.Session, name: str, source: str, levels: list[str]
) -> list[Assembly]:
    """List all assemblies for a taxon, applying source and level filters.

    Raises:
        EmptyResultError: If the taxon has no assemblies for the filters.
        ApiError: If the API request fails.
    """
    url = f"{DATASETS_API}/genome/taxon/{quote(name, safe='')}/dataset_report"
    params = {"page_size": 1000}
    if source != "all":
        params["filters.assembly_source"] = source
    if levels != ["all"]:
        params["filters.assembly_level"] = [ASSEMBLY_LEVELS[level] for level in levels]

    assemblies: list[Assembly] = []
    page_token = None
    first_page = True
    while True:
        page_params = dict(params)
        if page_token:
            page_params["page_token"] = page_token
        resp = _request(session, "GET", url, "taxon report", params=page_params)
        data = resp.json()
        if first_page and not data.get("total_count"):
            raise EmptyResultError(
                f"no assemblies found for {name!r} with the requested filters"
            )
        first_page = False
        for report in data.get("reports", []) or []:
            if report.get("accession"):
                assemblies.append(_assembly_from_report(report))
        page_token = data.get("next_page_token")
        if not page_token:
            break
    logging.debug(f"Found {len(assemblies)} assemblies for {name!r}")
    return assemblies
