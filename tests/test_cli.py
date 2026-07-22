"""Tests for the genome-dl CLI."""

from pathlib import Path

from click.testing import CliRunner

from genome_dl.cli.download import genomedl
from tests.conftest import make_assembly


def _patch_common(mocker):
    mocker.patch("genome_dl.cli.download.make_session", return_value=object())


class TestInputValidation:
    def test_no_input_exits_nonzero(self, mocker):
        _patch_common(mocker)
        result = CliRunner().invoke(genomedl, [])
        assert result.exit_code == 1

    def test_multiple_inputs_exit_nonzero(self, mocker):
        _patch_common(mocker)
        result = CliRunner().invoke(
            genomedl, ["--accession", "GCF_000005845.2", "--species", "E. coli"]
        )
        assert result.exit_code == 1

    def test_bad_format_exits_one(self, mocker):
        _patch_common(mocker)
        result = CliRunner().invoke(
            genomedl, ["--accession", "GCF_000005845.2", "--formats", "bogus"]
        )
        assert result.exit_code == 1


class TestExitCodes:
    def test_success_writes_metadata(self, mocker, tmp_path):
        _patch_common(mocker)
        mocker.patch(
            "genome_dl.cli.download.resolve_accessions",
            return_value={"GCF_000005845": {2: make_assembly()}},
        )
        mocker.patch(
            "genome_dl.cli.download.download_assembly",
            return_value=[tmp_path / "GCF_000005845.2.fna.gz"],
        )
        result = CliRunner().invoke(
            genomedl, ["--accession", "GCF_000005845.2", "-o", str(tmp_path)]
        )
        assert result.exit_code == 0
        tsv = tmp_path / "genome-dl-metadata.tsv"
        assert tsv.exists()
        assert "GCF_000005845.2" in tsv.read_text()

    def test_suppressed_exits_two(self, mocker, tmp_path):
        _patch_common(mocker)
        mocker.patch(
            "genome_dl.cli.download.resolve_accessions",
            return_value={
                "GCF_000715355": {
                    1: make_assembly(accession="GCF_000715355.1", status="suppressed")
                }
            },
        )
        result = CliRunner().invoke(
            genomedl, ["--accession", "GCF_000715355.1", "-o", str(tmp_path)]
        )
        assert result.exit_code == 2

    def test_partial_exits_three(self, mocker, tmp_path):
        _patch_common(mocker)
        mocker.patch(
            "genome_dl.cli.download.resolve_accessions",
            return_value={
                "GCF_000005845": {2: make_assembly()},
                "GCF_000715355": {
                    1: make_assembly(accession="GCF_000715355.1", status="suppressed")
                },
            },
        )
        mocker.patch(
            "genome_dl.cli.download.download_assembly",
            return_value=[tmp_path / "GCF_000005845.2.fna.gz"],
        )
        acc_file = tmp_path / "accs.txt"
        acc_file.write_text("GCF_000005845.2\nGCF_000715355.1\n")
        result = CliRunner().invoke(
            genomedl, ["--accessions", str(acc_file), "-o", str(tmp_path)]
        )
        assert result.exit_code == 3

    def test_dry_run_writes_nothing(self, mocker, tmp_path):
        _patch_common(mocker)
        mocker.patch(
            "genome_dl.cli.download.resolve_accessions",
            return_value={"GCF_000005845": {2: make_assembly()}},
        )
        dl = mocker.patch("genome_dl.cli.download.download_assembly")
        result = CliRunner().invoke(
            genomedl,
            ["--accession", "GCF_000005845.2", "-o", str(tmp_path), "--dry-run"],
        )
        assert result.exit_code == 0
        assert "GCF_000005845.2" in result.output
        dl.assert_not_called()
        assert not list(Path(tmp_path).glob("*-metadata.tsv"))
