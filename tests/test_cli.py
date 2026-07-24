"""Tests for the genome-dl CLI."""

import json
import threading
from pathlib import Path

import pytest
from click.testing import CliRunner

from genome_dl.cli.download import _execute_downloads, genomedl
from genome_dl.exceptions import DownloadError
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
            return_value=AssemblyDownload(
                [tmp_path / "GCF_000005845.2.fna.gz"], [], []
            ),
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
            return_value=AssemblyDownload(
                [tmp_path / "GCF_000005845.2.fna.gz"], [], []
            ),
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
            return_value=AssemblyDownload(
                [tmp_path / "GCF_000005845.2.fna.gz"], [], []
            ),
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
            return_value=AssemblyDownload(
                [tmp_path / "GCF_000005845.2.fna.gz"], [], []
            ),
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
            return_value=AssemblyDownload(
                [tmp_path / "GCF_000005845.2.fna.gz"], [], []
            ),
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
            return_value=AssemblyDownload(
                [tmp_path / "GCF_000005845.2.fna.gz"], [], []
            ),
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

    def test_species_limit_fetches_first_x(self, mocker, tmp_path):
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
        # The provider applies the limit and reports the full population count;
        # the CLI consumes (first_x_assemblies, total_count).
        mocker.patch(
            "genome_dl.cli.download.list_taxon_assemblies",
            return_value=(pool[:2], len(pool)),
        )
        downloaded = []

        def fake_download(*args, **kwargs):
            asm = args[2]
            downloaded.append(asm.accession)
            return AssemblyDownload([tmp_path / f"{asm.accession}.fna.gz"], [], [])

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
                "--cpus",
                "1",
                "-o",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0
        # The first X assemblies flow through to download; nothing beyond X.
        assert downloaded == [a.accession for a in pool[:2]]
        assert len(downloaded) == 2

    def test_duplicate_tokens_deduped(self, mocker, tmp_path):
        _patch_common(mocker)
        mocker.patch(
            "genome_dl.cli.download.resolve_accessions",
            return_value={"GCF_000005845": {2: make_assembly()}},
        )
        calls = []

        def fake_download(*args, **kwargs):
            asm = args[2]
            calls.append(asm.accession)
            return AssemblyDownload([tmp_path / f"{asm.accession}.fna.gz"], [], [])

        mocker.patch(
            "genome_dl.cli.download.download_assembly", side_effect=fake_download
        )
        acc_file = tmp_path / "accs.txt"
        # Two distinct tokens that resolve to the same current accession.
        acc_file.write_text("GCF_000005845\nGCF_000005845.2\n")
        result = CliRunner().invoke(
            genomedl,
            ["--accessions", str(acc_file), "-o", str(tmp_path), "--cpus", "1"],
        )
        assert result.exit_code == 0
        # Downloaded exactly once, not twice (no race on the shared output file).
        assert calls == ["GCF_000005845.2"]
        rows = (tmp_path / "genome-dl-metadata.tsv").read_text().strip().splitlines()
        assert len(rows) == 2  # header + one data row

    def test_all_download_failed_exits_one(self, mocker, tmp_path):
        # Accession resolved fine but every download failed -> transient
        # download error (exit 1), not "not found" (exit 2).
        _patch_common(mocker)
        mocker.patch(
            "genome_dl.cli.download.resolve_accessions",
            return_value={"GCF_000005845": {2: make_assembly()}},
        )
        mocker.patch(
            "genome_dl.cli.download.download_assembly",
            side_effect=DownloadError("network boom", accession="GCF_000005845.2"),
        )
        result = CliRunner().invoke(
            genomedl, ["--accession", "GCF_000005845.2", "-o", str(tmp_path)]
        )
        assert result.exit_code == 1

    def test_unexpected_error_recorded_not_crash(self, mocker, tmp_path):
        # A non-DownloadError (e.g. OSError: disk full) from one assembly must
        # be recorded as a failure and exit 1, not crash the whole run.
        _patch_common(mocker)
        mocker.patch(
            "genome_dl.cli.download.resolve_accessions",
            return_value={"GCF_000005845": {2: make_assembly()}},
        )
        mocker.patch(
            "genome_dl.cli.download.download_assembly",
            side_effect=OSError("No space left on device"),
        )
        result = CliRunner().invoke(
            genomedl, ["--accession", "GCF_000005845.2", "-o", str(tmp_path)]
        )
        assert result.exit_code == 1
        assert result.exception is None or isinstance(result.exception, SystemExit)

    def test_prefix_path_traversal_rejected(self, mocker, tmp_path):
        _patch_common(mocker)
        result = CliRunner().invoke(
            genomedl,
            [
                "--accession",
                "GCF_000005845.2",
                "-o",
                str(tmp_path),
                "--prefix",
                "../evil",
            ],
        )
        assert result.exit_code == 1


