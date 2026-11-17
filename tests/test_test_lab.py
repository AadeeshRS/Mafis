"""Regression checks for the test harness and its loopback API."""

import base64
from http.client import HTTPConnection
import json
from threading import Thread
from time import monotonic, sleep

import pytest

from dashboard import server


@pytest.fixture
def request_dashboard(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "RUNS", tmp_path)
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.setenv(name, "")
    with server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler) as httpd:
        httpd.jobs = server.JobStore()
        thread = Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        def request(method, path, payload=None, **headers):
            connection = HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
            try:
                connection.request(method, path, body=json.dumps(payload) if payload is not None else None,
                                   headers={"Content-Type": "application/json", **headers})
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()

        try:
            yield request
        finally:
            httpd.shutdown()
            thread.join()


def test_dashboard_catalog_and_request_boundaries(request_dashboard):
    status, catalog = request_dashboard("GET", "/api/catalog")
    assert status == 200
    assert all(sample["available"] for sample in catalog["samples"])
    assert "all" in catalog["suites"]
    assert request_dashboard("POST", "/api/runs", {"kind": "suite", "group": "../../.env"})[0] == 400
    assert request_dashboard("POST", "/api/runs", {"kind": "key"}, Origin="https://other.example")[0] == 403
    assert request_dashboard("GET", "/.env")[0] == 404


def test_dashboard_missing_key_job_records_zero_requests(request_dashboard):
    status, job = request_dashboard("POST", "/api/runs", {"kind": "key"})
    assert status == 202
    job_url = f"/api/runs/{job['id']}"
    deadline = monotonic() + 15
    while job["status"] == "running" and monotonic() < deadline:
        status, job = request_dashboard("GET", job_url)
        assert status == 200
        if job["status"] == "running":
            sleep(0.1)
    assert job["status"] == "blocked"
    readiness = job["results"]["gemini_readiness.json"]
    assert readiness["blocker"] == "missing_credential"
    assert readiness["generation_requests"] == readiness["metadata_requests"] == 0
    status, artifact = request_dashboard("GET", f"{job_url}/gemini_readiness.json")
    assert status == 200
    assert artifact == readiness


def test_custom_pdf_command_uses_local_path_and_requires_live_confirmation(tmp_path):
    payload = {"kind": "sample", "case": "custom", "workflow": "full", "scenario": "clean", "mode": "mock",
               "title": "- Example report", "entity": "Example Inc", "source_url": "https://example.com/report.pdf",
               "pdf": base64.b64encode(b"%PDF-1.7\n").decode()}
    args, _, pdf = server.build_command(payload, tmp_path)
    assert "--live" not in args
    assert "--title=- Example report" in args
    assert str(tmp_path / "input.pdf") in args
    assert pdf == b"%PDF-1.7\n"
    with pytest.raises(ValueError, match="free-tier confirmation"):
        server.build_command({**payload, "mode": "live"}, tmp_path)
    with pytest.raises(ValueError, match="Upload a PDF"):
        server.build_command({**payload, "pdf": base64.b64encode(b"not a PDF").decode()}, tmp_path)


def test_dashboard_ollama_mode_needs_no_gemini_key(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "key_configured", lambda: False)
    payload = {"kind": "sample", "case": "apple_2024", "workflow": "full", "scenario": "clean", "mode": "ollama"}
    args, _, _ = server.build_command(payload, tmp_path)
    assert "--ollama" in args and "--live" not in args
    with pytest.raises(ValueError, match="offline mock"):
        server.build_command({**payload, "scenario": "corrected"}, tmp_path)
