"""Exercise CLI routing with simulated accounting only; SDK access is forbidden."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluation import batch2
from gemini import CallTelemetry, GeminiAdapter, PersistentGenerationBudget


@pytest.fixture
def cli_run(tmp_path, monkeypatch, capsys):
    calls = []
    preparations = []
    scenario = {}

    def forbidden_client(*args, **kwargs):
        raise AssertionError("A budget admission test must never access the SDK")

    monkeypatch.setattr(GeminiAdapter, "_get_client", forbidden_client)
    monkeypatch.setattr("rag.retriever.SharedRetriever", lambda **kwargs: object())

    def prepare(case, *args):
        preparations.append(case["case_id"])
        return SimpleNamespace(case=case, fingerprint=case["case_id"] + "-context")

    monkeypatch.setattr(batch2, "CommonEvidence", prepare)

    def simulate(condition, bundle, adapter, output):
        Path(output).mkdir(parents=True, exist_ok=True)
        calls.append((bundle.case["case_id"], condition))
        if isinstance(adapter, GeminiAdapter):
            count = {"single_llm": 1, "full": 8}.get(condition, 1)
            for index in range(count):
                request_id = f"{bundle.case['case_id']}:{condition}:{index}"
                adapter.request_budget.consume(request_id, adapter.settings.model_id, 1)
                adapter.request_budget.record(CallTelemetry(
                    request_id=request_id, model_id=adapter.settings.model_id,
                    attempt=1, status="simulated_success", latency_ms=0))
        result = {"case_id": bundle.case["case_id"], "condition": condition,
                "execution_identity": batch2.execution_identity(adapter),
                "context_sha256": bundle.fingerprint, "question": "test scope",
                "live_empirical_evaluation": False, "valid_ablation": True,
                "mode": "offline CLI accounting simulation; no SDK calls"}
        if scenario.get("halt_after_baseline") and condition == "single_llm":
            adapter.request_budget.state["stopped"] = True
            adapter.request_budget._save()
            result.update(failure="simulated provider failure", valid_ablation=False)
        return result

    monkeypatch.setattr(batch2, "run_condition", simulate)

    def run(*, remaining=12, halted=False, companies=2,
            conditions=("full", "single_llm"), live=True, halt_after_baseline=False):
        scenario["halt_after_baseline"] = halt_after_baseline
        ledger = tmp_path / "simulated_ledger.json"
        state = {"maximum": 12, "stopped": halted,
                 "attempts": [{"request_id": f"prior-{i}"} for i in range(12 - remaining)]}
        ledger.write_text(json.dumps(state), encoding="utf-8")
        before = ledger.read_bytes()
        cases = tmp_path / "cases.json"
        cases.write_text(json.dumps({"cases": [
            {"case_id": f"company-{i}", "split": "development",
             "document_sha256": "a" * 64, "annotation_sha256": "b" * 64}
            for i in range(companies)]}), encoding="utf-8")
        output = tmp_path / "results"
        argv = ["evaluation.batch2", "--cases", str(cases), "--output", str(output),
                "--conditions", *conditions]
        if live:
            argv += ["--live", "--real-embeddings", "--model", "simulated-model",
                     "--live-budget", str(ledger)]
        monkeypatch.setattr("sys.argv", argv)
        code = 0
        try:
            batch2.main()
        except SystemExit as exc:
            code = exc.code
        captured = capsys.readouterr()
        summary = json.loads(captured.out.splitlines()[-1]) if captured.out else None
        return SimpleNamespace(code=code, summary=summary, calls=calls,
            preparations=preparations, output=output, ledger=ledger, before=before,
            records=json.loads((output / "results.json").read_text()) if (output / "results.json").exists() else [],
            pairs=json.loads((output / "pairs.json").read_text()) if (output / "pairs.json").exists() else [])

    return run


def assert_unexecuted(result, company, reason, remaining):
    rows = [r for r in result.records if r["case_id"] == company]
    assert {r["condition"] for r in rows} == {"full", "single_llm"}
    for row in rows:
        assert row["executed"] is False and row["skip_reason"] == reason
        assert row["failure"] == reason + "; not executed"
        assert not row["valid_ablation"] and not row["live_empirical_evaluation"]
        assert not row["live_attempted"]
        assert row["llm_requests"] == row["generation_transport_attempts"] == row["transport_attempts"] == 0
        assert row["tokens"] is None and row["actual_api_cost_usd"] is None
        assert row["budget_remaining"] == remaining
        assert row["pair_clean_path_estimate"] == 9
        assert row["run_id"] is None and row["actual_model"] is None
        saved = json.loads((result.output / company / row["condition"] / "manifest.json").read_text())
        assert saved == row
    pair = next(p for p in result.pairs if p["case_id"] == company)
    assert pair["valid"] is False and pair["status"] == "unexecuted"
    assert pair["reasons"] == [reason]


def test_each_company_needs_a_complete_pair_budget(cli_run):
    result = cli_run()
    assert result.calls == [("company-0", "single_llm"), ("company-0", "full")]
    assert result.preparations == ["company-0"]
    assert result.code == 1
    assert len(json.loads(result.ledger.read_text())["attempts"]) == 9
    assert PersistentGenerationBudget(result.ledger)[0] == 3
    assert_unexecuted(result, "company-1", "insufficient_pair_budget", 3)
    assert result.summary["conditions_executed"] == result.summary["conditions_completed"] == 2
    assert result.summary["conditions_unexecuted"] == 2
    assert result.summary["condition_records"] == 4
    assert result.summary["live_attempts"] == 9
    assert result.summary["generation_transport_attempts_this_invocation"] == 9
    assert next(p for p in result.pairs if p["case_id"] == "company-0")["valid"]


def test_exactly_sufficient_pair_budget(cli_run):
    result = cli_run(remaining=9, companies=1)
    assert result.code == 0 and len(result.calls) == 2
    assert PersistentGenerationBudget(result.ledger)[0] == 0
    assert len(json.loads(result.ledger.read_text())["attempts"]) == 12
    assert result.pairs[0]["valid"]
    assert result.summary["conditions_completed"] == 2
    assert result.summary["conditions_unexecuted"] == 0


def test_initially_underfunded_pair_is_manifested_without_calls(cli_run):
    result = cli_run(remaining=8, companies=1)
    assert result.code == 1 and not result.calls
    assert not result.preparations
    assert result.ledger.read_bytes() == result.before
    assert_unexecuted(result, "company-0", "insufficient_pair_budget", 8)
    assert result.summary["conditions_executed"] == result.summary["conditions_completed"] == 0
    assert result.summary["live_attempts"] == 4  # Prior persisted attempts, not new calls.
    assert result.summary["generation_transport_attempts_this_invocation"] == 0


def test_halted_ledger_takes_precedence_and_is_unchanged(cli_run):
    result = cli_run(remaining=3, halted=True, companies=1)
    assert result.code == 1 and not result.calls
    assert not result.preparations
    assert result.ledger.read_bytes() == result.before
    assert_unexecuted(result, "company-0", "shared_provider_failure_halt", 3)
    assert result.summary["conditions_unexecuted"] == 2


def test_provider_failure_after_admission_prevents_the_full_arm(cli_run):
    result = cli_run(companies=1, halt_after_baseline=True)
    assert result.code == 1 and result.calls == [("company-0", "single_llm")]
    full = next(r for r in result.records if r["condition"] == "full")
    assert full["executed"] is False and full["skip_reason"] == "shared_provider_failure_halt"
    assert full["generation_transport_attempts"] == 0
    assert result.summary["conditions_executed"] == 1
    assert result.summary["conditions_completed"] == 0
    assert result.summary["conditions_unexecuted"] == 1
    assert result.summary["generation_transport_attempts_this_invocation"] == 1
    assert result.pairs[0]["status"] == "incomplete" and not result.pairs[0]["valid"]


def test_other_selected_conditions_cannot_interleave_the_admitted_pair(cli_run):
    result = cli_run(companies=1, conditions=("without_engine", "full", "single_llm"))
    assert result.code == 0
    assert result.calls == [("company-0", "single_llm"), ("company-0", "full"),
                            ("company-0", "without_engine")]
    assert result.pairs[0]["valid"]


@pytest.mark.parametrize("condition,remaining", [("single_llm", 1), ("full", 8)])
def test_single_condition_does_not_require_a_principal_pair(cli_run, condition, remaining):
    result = cli_run(remaining=remaining, companies=1, conditions=(condition,))
    assert result.code == 0 and result.calls == [("company-0", condition)]
    assert result.summary["conditions_completed"] == 1
    assert result.pairs[0]["reasons"] == ["principal_arm_not_selected"]


def test_offline_pairs_do_not_use_the_live_guard_or_ledger(cli_run):
    result = cli_run(remaining=0, halted=True, live=False)
    assert result.code == 0 and len(result.calls) == 4
    assert result.ledger.read_bytes() == result.before
    assert all(p["valid"] for p in result.pairs)
    assert result.summary["conditions_completed"] == 4
    assert result.summary["live_attempts"] == 0
