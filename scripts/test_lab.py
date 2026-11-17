"""Repeatable MAFIS checks shared by the terminal and the local dashboard."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "test_lab"
FIXTURES = ROOT / "tests" / "fixtures"
SAMPLE_IDS = ("nvidia_2024", "apple_2024", "coca_cola_2024", "amd_2024")
WORKFLOWS = {"phase1": "Phase 1", "extended": "Extended", "full": "Full pipeline"}
SCENARIOS = {
    "clean": ("Annual financial health", "Extract annual facts and calculate growth, margins and liquidity."),
    "corrected": ("Recoverable evidence gap", "Omit net income once and expect a successful targeted retry."),
    "persistent": ("Persistent evidence gap", "Omit net income twice and expect a partial report after one retry."),
    "missing": ("Missing document", "Expect a partial report and zero model calls."),
    "unsupported": ("Unsupported quarterly request", "Expect a partial report and zero model calls."),
}
SUITES = {
    "all": ("Full regression", "Run every existing pytest check.", ()),
    "sources": ("Sources & retrieval", "PDF parsing, source attribution, Chroma filters and citation inputs.",
                ("ingest", "retrieval", "multi_report", "closeout_sources", "document_agent")),
    "financial": ("Financial engine & memory", "Decimal calculations, input validation and claim versioning.",
                  ("financial_engine", "financial_agent", "shared_memory", "phase2_memory")),
    "verification": ("Verification & reporting", "Eligibility, source citations, dated market/risk and exclusions.",
                     ("verification_agent", "market_risk", "report_agent", "report_exclusions", "batch1_review_fixes")),
    "workflow": ("Workflow & reasoning", "Routing, all three workflows, Bull/Bear, Critic and targeted corrections.",
                 ("planner", "pipeline", "batch1_integration", "batch2_full", "batch2_reasoning", "closeout_regressions", "test_lab")),
    "provider": ("Provider & evaluation", "Mock SDK failures, retry budgets, baselines and evaluation metrics.",
                 ("gemini", "provider_reliability", "evaluation", "evaluation_cli_budget", "batch2_evaluation")),
}


def samples():
    cases = json.loads((FIXTURES / "batch2_cases.json").read_text(encoding="utf-8"))["cases"]
    by_id = {case["case_id"]: case for case in cases}
    return {case_id: by_id[case_id] for case_id in SAMPLE_IDS}


def run_suite(suite, output):
    files = [f"tests/test_{name}.py" for name in SUITES[suite][2]]
    # Empty keys also prevent python-dotenv from loading a repository key.
    offline_env = {**os.environ, "GEMINI_API_KEY": "", "GOOGLE_API_KEY": "", "ANONYMIZED_TELEMETRY": "False"}
    return subprocess.call([sys.executable, "-m", "pytest", "-q", "--color=no", "--basetemp",
                            str(output / "pytest"), *files], cwd=ROOT, env=offline_env)


def sample_run(args, output):
    from graph import DocumentInput, run_extended_pipeline, run_full_pipeline, run_pipeline, save_outputs
    from rag.market_sources import ingest_market_snapshot
    from rag.retriever import SharedRetriever
    from tests.batch2_fakes import Batch2MockLLM

    if args.scenario in ("corrected", "persistent") and args.workflow != "full":
        raise ValueError("Evidence gap scenarios require the full pipeline.")
    if args.live and (args.scenario != "clean" or not args.free_tier_confirmed):
        raise ValueError("Live runs require the annual financial health scenario and free-tier confirmation.")
    if args.live and not 1 <= args.request_budget <= 12:
        raise ValueError("The live transport attempt budget must be between 1 and 12.")

    case = samples()[args.case]
    question = args.question or ("Assess annual financial health, revenue growth, profitability and liquidity"
                                 if args.pdf else case["question"])
    document = dict(case["document"])
    if args.pdf:
        if not (args.source_url and args.title and args.entity):
            raise ValueError("Provide a source URL, document title and company with your PDF.")
        document = dict(path=args.pdf, source_url=args.source_url, title=args.title, entity=args.entity)
    document["path"] = str((ROOT / document["path"]).resolve())
    if args.scenario == "unsupported":
        question = "Assess Q2 quarterly financial performance"
    document = None if args.scenario == "missing" else DocumentInput.model_validate(document)

    extraction_attempts = 0

    def omit_net_income(response, payload):
        nonlocal extraction_attempts
        if payload["task"] == "document_extraction":
            extraction_attempts += 1
            if args.scenario == "persistent" or extraction_attempts == 1:
                response["primitives"] = [p for p in response["primitives"] if p["metric"] != "net_income"]
        return response

    mock = Batch2MockLLM(transform=omit_net_income if args.scenario in ("corrected", "persistent") else None)
    if args.live:
        from config import DOCUMENT_MODEL, FINANCIAL_MODEL
        from gemini import GeminiAdapter, GeminiSettings, credential

        if not credential():
            raise ValueError("Configure GEMINI_API_KEY or GOOGLE_API_KEY in .env first.")
        budget = [args.request_budget]
        document_model = GeminiAdapter(GeminiSettings.from_env(DOCUMENT_MODEL), allow_live=True, request_budget=budget)
        financial_model = GeminiAdapter(GeminiSettings.from_env(FINANCIAL_MODEL), allow_live=True, request_budget=budget)
    else:
        document_model = financial_model = mock

    print(f"{WORKFLOWS[args.workflow]} | {SCENARIOS[args.scenario][0]}", flush=True)
    real_embeddings = args.real_embeddings or args.live
    print(f"Models: {'live Gemini' if args.live else 'offline mocks'} | Retrieval: {'MiniLM' if real_embeddings else 'test hash embeddings'}", flush=True)
    if real_embeddings:
        retriever = SharedRetriever(path=output / "index")
    else:
        from chromadb import EphemeralClient
        from chromadb.config import Settings
        from tests.conftest import HashTestEmbedder

        retriever = SharedRetriever(client=EphemeralClient(settings=Settings(anonymized_telemetry=False)),
                                    embedder=HashTestEmbedder(), embedding_model="test-hash-v1")

    options = dict(retriever=retriever, document_llm=document_model, financial_llm=financial_model)
    if args.workflow != "phase1":
        market = ingest_market_snapshot(FIXTURES / "market_snapshots/fomc_2024_01_31.json", retriever=retriever)
        options.update(market_filters={"doc_id": market.source.source_id, "kind": "narrative"},
                       risk_categories=("financial", "macro"))
    if args.workflow == "full":
        options.update(bull_llm=document_model, bear_llm=document_model, critic_llm=document_model)
    runner = {"phase1": run_pipeline, "extended": run_extended_pipeline, "full": run_full_pipeline}[args.workflow]
    state = runner(question, document, **options)
    save_outputs(state, output, adapters=(document_model, financial_model))

    memory = state["memory"]
    report_status = state["report"].status
    expected = "partial" if args.scenario in ("persistent", "missing", "unsupported") else "success"
    if args.scenario == "clean" and (args.pdf or args.question):
        expected = None
    checks = {} if expected is None else {f"Report is {expected}": report_status == expected}
    if args.scenario in ("missing", "unsupported"):
        checks["No model calls"] = not mock.calls
    if args.scenario in ("corrected", "persistent"):
        checks["One targeted retry"] = extraction_attempts == 2 and memory.retry_budget_remaining == 0
    calls = args.request_budget - budget[0] if args.live else 0
    if args.live:
        checks["Generation attempted"] = calls > 0
        checks["Live report succeeded"] = report_status == "success"

    result = {
        "report_status": report_status, "expected_report_status": expected, "checks": checks,
        "scenario_passed": all(checks.values()) if checks else None,
        "model_execution": "Live Gemini" if args.live else "Offline mock",
        "generation_requests": calls, "mock_model_calls": len(mock.calls),
        "retry_nodes": state.get("retry_execution", {}).get("nodes", []),
        "calculations": {c.operation: str(c.display_value) for c in memory.get_calculations()
                         if memory.get_calculation_freshness(c.calculation_ref) == "current"},
    }
    write_json(output / "scenario.json", result)
    print(json.dumps(result, indent=2))
    return int(result["scenario_passed"] is False)


def write_json(path, result):
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def check_key(output):
    from config import DOCUMENT_MODEL, FINANCIAL_MODEL, PRIMARY_MODEL
    from scripts.live_readiness import probe

    result = probe(model_ids=(PRIMARY_MODEL, DOCUMENT_MODEL, FINANCIAL_MODEL))
    write_json(output / "gemini_readiness.json", result)
    print(json.dumps(result, indent=2))
    return int(not result["models"] or not all(model["available"] for model in result["models"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    suite = commands.add_parser("suite", help="Run the full pytest regression or a focused group")
    suite.add_argument("--group", choices=SUITES, default="all")
    sample = commands.add_parser("sample", help="Run a sample scenario or analyze a local PDF")
    sample.add_argument("--case", choices=SAMPLE_IDS, default=SAMPLE_IDS[0])
    sample.add_argument("--workflow", choices=WORKFLOWS, default="full")
    sample.add_argument("--scenario", choices=SCENARIOS, default="clean")
    for option in ("pdf", "source-url", "title", "entity", "question"):
        sample.add_argument("--" + option)
    sample.add_argument("--real-embeddings", action="store_true", help="Use MiniLM, which may need a one-time download")
    sample.add_argument("--live", action="store_true", help="Send source excerpts and prompts to Gemini")
    sample.add_argument("--free-tier-confirmed", action="store_true", help="Confirm this project's model quota in AI Studio")
    sample.add_argument("--request-budget", type=int, default=6, help="Shared live transport attempts, including retries")
    commands.add_parser("key", help="Check access to configured Gemini models using metadata only")
    commands.add_parser("retrieval", help="Measure MiniLM retrieval against labeled annual report pages")
    commands.add_parser("evaluation", help="Run the offline full workflow and comparator on development cases")
    commands.add_parser("coverage", help="Record PDF source, extraction and calculation coverage")
    for command in commands.choices.values():
        command.add_argument("--output", type=Path, default=OUTPUT / f"terminal-{uuid4().hex[:12]}")
    args = parser.parse_args()
    os.chdir(ROOT)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {output}", flush=True)
    try:
        if args.command == "suite":
            return run_suite(args.group, output)
        if args.command == "sample":
            return sample_run(args, output)
        if args.command == "key":
            return check_key(output)
        commands_to_run = {
            "retrieval": ["scripts.evaluate_retrieval", "--output", str(output / "retrieval.json"),
                          "--index", str(output / "index")],
            "evaluation": ["evaluation.batch2", "--split", "development", "--conditions", "full", "single_llm",
                           "--output", str(output)],
            "coverage": ["evaluation.source_coverage", "--output", str(output / "source_coverage.json")],
        }
        return subprocess.call([sys.executable, "-m", *commands_to_run[args.command]], cwd=ROOT)
    except ValueError as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
