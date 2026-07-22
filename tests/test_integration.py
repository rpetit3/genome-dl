"""Integration tests that hit the live NCBI Datasets API and FTP site.

Deselected by default; run with ``pytest -m integration``.
"""

import gzip

import pytest

from genome_dl.exceptions import EmptyResultError, TaxonError
from genome_dl.providers.datasets import (
    list_taxon_assemblies,
    make_session,
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
    written = download_assembly(
        session,
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


def test_superseded_selects_current(session):
    resolved = resolve_accessions(session, ["GCF_014058445"])
    asm, action = select_for_input("GCF_014058445", 1, resolved["GCF_014058445"])
    assert action == "superseded"
    assert asm.accession == "GCF_014058445.2"


def test_suppressed_detected(session):
    resolved = resolve_accessions(session, ["GCF_000715355"])
    asm, action = select_for_input("GCF_000715355", 1, resolved["GCF_000715355"])
    assert action == "suppressed"
    assert asm is None


def test_species_listing_limited(session):
    asms = list_taxon_assemblies(session, "Escherichia coli", "refseq", ["complete"])
    assert len(asms) > 0
    assert all(a.status == "current" for a in asms)


def test_bad_species_raises(session):
    with pytest.raises(TaxonError):
        verify_taxon(session, "Notarealspecies xyz")


def test_species_no_assemblies_for_filter(session):
    # Verify EmptyResultError path is reachable for an implausible filter combo.
    with pytest.raises((EmptyResultError, TaxonError)):
        list_taxon_assemblies(
            session, "Homo sapiens neanderthalensis", "refseq", ["complete"]
        )
