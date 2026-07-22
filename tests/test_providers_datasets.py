"""Tests for genome_dl.providers.datasets."""

from pathlib import Path

import pytest
import responses

from genome_dl.constants import DATASETS_API
from genome_dl.exceptions import ApiError, EmptyResultError, TaxonError
from genome_dl.providers.datasets import (
    list_taxon_assemblies,
    make_session,
    metadata_row,
    resolve_accessions,
    select_for_input,
    verify_taxon,
)
from tests.conftest import make_assembly, make_report


def versions(*specs):
    """Build a {version: Assembly} map from (version, status) specs."""
    out = {}
    for version, status in specs:
        acc = f"GCF_000005845.{version}"
        out[version] = make_assembly(accession=acc, status=status)
    return out


class TestSelectForInput:
    def test_versionless_current(self):
        v = versions((2, "current"), (1, "previous"))
        asm, action = select_for_input("GCF_000005845", None, v)
        assert action == "selected"
        assert asm.accession == "GCF_000005845.2"

    def test_versionless_only_suppressed(self):
        v = versions((1, "suppressed"))
        asm, action = select_for_input("GCF_000005845", None, v)
        assert action == "suppressed"
        assert asm is None

    def test_versioned_current(self):
        v = versions((2, "current"))
        asm, action = select_for_input("GCF_000005845", 2, v)
        assert action == "selected"
        assert asm.accession == "GCF_000005845.2"

    def test_versioned_previous_selects_current(self):
        v = versions((2, "current"), (1, "previous"))
        asm, action = select_for_input("GCF_000005845", 1, v)
        assert action == "superseded"
        assert asm.accession == "GCF_000005845.2"

    def test_versioned_suppressed(self):
        v = versions((2, "current"), (1, "suppressed"))
        asm, action = select_for_input("GCF_000005845", 1, v)
        assert action == "suppressed"
        assert asm is None

    def test_versioned_missing(self):
        v = versions((2, "current"))
        asm, action = select_for_input("GCF_000005845", 5, v)
        assert action == "notfound"
        assert asm is None

    def test_empty_base(self):
        asm, action = select_for_input("GCF_000005845", 2, {})
        assert action == "notfound"
        assert asm is None


class TestMetadataRow:
    def test_extracts_expected_columns(self):
        asm = make_assembly()
        files = [
            Path("/out/GCF_000005845.2.fna.gz"),
            Path("/out/GCF_000005845.2.gff.gz"),
        ]
        row = metadata_row(asm, files)
        assert row["accession"] == "GCF_000005845.2"
        assert row["source_database"] == "REFSEQ"
        assert row["assembly_name"] == "ASM584v2"
        assert row["organism_name"].startswith("Escherichia coli")
        assert row["tax_id"] == 511145
        assert row["strain"] == "K-12 substr. MG1655"
        assert row["biosample"] == "SAMN02604091"
        assert row["bioproject"] == "PRJNA225"
        assert row["paired_accession"] == "GCA_000005845.2"
        assert row["gc_percent"] == 51
        assert row["files"] == "GCF_000005845.2.fna.gz;GCF_000005845.2.gff.gz"


class TestResolveAccessions:
    @responses.activate
    def test_groups_versions_and_paginates(self):
        url = f"{DATASETS_API}/genome/dataset_report"
        responses.add(
            responses.POST,
            url,
            json={
                "reports": [make_report("GCF_000005845.2", status="current")],
                "next_page_token": "TOKEN",
            },
        )
        responses.add(
            responses.POST,
            url,
            json={
                "reports": [make_report("GCF_000005845.1", status="previous")],
            },
        )
        session = make_session(3, None)
        result = resolve_accessions(session, ["GCF_000005845"])
        assert set(result["GCF_000005845"]) == {1, 2}
        assert result["GCF_000005845"][2].status == "current"
        assert result["GCF_000005845"][1].status == "previous"

    @responses.activate
    def test_api_error_raises(self):
        responses.add(
            responses.POST,
            f"{DATASETS_API}/genome/dataset_report",
            status=500,
        )
        session = make_session(0, None)
        with pytest.raises(ApiError):
            resolve_accessions(session, ["GCF_000005845"])


class TestVerifyTaxon:
    @responses.activate
    def test_success(self):
        responses.add(
            responses.GET,
            f"{DATASETS_API}/taxonomy/taxon/Escherichia%20coli/dataset_report",
            json={
                "reports": [
                    {
                        "taxonomy": {
                            "tax_id": 562,
                            "rank": "SPECIES",
                            "current_scientific_name": {"name": "Escherichia coli"},
                        }
                    }
                ]
            },
        )
        session = make_session(3, None)
        taxon = verify_taxon(session, "Escherichia coli")
        assert taxon["tax_id"] == 562
        assert taxon["name"] == "Escherichia coli"

    @responses.activate
    def test_invalid_name_raises(self):
        responses.add(
            responses.GET,
            f"{DATASETS_API}/taxonomy/taxon/Notreal%20xyz/dataset_report",
            json={
                "reports": [
                    {"errors": [{"reason": "not a recognized NCBI Taxonomy name."}]}
                ]
            },
        )
        session = make_session(3, None)
        with pytest.raises(TaxonError):
            verify_taxon(session, "Notreal xyz")


class TestListTaxonAssemblies:
    @responses.activate
    def test_paginates_and_accumulates(self):
        url = f"{DATASETS_API}/genome/taxon/Escherichia%20coli/dataset_report"
        responses.add(
            responses.GET,
            url,
            json={
                "total_count": 2,
                "reports": [make_report("GCF_000005845.2")],
                "next_page_token": "T",
            },
        )
        responses.add(
            responses.GET,
            url,
            json={"total_count": 2, "reports": [make_report("GCF_000008865.2")]},
        )
        session = make_session(3, None)
        result = list_taxon_assemblies(session, "Escherichia coli", "refseq", ["all"])
        assert [a.accession for a in result] == [
            "GCF_000005845.2",
            "GCF_000008865.2",
        ]

    @responses.activate
    def test_empty_raises(self):
        responses.add(
            responses.GET,
            f"{DATASETS_API}/genome/taxon/Escherichia%20coli/dataset_report",
            json={"total_count": 0},
        )
        session = make_session(3, None)
        with pytest.raises(EmptyResultError):
            list_taxon_assemblies(session, "Escherichia coli", "refseq", ["all"])
