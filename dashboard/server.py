"""Loopback-only browser interface for the MAFIS test runner."""

import argparse
import base64
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from threading import Lock, Thread
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from dotenv import dotenv_values
from pydantic import HttpUrl, ValidationError

from memory.live_feed import FEED_ENV, FEED_NAME
from scripts.test_lab import OUTPUT, ROOT, SCENARIOS, SUITES, WORKFLOWS, samples, write_json


ASSETS = Path(__file__).with_name("static")
RUNS = OUTPUT / "dashboard"
MAX_PDF = 25 * 1024 * 1024
MAX_REQUEST = (MAX_PDF + 2) // 3 * 4 + 16384
MEMORY_JOBS = ("sample", "apple-benchmark", "evaluation", "coverage")
MEMORY_PAGE_BYTES = 256 * 1024
CHECKS = {
    "retrieval": ("Semantic retrieval", "Score MiniLM Hit@5, Recall@5 and passage coverage against labeled PDFs."),
    "evaluation": ("Offline comparison", "Compare the full workflow and single-model baseline on development cases."),
    "apple-benchmark": ("Apple benchmark · Local Ollama", "Run DeepSeek-R1 once and compare it with Full MAFIS on Apple FY2024."),
    "coverage": ("Source coverage", "Audit PDF coverage, missing sources and supported calculations across the fixture set."),
}
ARTIFACTS = ("report.md", "run_summary.json", "analysis_map.json", "evidence.json", "scenario.json",
             "gemini_readiness.json", "ollama_readiness.json", "retrieval.json", "results.json", "manifest.json",
             "source_coverage.json", "benchmark.md", "benchmark.json", "apple_baseline.md", "apple_mafis.md", "run.log")
RESULTS = ("scenario.json", "run_summary.json", "gemini_readiness.json", "ollama_readiness.json", "benchmark.json")
STATIC = {"/": ("index.html", "text/html"), "/styles.css": ("styles.css", "text/css"),
          "/app.js": ("app.js", "text/javascript")}


def now():
    return datetime.now(timezone.utc).isoformat()


def key_configured():
    names = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
    path = ROOT / ".env"
    local = dotenv_values(path) if path.is_file() else {}
    return any(os.environ.get(name, local.get(name)) for name in names)


