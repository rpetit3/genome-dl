"""Tests for genome_dl.providers.ftp."""

import hashlib

import pytest
import requests
import responses

from genome_dl.constants import FTP_BASE
from genome_dl.exceptions import DownloadError
from genome_dl.providers.datasets import make_session
from genome_dl.providers.ftp import (
    _download_file,
    assembly_dir_url,
    download_assembly,
    fetch_md5,
    resolve_dir,
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
        written, _, _ = download_assembly(
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
        written, _, _ = download_assembly(
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
        written, unavailable, _ = download_assembly(
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
        written, unavailable, _ = download_assembly(
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

    @responses.activate
    def test_fallback_dir_uses_resolved_stem(self, tmp_path):
        # Our sanitized candidate dir 404s; the real NCBI dir has a different
        # stem. Filenames must be built from the resolved directory, not the
        # re-sanitized assembly name, or every format is silently "unavailable".
        asm = make_assembly(assembly_name="Weird#Name")
        candidate = f"{FTP_BASE}/all/GCF/000/005/845/GCF_000005845.2_Weird_Name/"
        parent = f"{FTP_BASE}/all/GCF/000/005/845/"
        real_dir = f"{parent}GCF_000005845.2_RealStem/"
        fna = b"FASTA-CONTENT"
        # candidate manifest 404s -> triggers the parent-listing fallback
        responses.add(responses.GET, f"{candidate}md5checksums.txt", status=404)
        responses.add(
            responses.GET,
            parent,
            body='<a href="GCF_000005845.2_RealStem/">dir</a>',
        )
        responses.add(
            responses.GET,
            f"{real_dir}md5checksums.txt",
            body=f"{_md5(fna)}  ./GCF_000005845.2_RealStem_genomic.fna.gz\n",
        )
        responses.add(
            responses.GET,
            f"{real_dir}GCF_000005845.2_RealStem_genomic.fna.gz",
            body=fna,
        )
        session = make_session(3, None)
        download_session = make_session(3, None, retries=False)
        written, unavailable, _ = download_assembly(
            session,
            download_session,
            asm,
            ["fasta"],
            tmp_path,
            FTP_BASE,
            force=False,
            ignore_md5=False,
            max_attempts=2,
            sleep=0,
        )
        assert [p.name for p in written] == ["GCF_000005845.2.fna.gz"]
        assert unavailable == []
        assert (tmp_path / "GCF_000005845.2.fna.gz").read_bytes() == fna


class TestPartialAndTruncation:
    @responses.activate
    def test_truncated_download_detected_even_when_md5_ignored(self, tmp_path):
        # Content-Length says 1000 but only a few bytes arrive; with --ignore
        # (no md5) the completeness check is the only guard against truncation.
        responses.add(
            responses.GET,
            f"{DIR}md5checksums.txt",
            body="deadbeef  ./GCF_000005845.2_ASM584v2_genomic.fna.gz\n",
        )
        responses.add(
            responses.GET,
            f"{DIR}GCF_000005845.2_ASM584v2_genomic.fna.gz",
            body=b"SHORT",
            headers={"Content-Length": "1000"},
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
                ignore_md5=True,
                max_attempts=2,
                sleep=0,
            )
        assert not (tmp_path / "GCF_000005845.2.fna.gz").exists()

    @responses.activate
    def test_partial_format_failure_keeps_written(self, tmp_path):
        # fasta downloads; gff is in the manifest but its download 404s.
        # The good fasta must be kept and the assembly reported as partial.
        fna = b"FASTA"
        responses.add(
            responses.GET,
            f"{DIR}md5checksums.txt",
            body=(
                f"{_md5(fna)}  ./GCF_000005845.2_ASM584v2_genomic.fna.gz\n"
                f"deadbeef  ./GCF_000005845.2_ASM584v2_genomic.gff.gz\n"
            ),
        )
        responses.add(
            responses.GET,
            f"{DIR}GCF_000005845.2_ASM584v2_genomic.fna.gz",
            body=fna,
        )
        responses.add(
            responses.GET,
            f"{DIR}GCF_000005845.2_ASM584v2_genomic.gff.gz",
            status=404,
        )
        session = make_session(3, None)
        download_session = make_session(3, None, retries=False)
        written, unavailable, failed = download_assembly(
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
        assert [p.name for p in written] == ["GCF_000005845.2.fna.gz"]
        assert unavailable == []
        assert failed == ["gff"]
        assert (tmp_path / "GCF_000005845.2.fna.gz").read_bytes() == fna

    @responses.activate
    def test_zero_files_all_unavailable_raises(self, tmp_path):
        # Requesting only a format absent from the manifest yields zero files,
        # which must be a failure rather than a silent exit-0 success.
        responses.add(
            responses.GET,
            f"{DIR}md5checksums.txt",
            body="abc  ./GCF_000005845.2_ASM584v2_genomic.fna.gz\n",
        )
        session = make_session(3, None)
        download_session = make_session(3, None, retries=False)
        with pytest.raises(DownloadError):
            download_assembly(
                session,
                download_session,
                make_assembly(),
                ["gff"],  # not in the manifest
                tmp_path,
                FTP_BASE,
                force=False,
                ignore_md5=False,
                max_attempts=2,
                sleep=0,
            )


class _StreamResp:
    """Minimal stand-in for a streamed ``requests`` response.

    ``drop_after`` injects a mid-stream connection drop: ``iter_content`` yields
    that many chunks, then raises ``ChunkedEncodingError`` the way a real socket
    reset surfaces (a ``RequestException`` requests raises while reading the
    body, which the HTTPAdapter Retry does not cover).
    """

    def __init__(self, chunks, *, status=200, content_length=None, drop_after=None):
        self.status_code = status
        self.ok = 200 <= status < 400
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)
        self._chunks = chunks
        self._drop_after = drop_after

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, chunk_size=None):
        for i, chunk in enumerate(self._chunks):
            if self._drop_after is not None and i == self._drop_after:
                raise requests.exceptions.ChunkedEncodingError(
                    "Response ended prematurely"
                )
            yield chunk


class _FakeDownloadSession:
    """Serve a scripted sequence of ``_StreamResp`` objects for each GET."""

    def __init__(self, *responses_seq):
        self._seq = list(responses_seq)
        self.calls = 0

    def get(self, url, stream=True):
        resp = self._seq[self.calls]
        self.calls += 1
        return resp


class TestConnectionDrop:
    def test_midstream_drop_retries_and_recovers(self, tmp_path):
        # Attempt 1 drops after the first chunk; attempt 2 delivers the full
        # body. The partial '.part' must be cleaned and the retry must succeed.
        fna = b"AAAABBBBCCCC"
        target = tmp_path / "GCF_000005845.2.fna.gz"
        session = _FakeDownloadSession(
            _StreamResp(
                [b"AAAA", b"BBBB", b"CCCC"], content_length=len(fna), drop_after=1
            ),
            _StreamResp([fna], content_length=len(fna)),
        )
        _download_file(
            session,
            f"{DIR}GCF_000005845.2_ASM584v2_genomic.fna.gz",
            target,
            _md5(fna),
            max_attempts=3,
            sleep=0,
            progress=None,
            label="GCF_000005845.2.fna.gz",
        )
        assert session.calls == 2
        assert target.read_bytes() == fna
        assert not target.with_suffix(".gz.part").exists()

    def test_persistent_drop_exhausts_with_actionable_message(self, tmp_path):
        target = tmp_path / "GCF_000005845.2.fna.gz"
        session = _FakeDownloadSession(
            _StreamResp([b"AAAA", b"BBBB"], content_length=8, drop_after=1),
            _StreamResp([b"AAAA", b"BBBB"], content_length=8, drop_after=1),
        )
        with pytest.raises(DownloadError) as excinfo:
            _download_file(
                session,
                f"{DIR}GCF_000005845.2_ASM584v2_genomic.fna.gz",
                target,
                None,
                max_attempts=2,
                sleep=0,
                progress=None,
                label="GCF_000005845.2.fna.gz",
            )
        msg = str(excinfo.value)
        assert "after 2 attempt" in msg
        assert "retry later" in msg
        assert session.calls == 2
        assert not target.exists()


class TestServerErrorsAndFileStatus:
    @responses.activate
    def test_ftp_5xx_download_exhausts_and_names_status(self, tmp_path):
        # The byte-download session opts out of adapter retries; its manual loop
        # must retry a 5xx up to max_attempts, then fail with an actionable msg.
        url = f"{DIR}GCF_000005845.2_ASM584v2_genomic.fna.gz"
        responses.add(responses.GET, url, status=503)
        download_session = make_session(3, None, retries=False)
        with pytest.raises(DownloadError) as excinfo:
            _download_file(
                download_session,
                url,
                tmp_path / "GCF_000005845.2.fna.gz",
                None,
                max_attempts=3,
                sleep=0,
                progress=None,
                label="GCF_000005845.2.fna.gz",
            )
        msg = str(excinfo.value)
        assert "HTTP 503" in msg
        assert "after 3 attempt" in msg
        assert len(responses.calls) == 3  # retried, not failed fast

    @responses.activate
    def test_ftp_404_file_fails_fast_without_retry(self, tmp_path):
        # A 4xx on a file is permanent: it must NOT burn every attempt/sleep,
        # and the message must point at a removed/superseded file.
        url = f"{DIR}GCF_000005845.2_ASM584v2_genomic.fna.gz"
        responses.add(responses.GET, url, status=404)
        download_session = make_session(3, None, retries=False)
        with pytest.raises(DownloadError) as excinfo:
            _download_file(
                download_session,
                url,
                tmp_path / "GCF_000005845.2.fna.gz",
                None,
                max_attempts=3,
                sleep=0,
                progress=None,
                label="GCF_000005845.2.fna.gz",
            )
        msg = str(excinfo.value)
        assert "HTTP 404" in msg
        assert "removed or superseded" in msg
        assert len(responses.calls) == 1  # not retried

    @responses.activate
    def test_ftp_429_file_is_retried(self, tmp_path):
        # 429 (rate-limit) is a retriable 4xx and must NOT be treated as
        # permanent, so it burns every attempt rather than failing fast.
        url = f"{DIR}GCF_000005845.2_ASM584v2_genomic.fna.gz"
        responses.add(responses.GET, url, status=429)
        download_session = make_session(3, None, retries=False)
        with pytest.raises(DownloadError) as excinfo:
            _download_file(
                download_session,
                url,
                tmp_path / "GCF_000005845.2.fna.gz",
                None,
                max_attempts=3,
                sleep=0,
                progress=None,
                label="GCF_000005845.2.fna.gz",
            )
        assert "HTTP 429" in str(excinfo.value)
        assert len(responses.calls) == 3  # retried, not failed fast

    def test_truncated_stream_detected_without_ignore(self, tmp_path):
        # The completeness check runs BEFORE md5. The stub yields fewer bytes
        # than Content-Length without raising (a real urllib3 stream would raise
        # IncompleteRead, but a clean short close from a proxy would not), and
        # the md5 matches those bytes -- so md5 alone would pass. The
        # Content-Length guard is the only thing that catches the truncation,
        # and it must fire even though md5 verification is enabled.
        short = b"SHORT"
        target = tmp_path / "GCF_000005845.2.fna.gz"
        session = _FakeDownloadSession(
            _StreamResp([short], content_length=1000),
            _StreamResp([short], content_length=1000),
        )
        with pytest.raises(DownloadError) as excinfo:
            _download_file(
                session,
                f"{DIR}GCF_000005845.2_ASM584v2_genomic.fna.gz",
                target,
                _md5(short),  # md5 matches the received bytes
                max_attempts=2,
                sleep=0,
                progress=None,
                label="GCF_000005845.2.fna.gz",
            )
        assert "incomplete download" in str(excinfo.value)
        assert session.calls == 2  # incomplete is retriable
        assert not target.exists()


class TestResolveDirErrors:
    @responses.activate
    def test_missing_directory_message_hints_removal(self):
        # Candidate manifest 404s and the parent listing 404s -> the assembly
        # directory is genuinely absent; the message must say so, not hint at a
        # server error.
        candidate = f"{DIR}md5checksums.txt"
        parent = f"{FTP_BASE}/all/GCF/000/005/845/"
        responses.add(responses.GET, candidate, status=404)
        responses.add(responses.GET, parent, status=404)
        session = make_session(1, None)
        with pytest.raises(DownloadError) as excinfo:
            resolve_dir(session, FTP_BASE, "GCF_000005845.2", "ASM584v2")
        msg = str(excinfo.value)
        assert "no FTP directory" in msg
        assert "removed or suppressed" in msg

    @responses.activate
    def test_server_error_message_says_retry(self):
        # A persistent 5xx on both the manifest and the parent listing must be
        # reported as a transient server error (retry later), NOT as a missing
        # directory (which would tell the user to check the accession instead).
        candidate = f"{DIR}md5checksums.txt"
        parent = f"{FTP_BASE}/all/GCF/000/005/845/"
        responses.add(responses.GET, candidate, status=503)
        responses.add(responses.GET, parent, status=503)
        session = make_session(1, None)
        with pytest.raises(DownloadError) as excinfo:
            resolve_dir(session, FTP_BASE, "GCF_000005845.2", "ASM584v2")
        msg = str(excinfo.value)
        assert "server error" in msg
        assert "retry later" in msg


class TestSupersededMessage:
    @responses.activate
    def test_no_formats_available_message_hints_superseded(self, tmp_path):
        # A resolved (previous) version whose sequence files were removed yields
        # zero files; the error must explain the version may be superseded and
        # how to recover (omit the version / change --formats).
        responses.add(
            responses.GET,
            f"{DIR}md5checksums.txt",
            body="abc  ./GCF_000005845.2_ASM584v2_assembly_report.txt\n",
        )
        session = make_session(3, None)
        download_session = make_session(3, None, retries=False)
        with pytest.raises(DownloadError) as excinfo:
            download_assembly(
                session,
                download_session,
                make_assembly(),
                ["fasta"],  # sequence file absent from the manifest
                tmp_path,
                FTP_BASE,
                force=False,
                ignore_md5=False,
                max_attempts=2,
                sleep=0,
            )
        msg = str(excinfo.value)
        assert "no requested formats available" in msg
        assert "superseded" in msg
        assert "omit the version" in msg


class TestNewFormats:
    @responses.activate
    def test_wgs_genpept_translated_cds_wire_to_live_suffixes(self, tmp_path):
        # Live-verified suffixes (GCF_000734955.1, a contig/WGS assembly):
        # _wgsmaster.gbff.gz, _protein.gpff.gz, _translated_cds.faa.gz. A typo in
        # the FORMATS suffix would silently mark the format "unavailable", so
        # pin the wiring: manifest name -> {accession}.{ext} output.
        wgs = b"WGSMASTER"
        gpff = b"GENPEPT"
        tcds = b"TRANSLATED"
        stem = "GCF_000005845.2_ASM584v2"
        responses.add(
            responses.GET,
            f"{DIR}md5checksums.txt",
            body=(
                f"{_md5(wgs)}  ./{stem}_wgsmaster.gbff.gz\n"
                f"{_md5(gpff)}  ./{stem}_protein.gpff.gz\n"
                f"{_md5(tcds)}  ./{stem}_translated_cds.faa.gz\n"
            ),
        )
        responses.add(responses.GET, f"{DIR}{stem}_wgsmaster.gbff.gz", body=wgs)
        responses.add(responses.GET, f"{DIR}{stem}_protein.gpff.gz", body=gpff)
        responses.add(responses.GET, f"{DIR}{stem}_translated_cds.faa.gz", body=tcds)
        session = make_session(3, None)
        download_session = make_session(3, None, retries=False)
        written, unavailable, failed = download_assembly(
            session,
            download_session,
            make_assembly(),
            ["wgs", "genpept", "translated-cds"],
            tmp_path,
            FTP_BASE,
            force=False,
            ignore_md5=False,
            max_attempts=2,
            sleep=0,
        )
        assert unavailable == []
        assert failed == []
        assert sorted(p.name for p in written) == [
            "GCF_000005845.2.gpff.gz",
            "GCF_000005845.2.translated_cds.faa.gz",
            "GCF_000005845.2.wgsmaster.gbff.gz",
        ]
        assert (tmp_path / "GCF_000005845.2.wgsmaster.gbff.gz").read_bytes() == wgs
