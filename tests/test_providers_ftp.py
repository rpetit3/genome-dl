"""Tests for genome_dl.providers.ftp."""

import hashlib

import pytest
import requests
import responses

from genome_dl.constants import FTP_BASE
from genome_dl.exceptions import DownloadError
from genome_dl.providers.datasets import make_session
from genome_dl.providers.ftp import (
    assembly_dir_url,
    download_assembly,
    fetch_md5,
)
from tests.conftest import make_assembly

DIR = f"{FTP_BASE}/all/GCF/000/005/845/GCF_000005845.2_ASM584v2/"


class TestAssemblyDirUrl:
    def test_refseq(self):
        assert (
            assembly_dir_url(FTP_BASE, "GCF_000005845.2", "ASM584v2")
            == f"{FTP_BASE}/all/GCF/000/005/845/GCF_000005845.2_ASM584v2/"
        )

    def test_genbank_prefix(self):
        assert (
            assembly_dir_url(FTP_BASE, "GCA_000005845.2", "ASM584v2")
            == f"{FTP_BASE}/all/GCA/000/005/845/GCA_000005845.2_ASM584v2/"
        )

    def test_spaces_sanitized(self):
        url = assembly_dir_url(FTP_BASE, "GCA_902459825.2", "MB3601_COMBINED annotated")
        assert url.endswith("GCA_902459825.2_MB3601_COMBINED_annotated/")

    def test_dots_preserved(self):
        url = assembly_dir_url(FTP_BASE, "GCA_049959555.1", "Valafar_Erdman 1.0")
        assert url.endswith("GCA_049959555.1_Valafar_Erdman_1.0/")


class TestFetchMd5:
    @responses.activate
    def test_parses_entries(self):
        responses.add(
            responses.GET,
            f"{DIR}md5checksums.txt",
            body=(
                "abc123  ./GCF_000005845.2_ASM584v2_genomic.fna.gz\n"
                "def456  ./GCF_000005845.2_ASM584v2_genomic.gff.gz\n"
            ),
        )
        session = make_session(3, None)
        md5s = fetch_md5(session, DIR)
        assert md5s == {
            "GCF_000005845.2_ASM584v2_genomic.fna.gz": "abc123",
            "GCF_000005845.2_ASM584v2_genomic.gff.gz": "def456",
        }

    @responses.activate
    def test_network_error_raises_downloaderror(self):
        responses.add(
            responses.GET,
            f"{DIR}md5checksums.txt",
            body=requests.exceptions.ConnectionError("boom"),
        )
        session = make_session(1, None)
        with pytest.raises(DownloadError):
            fetch_md5(session, DIR)


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


