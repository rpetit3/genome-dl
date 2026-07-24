"""Tests for genome_dl.providers.datasets."""

import time
from pathlib import Path

import pytest
import requests
import responses

from genome_dl.constants import DATASETS_API
from genome_dl.exceptions import ApiError, EmptyResultError, TaxonError
from genome_dl.providers.datasets import (
    _assembly_from_report,
    _RateLimiter,
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

    def test_versioned_previous_stale_by_default(self):
        # Default (allow_outdated=False): an explicit outdated pin is refused.
        v = versions((2, "current"), (1, "previous"))
        asm, action = select_for_input("GCF_000005845", 1, v)
        assert action == "stale"
        assert asm is None

    def test_versioned_previous_honored_with_allow_outdated(self):
        v = versions((2, "current"), (1, "previous"))
        asm, action = select_for_input("GCF_000005845", 1, v, allow_outdated=True)
        assert action == "outdated"
        assert asm.accession == "GCF_000005845.1"

    def test_versioned_previous_no_current_stale_by_default(self):
        v = versions((1, "previous"))
        asm, action = select_for_input("GCF_000005845", 1, v)
        assert action == "stale"
        assert asm is None

    def test_versioned_previous_no_current_honored_with_allow_outdated(self):
        v = versions((1, "previous"))
        asm, action = select_for_input("GCF_000005845", 1, v, allow_outdated=True)
        assert action == "outdated"
        assert asm.accession == "GCF_000005845.1"

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

    def test_emits_dynamic_infraspecific_keys(self):
        report = make_report()
        report["organism"]["infraspecific_names"] = {
            "isolate": "WHEZ1",
            "sex": "female",
        }
        row = metadata_row(_assembly_from_report(report), [])
        # No strain key present -> strain column empty, but the isolate/sex
        # identifiers are surfaced as their own keys instead of being dropped.
        assert row["strain"] == ""
        assert row["isolate"] == "WHEZ1"
        assert row["sex"] == "female"


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

    @responses.activate
    def test_5xx_storm_exhausts_with_retry_hint(self, mocker):
        # A persistent 5xx is retried by the adapter, then surfaced (not as a
        # urllib3 "Max retries exceeded" wall) as an ApiError that names the
        # status and tells the user the API may be busy -- retry later.
        mocker.patch("genome_dl.providers.datasets.time.sleep")
        url = f"{DATASETS_API}/genome/dataset_report"
        responses.add(responses.POST, url, status=503)
        session = make_session(3, None)
        with pytest.raises(ApiError) as excinfo:
            resolve_accessions(session, ["GCF_000005845"])
        msg = str(excinfo.value)
        assert "503" in msg
        assert "retry later" in msg
        # 3 attempts total = 1 initial + 2 adapter retries.
        assert len(responses.calls) == 3

    @responses.activate
    def test_api_error_surfaces_message_without_leaking_key(self):
        # NCBI's 4xx JSON body carries a human message and echoes the submitted
        # api-key; the ApiError must surface the message but never the key.
        responses.add(
            responses.POST,
            f"{DATASETS_API}/genome/dataset_report",
            status=400,
            json={"error": {"message": "API key invalid", "api-key": "SECRET123"}},
        )
        session = make_session(0, None)
        with pytest.raises(ApiError) as excinfo:
            resolve_accessions(session, ["GCF_000005845"])
        assert "API key invalid" in str(excinfo.value)
        assert "SECRET123" not in str(excinfo.value)

    @responses.activate
    def test_connection_error_gives_network_hint(self):
        # An unreachable API (offline / bad proxy / DNS) must surface a clean
        # network hint, not a wall of raw urllib3 connection-pool text.
        responses.add(
            responses.POST,
            f"{DATASETS_API}/genome/dataset_report",
            body=requests.exceptions.ConnectionError("Max retries exceeded"),
        )
        session = make_session(0, None)
        with pytest.raises(ApiError) as excinfo:
            resolve_accessions(session, ["GCF_000005845"])
        assert "check your network connection" in str(excinfo.value)


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

    @responses.activate
    def test_non_json_200_raises_apierror(self):
        # A proxy/captive-portal can return HTTP 200 with an HTML body; the
        # parse failure must surface as a clean ApiError, not a raw traceback.
        responses.add(
            responses.GET,
            f"{DATASETS_API}/taxonomy/taxon/Escherichia%20coli/dataset_report",
            body="<html><body>proxy login</body></html>",
            status=200,
            content_type="text/html",
        )
        session = make_session(1, None)
        with pytest.raises(ApiError):
            verify_taxon(session, "Escherichia coli")


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
        result, total = list_taxon_assemblies(
            session, "Escherichia coli", "refseq", ["all"]
        )
        assert [a.accession for a in result] == [
            "GCF_000005845.2",
            "GCF_000008865.2",
        ]
        assert total == 2

    @responses.activate
    def test_stops_early_at_limit(self):
        url = f"{DATASETS_API}/genome/taxon/Escherichia%20coli/dataset_report"
        responses.add(
            responses.GET,
            url,
            json={
                "total_count": 50,
                "reports": [
                    make_report("GCF_000005845.2"),
                    make_report("GCF_000008865.2"),
                ],
                "next_page_token": "T",
            },
        )
        session = make_session(3, None)
        result, total = list_taxon_assemblies(
            session, "Escherichia coli", "refseq", ["all"], limit=1
        )
        # Truncated to the limit and pagination stopped despite a next token.
        assert [a.accession for a in result] == ["GCF_000005845.2"]
        assert total == 50
        assert len(responses.calls) == 1
        assert responses.calls[0].request.params["page_size"] == "1"

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


class TestMakeSession:
    def test_total_attempts_semantics(self):
        adapter = make_session(3, None).get_adapter("https://x")
        assert adapter.max_retries.total == 2

    def test_single_attempt_no_retry(self):
        adapter = make_session(1, None).get_adapter("https://x")
        assert adapter.max_retries.total == 0

    def test_retries_disabled(self):
        adapter = make_session(3, None, retries=False).get_adapter("https://x")
        assert adapter.max_retries.total == 0

    def test_default_rate_limit_is_5_rps(self):
        session = make_session(3, None)
        assert session.rate_limiter._min_interval == pytest.approx(1 / 5)

    def test_api_key_raises_to_10_rps(self):
        session = make_session(3, "SECRET")
        assert session.rate_limiter._min_interval == pytest.approx(1 / 10)

    def test_rate_limit_disabled_has_no_limiter(self):
        session = make_session(3, None, rate_limit=False)
        assert not hasattr(session, "rate_limiter")

    def test_identity_encoding_sets_header(self):
        # F1: the byte-download session must request identity so Content-Length
        # matches the bytes written (NCBI transfer-gzips plain-text formats).
        session = make_session(3, None, identity_encoding=True)
        assert session.headers["Accept-Encoding"] == "identity"

    def test_default_encoding_allows_gzip(self):
        session = make_session(3, None)
        assert session.headers["Accept-Encoding"] != "identity"


class TestRateLimiter:
    def test_spaces_consecutive_calls(self):
        limiter = _RateLimiter(50)  # 0.02s minimum interval
        start = time.monotonic()
        for _ in range(3):
            limiter.acquire()
        # 3 calls => at least 2 inter-call intervals of 0.02s.
        assert time.monotonic() - start >= 0.04

    def test_nonpositive_rps_never_sleeps(self):
        limiter = _RateLimiter(0)
        start = time.monotonic()
        for _ in range(5):
            limiter.acquire()
        assert time.monotonic() - start < 0.01


class TestMultiLevelFilter:
    @responses.activate
    def test_multiple_levels_sent_as_repeated_params(self):
        # Regression: the REST API rejects a comma-joined assembly_level filter
        # (HTTP 400). Multiple levels must be repeated query params, which
        # requests encodes automatically from a list value.
        url = f"{DATASETS_API}/genome/taxon/Escherichia%20coli/dataset_report"
        responses.add(
            responses.GET,
            url,
            json={"total_count": 1, "reports": [make_report("GCF_000005845.2")]},
        )
        session = make_session(3, None)
        list_taxon_assemblies(
            session, "Escherichia coli", "refseq", ["complete", "chromosome"]
        )
        sent = responses.calls[0].request.url
        assert sent.count("filters.assembly_level=") == 2
        assert "complete_genome" in sent
        assert "chromosome" in sent
        assert "%2C" not in sent  # no comma-joined form


class TestNullNestedFields:
    def test_assembly_from_report_tolerates_nulls(self):
        # NCBI could return keys present-but-null; .get(k, {}) would not guard
        # that, so null must be coalesced to {} to avoid an AttributeError.
        report = {
            "accession": "GCF_000005845.2",
            "assembly_info": None,
            "organism": None,
            "assembly_stats": None,
        }
        asm = _assembly_from_report(report)
        assert asm.accession == "GCF_000005845.2"
        assert asm.assembly_name == ""
        assert asm.tax_id is None

    def test_metadata_row_tolerates_nulls(self):
        report = {
            "accession": "GCF_000005845.2",
            "assembly_info": None,
            "organism": None,
            "assembly_stats": None,
        }
        asm = make_assembly()
        asm.report = report
        row = metadata_row(asm, [])
        assert row["accession"] == "GCF_000005845.2"
        assert row["strain"] == ""
        assert row["biosample"] == ""


class TestResolveBatching:
    @responses.activate
    def test_large_lists_are_chunked(self):
        # >1000 bases must be split across multiple POSTs, not one oversized body.
        url = f"{DATASETS_API}/genome/dataset_report"
        responses.add(responses.POST, url, json={"reports": []})
        responses.add(responses.POST, url, json={"reports": []})
        session = make_session(3, None)
        bases = [f"GCF_{i:09d}" for i in range(1500)]
        resolve_accessions(session, bases)
        assert len(responses.calls) == 2
        import json as _json

        first_body = _json.loads(responses.calls[0].request.body)
        second_body = _json.loads(responses.calls[1].request.body)
        assert len(first_body["accessions"]) == 1000
        assert len(second_body["accessions"]) == 500


class TestRequestStreamRetry:
    @responses.activate
    def test_interrupted_stream_is_retried(self, mocker):
        # A response dropped mid-body (ChunkedEncodingError) is not covered by
        # the HTTPAdapter retry; _request retries it and succeeds on the next.
        mocker.patch("genome_dl.providers.datasets.time.sleep")
        url = f"{DATASETS_API}/taxonomy/taxon/Escherichia%20coli/dataset_report"
        responses.add(
            responses.GET,
            url,
            body=requests.exceptions.ChunkedEncodingError("Response ended prematurely"),
        )
        responses.add(
            responses.GET,
            url,
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
        result = verify_taxon(session, "Escherichia coli")
        assert result["tax_id"] == 562
        assert len(responses.calls) == 2

    @responses.activate
    def test_persistent_stream_drop_exhausts_to_apierror(self, mocker):
        mocker.patch("genome_dl.providers.datasets.time.sleep")
        url = f"{DATASETS_API}/taxonomy/taxon/Escherichia%20coli/dataset_report"
        responses.add(
            responses.GET,
            url,
            body=requests.exceptions.ChunkedEncodingError("Response ended prematurely"),
        )
        session = make_session(2, None)
        with pytest.raises(ApiError):
            verify_taxon(session, "Escherichia coli")
        assert len(responses.calls) == 2
