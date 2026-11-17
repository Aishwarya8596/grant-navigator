"""Verify notice provenance, page evidence, and nonfatal retrieval failures."""

from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import re
from types import SimpleNamespace

import httpx
import pytest
from pypdf import PdfReader

from grant_navigator.tools import notices


ROOT = Path(__file__).resolve().parents[1]
SAVED_PDF = ROOT / "data/notices/FY27_ASNCompetitiveNotice_Final.508.pdf"
REAL_CATALOG = json.loads((ROOT / "data/notices/catalog.json").read_text())


@pytest.fixture
def isolated_catalog(tmp_path, monkeypatch):
    notice_dir = tmp_path / "data/notices"
    notice_dir.mkdir(parents=True)
    monkeypatch.setattr(notices, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(notices, "NOTICE_DIRECTORY", notice_dir)
    monkeypatch.setattr(notices, "CATALOG_PATH", notice_dir / "catalog.json")
    monkeypatch.setattr(notices, "DOWNLOAD_DIRECTORY", tmp_path / "data/downloads")

    def configure(data=None, *, local=True, overrides=None):
        if data is None:
            data = SAVED_PDF.read_bytes()
        entry = dict(REAL_CATALOG["notices"][0])
        entry["sha256"] = sha256(data).hexdigest()
        entry.update(overrides or {})
        notices.CATALOG_PATH.write_text(json.dumps({"schema_version": 1, "notices": [entry]}))
        if local and not Path(entry["local_path"]).is_absolute() and ".." not in Path(entry["local_path"]).parts:
            path = tmp_path / entry["local_path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return entry, data

    return configure


def mock_download(monkeypatch, data, *, status=200, headers=None, stream_body=False):
    calls = []

    @contextmanager
    def fake_stream(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        options = {"stream": httpx.ByteStream(data)} if stream_body else {"content": data}
        response = httpx.Response(
            status, headers=headers, request=httpx.Request(method, url), **options,
        )
        try:
            yield response
        finally:
            response.close()

    monkeypatch.setattr(notices.httpx, "stream", fake_stream)
    return calls


def test_real_notice_returns_page_bound_evidence_and_snapshot_provenance():
    result = notices.read_grant_notice(363696)

    assert result["status"] == "success"
    assert result["opportunity_number"] == "AC-08-28-26"
    assert result["page_count"] == result["pages_searched"] == 28
    assert result["retrieval_mode"] == "saved_snapshot"
    assert result["retrieved_at_utc"] is None
    assert result["snapshot_captured_at_utc"].startswith("2026-11-10T")
    assert result["currentness_verified"] is False
    assert result["eligibility_status"] == "not_assessed"
    assert result["source_sha256"] == sha256(SAVED_PDF.read_bytes()).hexdigest()
    pages = [re.sub(r"\s+", " ", page.extract_text() or "").strip() for page in PdfReader(SAVED_PDF).pages]
    assert len(result["excerpts"]) == 6
    assert {1, 7, 8} <= {excerpt["page_number"] for excerpt in result["excerpts"]}
    assert 2 not in {excerpt["page_number"] for excerpt in result["excerpts"]}  # Skip navigation-only TOC.
    assert any(
        "well in advance of AmeriCorps deadlines" in excerpt["text"]
        for excerpt in result["excerpts"] if excerpt["page_number"] == 1
    )
    assert any(
        "only one state must apply through" in excerpt["text"]
        for excerpt in result["excerpts"] if excerpt["page_number"] == 8
    )
    for excerpt in result["excerpts"]:
        page = excerpt["page_number"]
        assert excerpt["text"] in pages[page - 1]
        assert len(excerpt["text"]) <= notices.EXCERPT_CHARACTERS
        assert excerpt["citation_url"] == f"{result['source_url']}#page={page}"
        assert f":p{page}:" in excerpt["evidence_id"]
        assert result["source_sha256"][:16] in excerpt["evidence_id"]


def test_focused_query_is_bounded_and_evidence_ids_are_stable():
    focus = "only one state apply through commissions"
    first = notices.read_grant_notice(363696, focus, max_excerpts=1)
    second = notices.read_grant_notice(363696, focus, max_excerpts=1)

    assert first["status"] == "success"
    assert len(first["excerpts"]) == 1
    assert first["excerpts"][0]["page_number"] == 8
    assert "only one state must apply through" in first["excerpts"][0]["text"]
    assert first["excerpts"] == second["excerpts"]


@pytest.mark.parametrize("focus", [
    notices.DEFAULT_FOCUS,
    "cost sharing matching requirement",
    "cost reimbursement matching funds fixed amount grants",
])
def test_cost_query_preserves_different_conditions_for_funding_mechanisms(focus):
    result = notices.read_grant_notice(363696, focus, max_excerpts=6)
    texts = [excerpt["text"] for excerpt in result["excerpts"]]
    assert result["status"] == "success"
    assert any("Cost Reimbursement Grants Applicants are required to match" in text for text in texts)
    assert any("no cost share or matching requirement for fixed amount grants" in text for text in texts)
    assert all(not re.search(r"(?:\.\s*){6,}", text) for text in texts)
    if focus == notices.DEFAULT_FOCUS:
        assert {1, 8} <= {excerpt["page_number"] for excerpt in result["excerpts"]}


def test_unknown_opportunity_has_explicit_unavailable_result_without_network(monkeypatch):
    def no_download(source):
        pytest.fail("An uncataloged opportunity must not request a PDF")

    monkeypatch.setattr(notices, "_download_pdf", no_download)
    result = notices.read_grant_notice(999999)
    assert result["status"] == "notice_unavailable"
    assert result["excerpts"] == []
    assert result["eligibility_status"] == "not_assessed"


@pytest.mark.parametrize("arguments", [
    {"opportunity_id": 0}, {"opportunity_id": True}, {"opportunity_id": "363696"},
    {"opportunity_id": 363696, "focus": ""},
    {"opportunity_id": 363696, "focus": "x" * 501},
    {"opportunity_id": 363696, "focus": "What are the?"},
    {"opportunity_id": 363696, "max_excerpts": 0},
    {"opportunity_id": 363696, "max_excerpts": True},
    {"opportunity_id": 363696, "max_excerpts": 9},
])
def test_invalid_requests_are_nonfatal(arguments):
    result = notices.read_grant_notice(**arguments)
    assert result["status"] == "invalid_request"
    assert result["excerpts"] == []


def test_readable_document_with_no_query_match_does_not_imply_absent_rule():
    result = notices.read_grant_notice(363696, "zzyzxunmatchabletardigrade")
    assert result["status"] == "no_matching_excerpts"
    assert result["page_count"] == 28
    assert result["excerpts"] == []
    assert "does not establish that the rule is absent" in result["message"]


def test_changed_saved_file_is_rejected_before_extraction_or_network(isolated_catalog, monkeypatch):
    entry, _ = isolated_catalog()
    (notices.PROJECT_ROOT / entry["local_path"]).write_bytes(b"%PDF-different-content")

    def no_read(*args, **kwargs):
        pytest.fail("Unverified bytes must not be parsed or replaced from the network")

    monkeypatch.setattr(notices, "_page_texts", no_read)
    monkeypatch.setattr(notices, "_download_pdf", no_read)
    result = notices.read_grant_notice(363696)
    assert result["status"] == "notice_changed"
    assert result["excerpts"] == []


def test_missing_saved_pdf_downloads_only_reviewed_source_and_reuses_verified_cache(isolated_catalog, monkeypatch):
    entry, data = isolated_catalog(local=False)
    calls = mock_download(monkeypatch, data)
    first = notices.read_grant_notice(363696, "deadline", max_excerpts=1)

    assert first["status"] == "success"
    assert first["retrieval_mode"] == "downloaded_verified_snapshot"
    assert first["retrieved_at_utc"]
    assert first["snapshot_captured_at_utc"].startswith("2026-11-10T")
    assert calls == [{
        "method": "GET", "url": entry["source_url"],
        "timeout": 15.0, "follow_redirects": False,
    }]
    second = notices.read_grant_notice(363696, "deadline", max_excerpts=1)
    assert second["status"] == "success"
    assert second["retrieved_at_utc"] == first["retrieved_at_utc"]
    assert second["excerpts"] == first["excerpts"]
    assert len(calls) == 1


@pytest.mark.parametrize("stream_body", [False, True])
def test_download_size_limit_applies_to_header_and_unannounced_stream(isolated_catalog, monkeypatch, stream_body):
    _, data = isolated_catalog(local=False)
    monkeypatch.setattr(notices, "MAX_DOWNLOAD_BYTES", 1000)
    mock_download(monkeypatch, data, stream_body=stream_body)
    result = notices.read_grant_notice(363696)
    assert result["status"] == "notice_unreadable"
    assert result["excerpts"] == []
    assert not notices.DOWNLOAD_DIRECTORY.exists()


@pytest.mark.parametrize("status", [302, 503])
def test_redirect_or_http_failure_remains_explicit_unavailable(isolated_catalog, monkeypatch, status):
    _, data = isolated_catalog(local=False)
    mock_download(monkeypatch, data, status=status, headers={"location": "https://different.gov/notice.pdf"})
    result = notices.read_grant_notice(363696)
    assert result["status"] == "notice_unavailable"
    assert result["excerpts"] == []


def test_download_with_changed_digest_is_not_saved(isolated_catalog, monkeypatch):
    isolated_catalog(local=False)
    mock_download(monkeypatch, b"%PDF-unreviewed-change")
    result = notices.read_grant_notice(363696)
    assert result["status"] == "notice_changed"
    assert not notices.DOWNLOAD_DIRECTORY.exists()


def test_invalid_pdf_with_matching_digest_is_unreadable(isolated_catalog):
    isolated_catalog(b"%PDF-1.7\nnot-a-usable-pdf")
    result = notices.read_grant_notice(363696)
    assert result["status"] == "notice_unreadable"
    assert result["excerpts"] == []


@pytest.mark.parametrize("reader", [
    SimpleNamespace(is_encrypted=True),
    SimpleNamespace(is_encrypted=False, pages=[SimpleNamespace(extract_text=lambda: "")]),
])
def test_encrypted_or_image_only_notices_are_not_treated_as_read(reader, isolated_catalog, monkeypatch):
    isolated_catalog()
    monkeypatch.setattr(notices, "PdfReader", lambda *args, **kwargs: reader)
    result = notices.read_grant_notice(363696)
    assert result["status"] == "notice_unreadable"
    assert result["excerpts"] == []


def test_extraction_error_is_nonfatal_to_research(isolated_catalog, monkeypatch):
    isolated_catalog()

    def extract_text():
        raise NotImplementedError("Simulated unsupported PDF encoding")

    monkeypatch.setattr(notices, "PdfReader", lambda *args, **kwargs: SimpleNamespace(
        is_encrypted=False, pages=[SimpleNamespace(extract_text=extract_text)]
    ))
    result = notices.read_grant_notice(363696)
    assert result["status"] == "notice_unreadable"
    assert result["excerpts"] == []


@pytest.mark.parametrize("local_path", ["../outside.pdf", "/private/tmp/outside.pdf", "data/notices/file.txt"])
def test_catalog_paths_cannot_escape_notice_directory(isolated_catalog, local_path):
    isolated_catalog(local=False, overrides={"local_path": local_path})
    result = notices.read_grant_notice(363696)
    assert result["status"] == "notice_unavailable"


def test_symlink_cannot_escape_notice_directory(isolated_catalog):
    entry, data = isolated_catalog(local=False)
    outside = notices.PROJECT_ROOT / "outside.pdf"
    outside.write_bytes(data)
    (notices.PROJECT_ROOT / entry["local_path"]).symlink_to(outside)
    result = notices.read_grant_notice(363696)
    assert result["status"] == "notice_unavailable"


@pytest.mark.parametrize("source_url", [
    "http://agency.gov/notice.pdf", "https://example.com/notice.pdf",
    "file:///etc/passwd", "https://user:pass@agency.gov/notice.pdf",
])
def test_catalog_download_sources_must_be_reviewed_government_https(isolated_catalog, source_url):
    isolated_catalog(overrides={"source_url": source_url})
    result = notices.read_grant_notice(363696)
    assert result["status"] == "notice_unavailable"


def test_duplicate_catalog_bindings_are_not_used(isolated_catalog):
    entry, _ = isolated_catalog()
    notices.CATALOG_PATH.write_text(json.dumps({"schema_version": 1, "notices": [entry, entry]}))
    result = notices.read_grant_notice(363696)
    assert result["status"] == "notice_unavailable"


def test_missing_opportunity_number_invalidates_catalog_binding(isolated_catalog):
    isolated_catalog(overrides={"opportunity_number": ""})
    result = notices.read_grant_notice(363696)
    assert result["status"] == "notice_unavailable"


def test_tampered_download_metadata_is_not_reported_as_valid_provenance(isolated_catalog, monkeypatch):
    _, data = isolated_catalog(local=False)
    mock_download(monkeypatch, data)
    first = notices.read_grant_notice(363696, "deadline", max_excerpts=1)
    assert first["status"] == "success"
    metadata = next(notices.DOWNLOAD_DIRECTORY.glob("*.json"))
    record = json.loads(metadata.read_text())
    record["source_url"] = "https://other.gov/unreviewed.pdf"
    metadata.write_text(json.dumps(record))
    second = notices.read_grant_notice(363696)
    assert second["status"] == "notice_unavailable"
    assert second["excerpts"] == []

