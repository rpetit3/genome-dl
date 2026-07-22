"""Shared fixtures for the genome-dl test suite."""

import pytest

from genome_dl.providers.datasets import Assembly


def make_report(
    accession="GCF_000005845.2",
    assembly_name="ASM584v2",
    status="current",
    source_database="SOURCE_DATABASE_REFSEQ",
    organism_name="Escherichia coli str. K-12 substr. MG1655",
    tax_id=511145,
    **extra,
):
    """Build a minimal-but-realistic dataset_report entry."""
    report = {
        "accession": accession,
        "paired_accession": "GCA_000005845.2",
        "source_database": source_database,
        "organism": {
            "organism_name": organism_name,
            "tax_id": tax_id,
            "infraspecific_names": {"strain": "K-12 substr. MG1655"},
        },
        "assembly_info": {
            "assembly_name": assembly_name,
            "assembly_status": status,
            "assembly_level": "Complete Genome",
            "bioproject_accession": "PRJNA225",
            "submitter": "Univ. Wisconsin",
            "release_date": "2013-09-26",
            "refseq_category": "reference genome",
            "biosample": {"accession": "SAMN02604091"},
        },
        "assembly_stats": {
            "total_sequence_length": "4641652",
            "number_of_contigs": 1,
            "contig_n50": 4641652,
            "gc_percent": 51,
        },
    }
    report.update(extra)
    return report


def make_assembly(
    accession="GCF_000005845.2",
    assembly_name="ASM584v2",
    status="current",
    source_database="SOURCE_DATABASE_REFSEQ",
    organism_name="Escherichia coli str. K-12 substr. MG1655",
    tax_id=511145,
):
    """Build an Assembly with a matching report dict."""
    report = make_report(
        accession=accession,
        assembly_name=assembly_name,
        status=status,
        source_database=source_database,
        organism_name=organism_name,
        tax_id=tax_id,
    )
    return Assembly(
        accession=accession,
        assembly_name=assembly_name,
        status=status,
        source_database=source_database,
        organism_name=organism_name,
        tax_id=tax_id,
        report=report,
    )


@pytest.fixture
def assembly():
    return make_assembly()


@pytest.fixture
def report_factory():
    return make_report


@pytest.fixture
def assembly_factory():
    return make_assembly