def bounded_text(payload, name, limit, *, required=True):
    value = payload.get(name, "")
    if not isinstance(value, str) or len(value) > limit or any(ord(char) < 32 and char not in "\r\n\t" for char in value):
        raise ValueError(f"Enter at most {limit} characters for {name.replace('_', ' ')}.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"Enter a {name.replace('_', ' ')}.")
    return value


def build_command(payload, run_dir):
    kind = payload.get("kind")
    pdf = None
    if kind == "suite":
        group = bounded_text(payload, "group", 20)
        if group not in SUITES:
            raise ValueError("Select a test suite.")
        return [kind, "--group", group], SUITES[group][0], pdf
    if kind == "key":
        return [kind], "Gemini metadata check", pdf
    if kind == "ollama":
        return [kind], "Local Ollama check", pdf
    if isinstance(kind, str) and kind in CHECKS:
        return [kind], CHECKS[kind][0], pdf
    if kind != "sample":
        raise ValueError("Select a test to run.")
    case = bounded_text(payload, "case", 32)
    workflow = bounded_text(payload, "workflow", 20)
    scenario = bounded_text(payload, "scenario", 20)
    mode = bounded_text(payload, "mode", 20)
    available = samples()
    if workflow not in WORKFLOWS or scenario not in SCENARIOS or mode not in ("mock", "minilm", "ollama", "live"):
        raise ValueError("Select a workflow, scenario and execution mode.")
    if case != "custom" and case not in available:
        raise ValueError("Select a sample document or upload a PDF.")
    if scenario in ("corrected", "persistent") and workflow != "full":
        raise ValueError("Evidence gap scenarios require the full pipeline.")
    if mode == "ollama" and scenario in ("corrected", "persistent"):
        raise ValueError("Injected evidence gaps require an offline mock model.")
    args = [kind, "--workflow", workflow, "--scenario", scenario]
    label = SCENARIOS[scenario][0]
    if case == "custom":
        title = bounded_text(payload, "title", 200)
        entity = bounded_text(payload, "entity", 120)
        try:
            source_url = str(HttpUrl(bounded_text(payload, "source_url", 2083)))
        except ValidationError:
            raise ValueError("Enter an HTTP or HTTPS source URL.") from None
        encoded = payload.get("pdf")
        if not isinstance(encoded, str):
            raise ValueError("Choose a PDF to upload.")
        try:
            pdf = base64.b64decode(encoded, validate=True)
        except ValueError:
            raise ValueError("The uploaded PDF could not be read.") from None
        if len(pdf) > MAX_PDF or not pdf.startswith(b"%PDF-"):
            raise ValueError("Upload a PDF of up to 25 MiB.")
        args.extend(("--pdf", str(run_dir / "input.pdf"), "--title=" + title, "--entity=" + entity,
                     "--source-url=" + source_url))
    else:
        args.extend(("--case", case))
        entity = available[case]["document"]["entity"]
    question = bounded_text(payload, "question", 1000, required=False)
    if scenario == "document" and not question:
        raise ValueError("Enter a question for Ask the document.")
    if question:
        args.append("--question=" + question)
        if scenario == "clean":
            label = "Custom question"
    if mode == "minilm":
        args.append("--real-embeddings")
    if mode == "ollama":
        args.append("--ollama")
    if mode == "live":
        if scenario not in ("clean", "document") or payload.get("free_tier_confirmed") is not True:
            raise ValueError("Live runs require an analysis or document question and free-tier confirmation.")
        if not key_configured():
            raise ValueError("Configure GEMINI_API_KEY or GOOGLE_API_KEY in .env first.")
        budget = payload.get("request_budget")
        if type(budget) is not int or not 1 <= budget <= 12:
            raise ValueError("Set a live transport attempt budget between 1 and 12.")
        args.extend(("--live", "--free-tier-confirmed", "--request-budget", str(budget)))
    return args, f"{entity} · {label}", pdf


class JobStore:
    def __init__(self):
        self.lock = Lock()
        self.jobs = {}
        self.active = None
        for path in RUNS.glob("*/job.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                if job["id"] != path.parent.name:
                    continue
                if job["status"] == "running":
                    job.update(status="interrupted", finished_at=now())
                    write_json(path, job)
                self.jobs[job["id"]] = job
            except (OSError, ValueError, TypeError, KeyError):
                continue

    def list(self):
        with self.lock:
            return sorted(self.jobs.values(), key=lambda job: job["started_at"], reverse=True)[:50]

    def start(self, payload):
        job_id = uuid4().hex
        directory = RUNS / job_id
        args, label, pdf = build_command(payload, directory)
        with self.lock:
            if self.active:
                raise RuntimeError("Another test is running. Wait for it to finish.")
            directory.mkdir(parents=True, exist_ok=False)
            if pdf is not None:
                (directory / "input.pdf").write_bytes(pdf)
            mode = payload["mode"] if args[0] == "sample" else "metadata" if args[0] == "key" else "offline"
            job = dict(id=job_id, label=label, kind=args[0], mode=mode, status="running", started_at=now())
            write_json(directory / "job.json", job)
            self.jobs[job_id] = job
            self.active = job_id
            Thread(target=self.execute, args=(job, args, directory), daemon=True).start()
        return job

    def execute(self, job, args, directory):
        command = [sys.executable, "-u", "-m", "scripts.test_lab", *args, "--output", str(directory)]
        env = {**os.environ, "PYTHONUTF8": "1", "ANONYMIZED_TELEMETRY": "False"}
        env.pop(FEED_ENV, None)
        if job["kind"] in MEMORY_JOBS:
            env[FEED_ENV] = str(directory / FEED_NAME)
        if job["mode"] not in ("metadata", "live"):
            env.update(GEMINI_API_KEY="", GOOGLE_API_KEY="")
        with (directory / "run.log").open("wb") as log:
            try:
                exit_code = subprocess.call(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            except OSError as exc:
                log.write(f"Could not start test runner ({type(exc).__name__}).\n".encode())
                exit_code = 1
        status = "failed" if exit_code else "completed" if job["kind"] == "apple-benchmark" else "passed"
        if job["kind"] in ("key", "sample"):
            name = "gemini_readiness.json" if job["kind"] == "key" else "scenario.json"
            path = directory / name
            if path.exists():
                result = json.loads(path.read_text(encoding="utf-8"))
                if result.get("blocker") == "missing_credential":
                    status = "blocked"
                if job["kind"] == "sample" and exit_code == 0:
                    answer_status = result.get("answer", {}).get("status")
                    custom = result.get("expected_report_status") is None
                    if custom and answer_status in ("unsupported", "unavailable"):
                        status = "unanswered"
                    elif result["scenario_passed"] is None or custom and answer_status == "partial":
                        status = "completed"
        readiness = directory / "ollama_readiness.json"
        if exit_code and readiness.is_file() and json.loads(readiness.read_text(encoding="utf-8"))["status"] != "ready":
            status = "blocked"
        finished = {**job, "status": status, "exit_code": exit_code, "finished_at": now()}
        with self.lock:
            self.active = None
            self.jobs[job["id"]] = finished
            write_json(directory / "job.json", finished)

    def detail(self, job_id):
        with self.lock:
            job = self.jobs[job_id]
        directory = RUNS / job_id
        artifacts = [name for name in ARTIFACTS if (directory / name).is_file()]
        log = ""
        clipped = False
        if "run.log" in artifacts:
            with (directory / "run.log").open("rb") as handle:
                size = handle.seek(0, os.SEEK_END)
                clipped = size > 32000
                handle.seek(max(size - 32000, 0))
                log = handle.read(32000).decode("utf-8", errors="replace")
        results = {}
        if job["status"] != "running":
            for name in RESULTS:
                if name in artifacts:
                    results[name] = json.loads((directory / name).read_text(encoding="utf-8"))
        return {**job, "artifacts": artifacts, "log": log, "log_clipped": clipped, "results": results}

    def memory(self, job_id, cursor):
        # Read job status before the feed. A terminal status means the worker has
        # closed the file, so the final response can safely finish at EOF.
        with self.lock:
            job = self.jobs[job_id]
        response = {"status": job["status"], "source": None, "entries": [], "stages": [],
                    "cursor": cursor, "has_more": False}
        if job["kind"] not in MEMORY_JOBS:
            return response
        directory = RUNS / job_id
        try:
            feed = (directory / FEED_NAME).open("rb")
        except FileNotFoundError:
            if job["status"] == "running":
                return {**response, "source": "live"}
            snapshot = directory / ("mafis/evidence.json" if job["kind"] == "apple-benchmark" else "evidence.json")
            if snapshot.is_file():
                evidence = json.loads(snapshot.read_text(encoding="utf-8"))
                categories = {"sources": "source", "claims": "claim", "calculations": "calculation",
                              "verification_records": "verification", "contradictions": "contradiction",
                              "retry_decisions": "retry", "gate_history": "health_gate"}
                return {**response, "source": "snapshot", "entries": [
                    {"run_id": evidence["run_id"], "kind": kind, "record": record}
                    for key, kind in categories.items() for record in evidence.get(key, [])
                ]}
            return {**response, "source": "live"}

        with feed:
            if cursor:
                feed.seek(cursor - 1)
                if feed.read(1) != b"\n":
                    raise ValueError("Invalid Shared Memory cursor.")
            position = cursor
            entries = []
            while position - cursor < MEMORY_PAGE_BYTES:
                line = feed.readline()
                if not line.endswith(b"\n"):
                    break
                entries.extend(json.loads(line))
                position = feed.tell()
            has_more = position - cursor >= MEMORY_PAGE_BYTES and bool(feed.read(1))
        stages = [entry["record"] for entry in entries if entry["kind"] == "stage"]
        records = [entry for entry in entries if entry["kind"] != "stage"]
        return {**response, "source": "live", "entries": records, "stages": stages,
                "cursor": position, "has_more": has_more}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_data(self, data, media_type, status=HTTPStatus.OK, *, filename=None):
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, result, status=HTTPStatus.OK):
        self.send_data(json.dumps(result).encode("utf-8"), "application/json", status)

    def trusted_host(self):
        port = self.server.server_port
        return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def reject_post(self, message, status):
        # Closing a Windows socket with a small unread body can reset the response.
        length = self.headers.get("Content-Length", "")
        if len(length) <= 4 and length.isascii() and length.isdecimal() and int(length) <= 4096:
            timeout = self.connection.gettimeout()
            self.connection.settimeout(0.5)
            try:
                self.rfile.read(int(length))
            except OSError:
                pass
            finally:
                self.connection.settimeout(timeout)
        return self.send_json({"error": message}, status)

    def do_GET(self):
        if not self.trusted_host():
            return self.send_json({"error": "Use the dashboard's local address."}, HTTPStatus.FORBIDDEN)
        url = urlsplit(self.path)
        path = url.path
        jobs = self.server.jobs
        if path in STATIC:
            filename, media = STATIC[path]
            return self.send_data((ASSETS / filename).read_bytes(), f"{media}; charset=utf-8")
        if path == "/api/catalog":
            cases = [dict(id=case_id, entity=case["document"]["entity"], title=case["document"]["title"],
                          question=case["question"], available=(ROOT / case["document"]["path"]).is_file())
                     for case_id, case in samples().items()]
            return self.send_json({"samples": cases, "suites": SUITES, "workflows": WORKFLOWS,
                                   "scenarios": SCENARIOS, "checks": CHECKS})
        if path == "/api/runs":
            return self.send_json({"jobs": jobs.list(), "key_configured": key_configured()})
        sample = re.fullmatch(r"/samples/([a-z0-9_]+)\.pdf", path)
        if sample and (case := samples().get(sample[1])):
            pdf = ROOT / case["document"]["path"]
            if pdf.is_file():
                return self.send_data(pdf.read_bytes(), "application/pdf", filename=f"{sample[1]}.pdf")
        run = re.fullmatch(r"/api/runs/([a-f0-9]{32})(?:/([a-z_.]+))?", path)
        if run and run[1] in jobs.jobs:
            if run[2] is None:
                return self.send_json(jobs.detail(run[1]))
            if run[2] == "memory":
                cursor = parse_qs(url.query, keep_blank_values=True).get("after", ["0"])[0]
                if not re.fullmatch(r"[0-9]{1,16}", cursor):
                    return self.send_json({"error": "Invalid Shared Memory cursor."}, HTTPStatus.BAD_REQUEST)
                try:
                    return self.send_json(jobs.memory(run[1], int(cursor)))
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            artifact = RUNS / run[1] / run[2]
            if run[2] in ARTIFACTS and artifact.is_file():
                return self.send_data(artifact.read_bytes(), "text/plain; charset=utf-8", filename=run[2])
        return self.send_json({"error": "File or run not found."}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        host = self.headers.get("Host")
        if not self.trusted_host() or self.headers.get("Origin", f"http://{host}") != f"http://{host}":
            return self.reject_post("Requests must come from the local dashboard.", HTTPStatus.FORBIDDEN)
        if self.path != "/api/runs":
            return self.reject_post("Unknown endpoint.", HTTPStatus.NOT_FOUND)
        if self.headers.get_content_type() != "application/json":
            return self.reject_post("Expected a JSON request.", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0:
                raise ValueError("A test request is required.")
            if size > MAX_REQUEST:
                return self.send_json({"error": "Upload a PDF of up to 25 MiB."}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError("Expected a test request object.")
            job = self.server.jobs.start(data)
        except ValueError as exc:
            return self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except RuntimeError as exc:
            return self.send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
        return self.send_json(job, HTTPStatus.ACCEPTED)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        server.jobs = JobStore()
        print(f"MAFIS Test Lab is running at http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nDashboard stopped.")


if __name__ == "__main__":
    main()