class TestDownloadAssembly:
    @responses.activate
    def test_happy_path_names_by_accession(self, tmp_path):
        fna = b"FASTA-CONTENT"
        gff = b"GFF-CONTENT"
        md5_body = (
            f"{_md5(fna)}  ./GCF_000005845.2_ASM584v2_genomic.fna.gz\n"
            f"{_md5(gff)}  ./GCF_000005845.2_ASM584v2_genomic.gff.gz\n"
        )
        responses.add(responses.GET, f"{DIR}md5checksums.txt", body=md5_body)
        responses.add(
            responses.GET,
            f"{DIR}GCF_000005845.2_ASM584v2_genomic.fna.gz",
            body=fna,
        )
        responses.add(
            responses.GET,
            f"{DIR}GCF_000005845.2_ASM584v2_genomic.gff.gz",
            body=gff,
        )
        session = make_session(3, None)
        download_session = make_session(3, None, retries=False)
        written, _ = download_assembly(
            session,
            download_session,
            make_assembly(),
            ["fasta", "gff"],
            tmp_path,
            FTP_BASE,
            force=False,
            ignore_md5=False,
            max_attempts=2,
            sleep=0,
        )
        names = sorted(p.name for p in written)
        assert names == ["GCF_000005845.2.fna.gz", "GCF_000005845.2.gff.gz"]
        assert (tmp_path / "GCF_000005845.2.fna.gz").read_bytes() == fna

    @responses.activate
    def test_cds_and_rna_disambiguated(self, tmp_path):
        cds = b"CDS"
        rna = b"RNA"
        responses.add(
            responses.GET,
            f"{DIR}md5checksums.txt",
            body=(
                f"{_md5(cds)}  ./GCF_000005845.2_ASM584v2_cds_from_genomic.fna.gz\n"
                f"{_md5(rna)}  ./GCF_000005845.2_ASM584v2_rna_from_genomic.fna.gz\n"
            ),
        )
        responses.add(
            responses.GET,
            f"{DIR}GCF_000005845.2_ASM584v2_cds_from_genomic.fna.gz",
            body=cds,
        )
        responses.add(
            responses.GET,
            f"{DIR}GCF_000005845.2_ASM584v2_rna_from_genomic.fna.gz",
            body=rna,
        )
        session = make_session(3, None)
        download_session = make_session(3, None, retries=False)
        written, _ = download_assembly(
            session,
            download_session,
            make_assembly(),
            ["cds", "rna"],
            tmp_path,
            FTP_BASE,
            force=False,
            ignore_md5=False,
            max_attempts=2,
            sleep=0,
        )
        names = sorted(p.name for p in written)
        assert names == ["GCF_000005845.2.cds.fna.gz", "GCF_000005845.2.rna.fna.gz"]

    @responses.activate
    def test_missing_format_skipped(self, tmp_path):
        fna = b"FASTA"
        responses.add(
            responses.GET,
            f"{DIR}md5checksums.txt",
            body=f"{_md5(fna)}  ./GCF_000005845.2_ASM584v2_genomic.fna.gz\n",
        )
        responses.add(
            responses.GET,
            f"{DIR}GCF_000005845.2_ASM584v2_genomic.fna.gz",
            body=fna,
        )
        session = make_session(3, None)
        download_session = make_session(3, None, retries=False)
        written, unavailable = download_assembly(
            session,
            download_session,
            make_assembly(),
            ["fasta", "gff"],  # gff not in md5checksums
            tmp_path,
            FTP_BASE,
            force=False,
            ignore_md5=False,
            max_attempts=2,
            sleep=0,
        )
        assert [p.name for p in written] == ["GCF_000005845.2.fna.gz"]
        assert unavailable == ["gff"]

    @responses.activate
    def test_md5_mismatch_raises_after_retries(self, tmp_path):
        responses.add(
            responses.GET,
            f"{DIR}md5checksums.txt",
            body="deadbeef  ./GCF_000005845.2_ASM584v2_genomic.fna.gz\n",
        )
        responses.add(
            responses.GET,
            f"{DIR}GCF_000005845.2_ASM584v2_genomic.fna.gz",
            body=b"WRONG",
        )
        session = make_session(3, None)
        download_session = make_session(3, None, retries=False)
        with pytest.raises(DownloadError):
            download_assembly(
                session,
                download_session,
                make_assembly(),
                ["fasta"],
                tmp_path,
                FTP_BASE,
                force=False,
                ignore_md5=False,
                max_attempts=2,
                sleep=0,
            )
        assert not (tmp_path / "GCF_000005845.2.fna.gz").exists()

    @responses.activate
    def test_ignore_md5_skips_verification_and_unavailable(self, tmp_path):
        # md5 is deliberately WRONG and gff is absent from the manifest.
        responses.add(
            responses.GET,
            f"{DIR}md5checksums.txt",
            body="deadbeef  ./GCF_000005845.2_ASM584v2_genomic.fna.gz\n",
        )
        responses.add(
            responses.GET,
            f"{DIR}GCF_000005845.2_ASM584v2_genomic.fna.gz",
            body=b"FASTA",
        )
        session = make_session(3, None)
        download_session = make_session(3, None, retries=False)
        written, unavailable = download_assembly(
            session,
            download_session,
            make_assembly(),
            ["fasta", "gff"],  # gff not in manifest
            tmp_path,
            FTP_BASE,
            force=False,
            ignore_md5=True,
            max_attempts=2,
            sleep=0,
        )
        # fasta downloads despite md5 mismatch (verification skipped);
        # gff is skipped as unavailable instead of hard-failing.
        assert [p.name for p in written] == ["GCF_000005845.2.fna.gz"]
        assert unavailable == ["gff"]
        assert (tmp_path / "GCF_000005845.2.fna.gz").read_bytes() == b"FASTA"

    @responses.activate
    def test_md5checksums_fetched_once(self, tmp_path):
        fna = b"FASTA"
        responses.add(
            responses.GET,
            f"{DIR}md5checksums.txt",
            body=f"{_md5(fna)}  ./GCF_000005845.2_ASM584v2_genomic.fna.gz\n",
        )
        responses.add(
            responses.GET,
            f"{DIR}GCF_000005845.2_ASM584v2_genomic.fna.gz",
            body=fna,
        )
        session = make_session(3, None)
        download_session = make_session(3, None, retries=False)
        download_assembly(
            session,
            download_session,
            make_assembly(),
            ["fasta"],
            tmp_path,
            FTP_BASE,
            force=False,
            ignore_md5=False,
            max_attempts=2,
            sleep=0,
        )
        md5_hits = [
            c for c in responses.calls if c.request.url.endswith("md5checksums.txt")
        ]
        assert len(md5_hits) == 1
