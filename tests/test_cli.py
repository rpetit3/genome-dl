"""Tests for the genome-dl CLI."""

import json
import random
from pathlib import Path

from click.testing import CliRunner

from genome_dl.cli.download import genomedl
from genome_dl.providers.ftp import AssemblyDownload
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
            return_value=AssemblyDownload([tmp_path / "GCF_000005845.2.fna.gz"], []),
        )
        result = CliRunner().invoke(
            genomedl, ["--accession", "GCF_000005845.2", "-o", str(tmp_path)]
        )
        assert result.exit_code == 0
        tsv = tmp_path / "genome-dl-metadata.tsv"
        assert tsv.exists()
        assert "GCF_000005845.2" in tsv.read_text()

    def test_success_writes_summary(self, mocker, tmp_path):
        _patch_common(mocker)
        mocker.patch(
            "genome_dl.cli.download.resolve_accessions",
            return_value={"GCF_000005845": {2: make_assembly()}},
        )
        mocker.patch(
            "genome_dl.cli.download.download_assembly",
            return_value=AssemblyDownload([tmp_path / "GCF_000005845.2.fna.gz"], []),
        )
        result = CliRunner().invoke(
            genomedl, ["--accession", "GCF_000005845.2", "-o", str(tmp_path)]
        )
        assert result.exit_code == 0
        summary = tmp_path / "genome-dl-summary.txt"
        assert summary.exists()
        text = summary.read_text()
        assert "--accession GCF_000005845.2" in text
        assert "Assemblies downloaded: 1" in text

    def test_summary_masks_api_key(self, mocker, tmp_path):
        _patch_common(mocker)
        mocker.patch(
            "genome_dl.cli.download.resolve_accessions",
            return_value={"GCF_000005845": {2: make_assembly()}},
        )
        mocker.patch(
            "genome_dl.cli.download.download_assembly",
            return_value=AssemblyDownload([tmp_path / "GCF_000005845.2.fna.gz"], []),
        )
        result = CliRunner().invoke(
            genomedl,
            ["--accession", "GCF_000005845.2", "-o", str(tmp_path)],
            env={"NCBI_API_KEY": "SECRET123"},
        )
        assert result.exit_code == 0
        text = (tmp_path / "genome-dl-summary.txt").read_text()
        assert "SECRET123" not in text
        assert "--api-key ****" in text

    def test_success_writes_json(self, mocker, tmp_path):
        _patch_common(mocker)
        mocker.patch(
            "genome_dl.cli.download.resolve_accessions",
            return_value={"GCF_000005845": {2: make_assembly()}},
        )
        mocker.patch(
            "genome_dl.cli.download.download_assembly",
            return_value=AssemblyDownload([tmp_path / "GCF_000005845.2.fna.gz"], []),
        )
        result = CliRunner().invoke(
            genomedl,
            ["--accession", "GCF_000005845.2", "-o", str(tmp_path)],
            env={"NCBI_API_KEY": ""},
        )
        assert result.exit_code == 0
        report = tmp_path / "genome-dl.json"
        assert report.exists()
        data = json.loads(report.read_text())
        assert data["genome_dl_version"]
        assert data["parameters"]["accession"] == "GCF_000005845.2"
        assert data["parameters"]["api-key"] is None
        assert data["results"]["downloaded"] == 1
        assert data["results"]["failed"] == 0
        assert data["assemblies"][0]["accession"] == "GCF_000005845.2"
        assert isinstance(data["assemblies"][0]["files"], list)
        assert data["assemblies"][0]["files"] == ["GCF_000005845.2.fna.gz"]

    def test_json_flag_emits_compact_stdout(self, mocker, tmp_path):
        _patch_common(mocker)
        mocker.patch(
            "genome_dl.cli.download.resolve_accessions",
            return_value={"GCF_000005845": {2: make_assembly()}},
        )
        mocker.patch(
            "genome_dl.cli.download.download_assembly",
            return_value=AssemblyDownload([tmp_path / "GCF_000005845.2.fna.gz"], []),
        )
        result = CliRunner().invoke(
            genomedl,
            ["--accession", "GCF_000005845.2", "-o", str(tmp_path), "--json"],
        )
        assert result.exit_code == 0
        out = result.output.strip()
        # single compact line, no pretty-print indentation
        assert "\n" not in out
        assert '": "' not in out and '": {' not in out
        data = json.loads(out)
        assert data["dry_run"] is False
        assert data["results"]["downloaded"] == 1
        assert data["assemblies"][0]["accession"] == "GCF_000005845.2"

    def test_json_flag_dry_run_emits_stdout(self, mocker, tmp_path):
        _patch_common(mocker)
        mocker.patch(
            "genome_dl.cli.download.resolve_accessions",
            return_value={"GCF_000005845": {2: make_assembly()}},
        )
        dl = mocker.patch("genome_dl.cli.download.download_assembly")
        result = CliRunner().invoke(
            genomedl,
            [
                "--accession",
                "GCF_000005845.2",
                "-o",
                str(tmp_path),
                "--dry-run",
                "--json",
            ],
        )
        assert result.exit_code == 0
        dl.assert_not_called()
        out = result.output.strip()
        assert "\t" not in out  # no human tab listing leaked to stdout
        data = json.loads(out)
        assert data["dry_run"] is True
        assert data["results"]["downloaded"] == 0
        assert data["assemblies"][0]["accession"] == "GCF_000005845.2"

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
            return_value=AssemblyDownload([tmp_path / "GCF_000005845.2.fna.gz"], []),
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
        assert not list(Path(tmp_path).glob("*-summary.txt"))
        assert not list(Path(tmp_path).glob("*.json"))

    def test_species_limit_seed_is_deterministic(self, mocker, tmp_path):
        _patch_common(mocker)
        mocker.patch(
            "genome_dl.cli.download.verify_taxon",
            return_value={
                "tax_id": 562,
                "rank": "species",
                "name": "Escherichia coli",
            },
        )
        pool = [make_assembly(accession=f"GCF_00000000{i}.1") for i in range(1, 6)]
        mocker.patch("genome_dl.cli.download.list_taxon_assemblies", return_value=pool)
        downloaded = []

        def fake_download(*args, **kwargs):
            asm = args[2]
            downloaded.append(asm.accession)
            return AssemblyDownload([tmp_path / f"{asm.accession}.fna.gz"], [])

        mocker.patch(
            "genome_dl.cli.download.download_assembly", side_effect=fake_download
        )
        result = CliRunner().invoke(
            genomedl,
            [
                "--species",
                "Escherichia coli",
                "--limit",
                "2",
                "--seed",
                "1",
                "--cpus",
                "1",
                "-o",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0
        # --limit picks exactly N, and --seed makes the subset reproducible.
        expected = {a.accession for a in random.Random(1).sample(pool, 2)}
        assert set(downloaded) == expected
        assert len(downloaded) == 2