class TestFtpSessionWiring:
    def test_ftp_sessions_omit_api_key_and_use_identity(
        self, mocker, tmp_path, monkeypatch
    ):
        # L1: the api-key must never be attached to FTP-host traffic.
        # F1: the byte-download session must request identity encoding.
        monkeypatch.setenv("NCBI_API_KEY", "SECRET")
        calls = []

        def fake_make_session(max_attempts, api_key, **kwargs):
            calls.append((api_key, kwargs))
            return object()

        mocker.patch(
            "genome_dl.cli.download.make_session", side_effect=fake_make_session
        )
        mocker.patch(
            "genome_dl.cli.download.resolve_accessions",
            return_value={"GCF_000005845": {2: make_assembly()}},
        )
        mocker.patch(
            "genome_dl.cli.download.download_assembly",
            return_value=AssemblyDownload(
                [tmp_path / "GCF_000005845.2.fna.gz"], [], []
            ),
        )
        result = CliRunner().invoke(
            genomedl, ["--accession", "GCF_000005845.2", "-o", str(tmp_path)]
        )
        assert result.exit_code == 0
        # Exactly one session carries the key (the Datasets API session); the two
        # FTP-host sessions (dir/md5 resolution + byte download) are keyless.
        keyed = [kw for key, kw in calls if key == "SECRET"]
        keyless = [kw for key, kw in calls if key is None]
        assert len(keyed) == 1
        assert len(keyless) == 2
        assert any(kw.get("identity_encoding") for kw in keyless)


class TestVersionPin:
    def _resolve_env(self, mocker):
        prev = make_assembly(
            accession="GCF_000005845.1", assembly_name="ASM584v1", status="previous"
        )
        curr = make_assembly(accession="GCF_000005845.2", status="current")
        mocker.patch(
            "genome_dl.cli.download.resolve_accessions",
            return_value={"GCF_000005845": {1: prev, 2: curr}},
        )

    def test_outdated_pin_errors_by_default(self, mocker, tmp_path, caplog):
        # F2: an explicit outdated pin is refused by default (reproducibility);
        # the error names the current version and the --allow-outdated escape.
        _patch_common(mocker)
        self._resolve_env(mocker)
        dl = mocker.patch("genome_dl.cli.download.download_assembly")
        with caplog.at_level("ERROR"):
            result = CliRunner().invoke(
                genomedl, ["--accession", "GCF_000005845.1", "-o", str(tmp_path)]
            )
        assert result.exit_code == 2
        dl.assert_not_called()
        assert "current: GCF_000005845.2" in caplog.text
        assert "--allow-outdated" in caplog.text

    def test_outdated_pin_downloaded_with_allow_outdated(
        self, mocker, tmp_path, caplog
    ):
        # F2: with --allow-outdated the exact pinned version downloads and a
        # newer-version warning is emitted.
        _patch_common(mocker)
        self._resolve_env(mocker)
        captured = {}

        def fake_dl(ftp_session, download_session, asm, *args, **kwargs):
            captured["accession"] = asm.accession
            return AssemblyDownload([tmp_path / f"{asm.accession}.fna.gz"], [], [])

        mocker.patch("genome_dl.cli.download.download_assembly", side_effect=fake_dl)
        with caplog.at_level("WARNING"):
            result = CliRunner().invoke(
                genomedl,
                [
                    "--accession",
                    "GCF_000005845.1",
                    "--allow-outdated",
                    "-o",
                    str(tmp_path),
                ],
            )
        assert result.exit_code == 0
        assert captured["accession"] == "GCF_000005845.1"
        assert "newer version GCF_000005845.2 exists" in caplog.text


