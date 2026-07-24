"""Tests for genome_dl.utils."""

import json

import pytest

from genome_dl.exceptions import ValidationError
from genome_dl.utils import (
    md5sum,
    parse_accession,
    read_accessions,
    write_json,
    write_tsv,
)


class TestParseAccession:
    def test_refseq_with_version(self):
        assert parse_accession("GCF_000005845.2") == ("GCF_000005845", 2)

    def test_genbank_with_version(self):
        assert parse_accession("GCA_000005845.1") == ("GCA_000005845", 1)

    def test_versionless(self):
        assert parse_accession("GCF_000005845") == ("GCF_000005845", None)

    def test_lowercase_is_upcased(self):
        assert parse_accession("gcf_000005845.2") == ("GCF_000005845", 2)

    def test_whitespace_stripped(self):
        assert parse_accession("  GCF_000005845.2  ") == ("GCF_000005845", 2)

    @pytest.mark.parametrize(
        "token",
        ["GCF_00005845.2", "GCX_000005845.2", "SRR12345", "", "GCF_000005845.2.1"],
    )
    def test_invalid_raises(self, token):
        with pytest.raises(ValidationError):
            parse_accession(token)


class TestReadAccessions:
    def test_skips_blank_and_comments(self, tmp_path):
        f = tmp_path / "acc.txt"
        f.write_text(
            "GCF_000005845.2\n\n# a comment\nGCF_014058445.1\n   \nGCA_000001.1\n"
        )
        assert read_accessions(str(f)) == [
            "GCF_000005845.2",
            "GCF_014058445.1",
            "GCA_000001.1",
        ]

    def test_missing_file_raises_validationerror(self, tmp_path):
        with pytest.raises(ValidationError):
            read_accessions(str(tmp_path / "does-not-exist.txt"))


class TestMd5sum:
    def test_matches_known_value(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_bytes(b"hello world")
        # md5("hello world")
        assert md5sum(str(f)) == "5eb63bbbe01eeed093cb22bb8f5acdc3"

    def test_missing_file_returns_none(self, tmp_path):
        assert md5sum(str(tmp_path / "nope.txt")) is None


class TestWriteTsv:
    def test_header_order_and_missing_fill(self, tmp_path):
        out = tmp_path / "meta.tsv"
        rows = [
            {"a": "1", "b": "2", "c": "ignored"},
            {"a": "3"},
        ]
        write_tsv(rows, str(out), ["a", "b"])
        lines = out.read_text().splitlines()
        assert lines[0] == "a\tb"
        assert lines[1] == "1\t2"
        # missing key filled with empty string, extra key "c" dropped
        assert lines[2] == "3\t"


class TestWriteJson:
    def test_roundtrip_stringifies_paths(self, tmp_path):
        out = tmp_path / "report.json"
        data = {"outdir": tmp_path, "items": [1, 2, 3], "name": "x"}
        write_json(data, str(out))
        text = out.read_text()
        assert text.endswith("\n")
        loaded = json.loads(text)
        assert loaded == {"outdir": str(tmp_path), "items": [1, 2, 3], "name": "x"}
