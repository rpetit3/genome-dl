"""Integration tests that hit the live NCBI Datasets API and FTP site.

Deselected by default; run with ``pytest -m integration``.
"""

import gzip

import pytest

from genome_dl.exceptions import EmptyResultError, TaxonError
from genome_dl.providers.datasets import (
    list_taxon_assemblies,
    make_session,
    metadata_row,
    resolve_accessions,
    select_for_input,
    verify_taxon,
)
from genome_dl.providers.ftp import download_assembly

pytestmark = pytest.mark.integration


@pytest.fixture
def session():
    return make_session(5, None)


def test_current_accession_downloads(session, tmp_path):
    resolved = resolve_accessions(session, ["GCF_000005845"])
    asm, action = select_for_input("GCF_000005845", 2, resolved["GCF_000005845"])
    assert action == "selected"
    written, _, _ = download_assembly(
        session,
        make_session(5, None, retries=False),
        asm,
        ["fasta"],
        tmp_path,
        "https://ftp.ncbi.nlm.nih.gov/genomes",
        force=False,
        ignore_md5=False,
        max_attempts=5,
        sleep=1,
    )
    path = written[0]
    assert path.name == "GCF_000005845.2.fna.gz"
    with gzip.open(path) as fh:
        assert fh.read(1) == b">"


def test_explicit_previous_version_policy(session):
    # F2: an explicit outdated pin is refused by default; allow_outdated honors
    # the exact version.
    resolved = resolve_accessions(session, ["GCF_014058445"])
    _, action = select_for_input("GCF_014058445", 1, resolved["GCF_014058445"])
    assert action == "stale"
    asm, action = select_for_input(
        "GCF_014058445", 1, resolved["GCF_014058445"], allow_outdated=True
    )
    assert action == "outdated"
    assert asm.accession == "GCF_014058445.1"


def test_text_formats_download(session, tmp_path):
    # F1 regression: NCBI transfer-gzips plain-text formats, so the download
    # session must request identity encoding or the completeness check trips on
    # every attempt. ignore_md5=False means success also proves md5 integrity.
    resolved = resolve_accessions(session, ["GCF_000005845"])
    asm, _ = select_for_input("GCF_000005845", 2, resolved["GCF_000005845"])
    written, _, failed = download_assembly(
        session,
        make_session(5, None, retries=False, identity_encoding=True),
        asm,
        ["assembly-report", "assembly-stats"],
        tmp_path,
        "https://ftp.ncbi.nlm.nih.gov/genomes",
        force=False,
        ignore_md5=False,
        max_attempts=5,
        sleep=1,
    )
    assert not failed
    names = sorted(p.name for p in written)
    assert names == [
        "GCF_000005845.2.assembly_report.txt",
        "GCF_000005845.2.assembly_stats.txt",
    ]
    assert (tmp_path / "GCF_000005845.2.assembly_report.txt").stat().st_size > 0


def test_suppressed_detected(session):
    resolved = resolve_accessions(session, ["GCF_000715355"])
    asm, action = select_for_input("GCF_000715355", 1, resolved["GCF_000715355"])
    assert action == "suppressed"
    assert asm is None


def test_species_listing_filters_by_level(session):
    asms, _ = list_taxon_assemblies(session, "Escherichia coli", "refseq", ["complete"])
    assert len(asms) > 0
    # The level filter must be honored: every returned assembly is complete.
    assert all(
        a.report["assembly_info"]["assembly_level"] == "Complete Genome" for a in asms
    )


def test_bad_species_raises(session):
    with pytest.raises(TaxonError):
        verify_taxon(session, "Notarealspecies xyz")


def test_species_no_assemblies_for_filter(session):
    # Verify EmptyResultError path is reachable for an implausible filter combo.
    with pytest.raises((EmptyResultError, TaxonError)):
        list_taxon_assemblies(
            session, "Homo sapiens neanderthalensis", "refseq", ["complete"]
        )


def test_species_limit_fetches_first_x(session):
    # First-X: fetch only the first N (NCBI default order, reference first) and
    # still report the full population count.
    asms, total = list_taxon_assemblies(
        session, "Escherichia coli", "refseq", ["all"], limit=3
    )
    assert len(asms) == 3
    assert total > len(asms)  # population is far larger than the fetched slice
    assert asms[0].report["assembly_info"].get("refseq_category") == "reference genome"


def test_metadata_captures_isolate(session):
    # GCA_016906955.1 identifies via isolate (no strain); the dynamic column
    # must surface it instead of silently dropping the identifier.
    resolved = resolve_accessions(session, ["GCA_016906955"])
    group = resolved["GCA_016906955"]
    row = metadata_row(group[max(group)], [])
    assert row.get("isolate") == "WHEZ1"
    assert row["strain"] == ""