class TestConcurrentDownloads:
    def test_execute_downloads_runs_in_parallel(self, mocker, tmp_path):
        # L4: prove real concurrency -- three workers must reach the barrier
        # simultaneously; a serial executor would time out and fail every task.
        targets = [make_assembly(accession=f"GCF_00000584{i}.2") for i in range(3)]
        barrier = threading.Barrier(3, timeout=5)

        def fake_dl(*args, **kwargs):
            barrier.wait()
            asm = args[2]
            return AssemblyDownload([tmp_path / f"{asm.accession}.fna.gz"], [], [])

        mocker.patch("genome_dl.cli.download.download_assembly", side_effect=fake_dl)
        failures = {}
        successful = _execute_downloads(
            object(),
            object(),
            targets,
            ["fasta"],
            tmp_path,
            False,
            False,
            1,
            0,
            3,
            False,
            failures,
        )
        assert len(successful) == 3
        assert failures == {}

    def test_execute_downloads_keyboardinterrupt_propagates(self, mocker, tmp_path):
        # L4: a Ctrl-C in a worker cancels the batch and re-raises so the CLI
        # can exit 130.
        targets = [make_assembly()]
        mocker.patch(
            "genome_dl.cli.download.download_assembly", side_effect=KeyboardInterrupt
        )
        failures = {}
        with pytest.raises(KeyboardInterrupt):
            _execute_downloads(
                object(),
                object(),
                targets,
                ["fasta"],
                tmp_path,
                False,
                False,
                1,
                0,
                1,
                False,
                failures,
            )


class TestOptionBounds:
    def test_empty_formats_exits_one(self, mocker):
        _patch_common(mocker)
        result = CliRunner().invoke(
            genomedl, ["--accession", "GCF_000005845.2", "--formats", ""]
        )
        assert result.exit_code == 1

    def test_empty_assembly_level_exits_one(self, mocker):
        _patch_common(mocker)
        result = CliRunner().invoke(
            genomedl, ["--species", "Escherichia coli", "--assembly-level", ""]
        )
        assert result.exit_code == 1

    def test_cpus_zero_rejected(self, mocker):
        _patch_common(mocker)
        result = CliRunner().invoke(
            genomedl, ["--accession", "GCF_000005845.2", "--cpus", "0"]
        )
        assert result.exit_code == 2

    def test_high_cpus_warns(self, mocker, tmp_path, caplog):
        _patch_common(mocker)
        mocker.patch(
            "genome_dl.cli.download.resolve_accessions",
            return_value={"GCF_000005845": {2: make_assembly()}},
        )
        mocker.patch(
            "genome_dl.cli.download.download_assembly",
            return_value=AssemblyDownload(
                [tmp_path / "GCF_000005845.2.fna.gz"], [], []
            ),
        )
        with caplog.at_level("WARNING"):
            result = CliRunner().invoke(
                genomedl,
                ["--accession", "GCF_000005845.2", "--cpus", "32", "-o", str(tmp_path)],
            )
        assert result.exit_code == 0
        assert "--cpus 32 exceeds 16" in caplog.text

    def test_cpus_at_threshold_no_warning(self, mocker, tmp_path, caplog):
        _patch_common(mocker)
        mocker.patch(
            "genome_dl.cli.download.resolve_accessions",
            return_value={"GCF_000005845": {2: make_assembly()}},
        )
        mocker.patch(
            "genome_dl.cli.download.download_assembly",
            return_value=AssemblyDownload(
                [tmp_path / "GCF_000005845.2.fna.gz"], [], []
            ),
        )
        with caplog.at_level("WARNING"):
            result = CliRunner().invoke(
                genomedl,
                ["--accession", "GCF_000005845.2", "--cpus", "16", "-o", str(tmp_path)],
            )
        assert result.exit_code == 0
        assert "exceeds" not in caplog.text

    def test_max_attempts_zero_rejected(self, mocker):
        _patch_common(mocker)
        result = CliRunner().invoke(
            genomedl, ["--accession", "GCF_000005845.2", "--max-attempts", "0"]
        )
        assert result.exit_code == 2

    def test_sleep_negative_rejected(self, mocker):
        _patch_common(mocker)
        result = CliRunner().invoke(
            genomedl, ["--accession", "GCF_000005845.2", "--sleep=-5"]
        )
        assert result.exit_code == 2

    def test_limit_negative_rejected(self, mocker):
        _patch_common(mocker)
        result = CliRunner().invoke(
            genomedl, ["--species", "Escherichia coli", "--limit=-1"]
        )
        assert result.exit_code == 2

    def test_outdir_is_file_exits_one(self, mocker, tmp_path):
        _patch_common(mocker)
        target = tmp_path / "not-a-dir"
        target.write_text("x")
        result = CliRunner().invoke(
            genomedl,
            ["--accession", "GCF_000005845.2", "--outdir", str(target)],
        )
        assert result.exit_code == 1
