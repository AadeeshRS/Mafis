"""One paired Apple FY2024 comparison using real local DeepSeek-R1 inference."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Literal
from uuid import uuid4
import json

from pydantic import Field

from engine.financial_engine import FinancialEngine
from evaluation.baseline import BaselineMetric, BaselineRun
from evaluation.batch2 import CommonEvidence
from evaluation.full_baseline import FullBaselineResponse, render_full_baseline
from evaluation.metrics import expectations, numerically_equal
from gemini import ModelOutputError, ModelUnavailable
from graph import run_full_pipeline, save_outputs
from memory.live_feed import track_stage
from memory.shared_memory import CalculationOperation, EvidenceModel
from ollama_adapter import CONTEXT_TOKENS, OllamaAdapter
from rag.retriever import SharedRetriever


OUTPUT_TOKEN_LIMIT = 1024
SECTIONS = ("Executive Summary", "Company Overview", "Financial Health", "Sources", "Support and Uncertainty", "Limitations")
ARM_NAMES = {"baseline": "Single DeepSeek-R1", "mafis": "Full MAFIS"}
METRIC_NAMES = {"revenue_growth": "Revenue growth", "operating_margin": "Operating margin",
                "net_margin": "Net margin", "current_ratio": "Current ratio"}


class LocalMetric(EvidenceModel):
    operation: CalculationOperation
    value: str | None
    unit: Literal["percent", "ratio"]
    period_end: date
    input_ids: tuple[int, ...] = Field(max_length=2)


class LocalAnalysis(EvidenceModel):
    section: Literal["Market Analysis", "Risk Assessment", "Bull Case", "Bear Case", "Key Contradictions"]
    finding: str
    evidence_ids: tuple[int, ...] = Field(max_length=3)


class LocalBaseline(EvidenceModel):
    source_cell_ids: tuple[int, ...] = Field(max_length=6)
    metrics: tuple[LocalMetric, ...] = Field(max_length=4)
    analysis: tuple[LocalAnalysis, ...] = Field(max_length=5)


def baseline_context(payload, cells):
    market = {i: chunk for i, chunk in enumerate(
        (c for c in payload["chunks"] if c["source"]["source_type"] == "news"), len(cells) + 1)}
    context = {"question": payload["question"], "requested_operations": payload["requested_operations"],
               "cell_columns": ["id", "metric", "period_end", "value", "currency", "scale"],
               "cells": [[i, c["metric"], c["period_end"], c["value"], c["currency"], c["scale"]] for i, c in cells.items()],
               "market": [[i, c["source"]["as_of_date"], c["text"]] for i, c in market.items()]}
    evidence = {i: c["chunk_id"] for i, c in (cells | market).items()}
    instruction = (
        "Answer in one response. List the supplied financial cell IDs and calculate each requested operation yourself. "
        "Revenue growth = (current revenue - prior revenue) / prior revenue * 100. "
        "Operating margin = operating income / current revenue * 100. Net margin = net income / current revenue * 100. "
        "Current ratio = current assets / current liabilities. Return the value as a string rounded to four decimal places, "
        "the correct unit and annual period end, and exactly the two source cell IDs used. Use null for unavailable results. "
        "Also provide one brief historical finding each for Market Analysis, Risk Assessment, Bull Case, Bear Case and Key Contradictions "
        "where the evidence supports one. Cite the supplied IDs, distinguish historical context from company-specific risk, "
        "and avoid forecasts or recommendations."
    )

    def restore(result):
        return {"sections": SECTIONS, "primitives": [cells[i] for i in result.source_cell_ids if i in cells],
                "metrics": [{**m.model_dump(exclude={"input_ids"}), "abstained": m.value is None,
                             "input_cell_ids": [cells[i]["cell_id"] if i in cells else f"unknown:{i}" for i in m.input_ids]}
                            for m in result.metrics],
                "analysis": [{"section": a.section, "proposition": a.finding,
                              "source_chunk_ids": [evidence.get(i, f"unknown:{i}") for i in a.evidence_ids]}
                             for a in result.analysis]}

    return context, LocalBaseline, instruction, restore


def reported_metrics(state):
    memory = state["memory"]
    entries = next(s.entries for s in state["report"].analysis_map.sections if s.title == "Financial Health")
    for entry in entries:
        if entry.calculation_ref:
            artifact = memory.get_calculation(entry.calculation_ref)
            yield BaselineMetric(operation=artifact.operation, value=str(artifact.display_value),
                unit=artifact.output_unit, period_end=artifact.output_period.end_date,
                input_cell_ids=tuple(ref.claim_id for ref in entry.input_refs))


def score_metrics(observed, cells, annotations):
    """Use one oracle and identical value/citation rules for the two reports."""
    _, expected = expectations(annotations)
    source = {(v["metric"], v["period_end"]): v for v in annotations["values"]}
    prior, year = sorted(day for metric, day in source if metric == "revenue")
    for operation, value in expected.items():
        candidates = [metric for metric in observed if metric.operation == operation]
        metric = candidates[0] if len(candidates) == 1 and not candidates[0].abstained else None
        unit = "ratio" if operation == "current_ratio" else "percent"
        correct = bool(metric and str(metric.period_end) == year and metric.unit == unit
                       and numerically_equal(metric.value, value))
        expected_inputs = sorted((name, prior if role == "previous_revenue" else year)
                                 for role, name in FinancialEngine.operation_inputs(operation))
        cited = [cells.get(i) for i in metric.input_cell_ids] if metric else []
        keys = [(c.metric, str(c.period.end_date)) for c in cited if c is not None]
        citations = (len(cited) == 2 and sorted(keys) == expected_inputs and all(
            c.value == Decimal(source[key]["value"]) and c.evidence.page == source[key]["pdf_page"]
            and (c.currency, c.scale, c.unit) == (annotations["currency"], annotations["scale"], annotations["unit"])
            for key, c in zip(keys, cited)))
        yield {"operation": operation, "expected": format(value, ".4f"), "unit": unit,
               "observed": metric.value if metric else None, "observed_unit": metric.unit if metric else None,
               "observed_period_end": str(metric.period_end) if metric else None,
               "correct": correct, "citations_correct": citations, "fully_supported": correct and citations}


def arm_result(metrics, model, elapsed, status, cells, annotations):
    rows = list(score_metrics(tuple(metrics), cells, annotations))
    calls = model.telemetry

    def tokens(field):
        values = [getattr(call, field) for call in calls]
        return sum(values) if values and all(value is not None for value in values) else None

    return {"status": status, "rows": rows, "correct": sum(row["correct"] for row in rows),
            "citations_correct": sum(row["citations_correct"] for row in rows),
            "fully_supported": sum(row["fully_supported"] for row in rows), "calls": len(calls),
            "prompt_tokens": tokens("prompt_tokens"), "output_tokens": tokens("output_tokens"),
            "seconds": round(elapsed, 3), "telemetry": [call.model_dump(mode="json") for call in calls]}


def render_comparison(result):
    baseline, mafis = (result["arms"][key] for key in ARM_NAMES)

    def mark(row):
        if row["observed"] is None:
            return "Missing"
        value = row["observed"] + ("%" if row["observed_unit"] == "percent" else "×")
        return f"{value} ({'correct' if row['correct'] else 'incorrect'}, {'cited' if row['citations_correct'] else 'citation failed'})"

    lines = ["# Apple FY2024 benchmark", "", f"**Question** {result['question']}", "",
             f"**Model for both arms** `{result['model']}`", "",
             f"**Result** {result['verdict']}", "",
             "| Metric | Reference | Single DeepSeek-R1 | Full MAFIS |", "| --- | ---: | --- | --- |"]
    for left, right in zip(baseline["rows"], mafis["rows"]):
        suffix = "%" if left["unit"] == "percent" else "×"
        lines.append(f"| {METRIC_NAMES[left['operation']]} | {left['expected']}{suffix} | {mark(left)} | {mark(right)} |")
    lines += ["", "| Measure | Single DeepSeek-R1 | Full MAFIS |", "| --- | ---: | ---: |",
              f"| Correct values | {baseline['correct']}/4 | {mafis['correct']}/4 |",
              f"| Correct input citations | {baseline['citations_correct']}/4 | {mafis['citations_correct']}/4 |",
              f"| Correct value with correct citations | {baseline['fully_supported']}/4 | {mafis['fully_supported']}/4 |",
              f"| Ollama calls | {baseline['calls']} | {mafis['calls']} |",
              f"| Wall time after shared preparation | {baseline['seconds']:.1f} s | {mafis['seconds']:.1f} s |", "",
              "## How to judge the responses", "",
              "The primary score gives one point for each correct result with the right fiscal period, unit and two source inputs. "
              "The reference comes from the manually annotated filing and independent arithmetic. Values are checked to four decimal places.", "",
              "Review the narrative separately. Check that it covers the question, uses relevant citations, and distinguishes observed facts from interpretations. "
              "The benchmark leaves narrative quality unscored. Treat calls, tokens and time as efficiency measurements.", "",
              "Both arms start from the same filing and dated market snapshot. MAFIS performs extra verification retrieval during its workflow. "
              "Shared indexing time is excluded from the arm timings. Cold starts and caching can affect the timing difference. "
              "This is one development case and one paired run.", "",
              "[Single-model report](apple_baseline.md) · [Full MAFIS report](apple_mafis.md)", ""]
    return "\n".join(lines)


def run_apple_benchmark(output, case, snapshot):
    print("Preparing the common Apple filing and dated market evidence…", flush=True)
    baseline_id = str(uuid4())
    with track_stage("benchmark_prepare", baseline_id):
        retriever = SharedRetriever(path=output / "index")
        bundle = CommonEvidence(case, retriever, snapshot)
    baseline_model, mafis_model = (OllamaAdapter(max_output_tokens=OUTPUT_TOKEN_LIMIT) for _ in ARM_NAMES)
    print("Running the single-model baseline (one Ollama request)…", flush=True)
    start = perf_counter()
    response, issues = None, ()
    try:
        with track_stage("baseline", baseline_id):
            response = baseline_model.generate(FullBaselineResponse, system="", payload=bundle.payload)
    except (ModelOutputError, ModelUnavailable) as exc:
        issues = (str(exc),)
    baseline_seconds = perf_counter() - start
    baseline = BaselineRun(run_id=baseline_id, status="success" if response else "failed", response=response,
                           context=bundle.chunks, context_sha256=bundle.fingerprint, issues=issues,
                           latency_ms=baseline_seconds * 1000)
    baseline_text = render_full_baseline(baseline, response) if response else render_full_baseline(baseline)
    (output / "apple_baseline.md").write_text(baseline_text, encoding="utf-8")

    print("Running the full MAFIS workflow with the same local model…", flush=True)
    start = perf_counter()
    state = run_full_pipeline(case["question"], case["document"], retriever=retriever,
        prepared_document=bundle.prepared, document_llm=mafis_model, financial_llm=mafis_model,
        bull_llm=mafis_model, bear_llm=mafis_model, critic_llm=mafis_model,
        market_filters={"doc_id": bundle.market_id, "kind": "narrative"}, risk_categories=("financial", "macro"))
    mafis_seconds = perf_counter() - start
    (output / "apple_mafis.md").write_text(state["report"].markdown, encoding="utf-8")
    save_outputs(state, output / "mafis", adapters=(mafis_model,))

    # Gold values are opened after both model runs and never enter a prompt.
    gold = json.loads(Path(case["gold"]).read_text(encoding="utf-8"))
    if gold["document"]["sha256"] != bundle.prepared.source.sha256:
        raise ValueError("The Apple reference annotations do not match the benchmark filing.")
    cells = {cell.cell_id: cell for chunk in bundle.chunks for cell in chunk.cells}
    arms = {"baseline": arm_result(response.metrics if response else (), baseline_model, baseline_seconds,
                                   baseline.status, cells, gold),
            "mafis": arm_result(reported_metrics(state), mafis_model, mafis_seconds, state["report"].status, cells, gold)}
    left, right = (arm["fully_supported"] for arm in arms.values())
    complete = response is not None and any(call.status == "success" for call in mafis_model.telemetry)
    verdict = ("The pair is incomplete." if not complete else "The scored financial results are tied." if left == right else
               f"{ARM_NAMES['mafis' if right > left else 'baseline']} leads on fully supported results in this run.")
    result = {"case_id": case["case_id"], "question": case["question"], "model": mafis_model.model_id,
              "settings": {"temperature": 0, "thinking": False, "context_tokens": CONTEXT_TOKENS,
                           "output_tokens_per_request": OUTPUT_TOKEN_LIMIT},
              "filing_sha256": bundle.prepared.source.sha256, "common_context_sha256": bundle.fingerprint,
              "shared_preparation_seconds": bundle.preparation["latency_ms"] / 1000, "arms": arms,
              "complete": complete, "verdict": verdict}
    (output / "benchmark.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (output / "benchmark.md").write_text(render_comparison(result), encoding="utf-8")
    print(verdict, flush=True)
    return int(not complete)
