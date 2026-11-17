import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from evaluation.apple_benchmark import LocalBaseline, baseline_context, score_metrics
from evaluation.baseline import BaselineMetric


def test_value_accuracy_and_citation_accuracy_are_independent():
    gold = json.loads((Path(__file__).parent / "fixtures/apple_2024/annotations.json").read_text(encoding="utf-8"))
    cells = {f"{row['metric']}:{row['period_end']}": SimpleNamespace(metric=row["metric"],
             period=SimpleNamespace(end_date=row["period_end"]), value=Decimal(row["value"]),
             evidence=SimpleNamespace(page=row["pdf_page"]), currency=gold["currency"], scale=gold["scale"], unit=gold["unit"])
             for row in gold["values"]}
    growth = BaselineMetric(operation="revenue_growth", value="2.1000", unit="percent",
                           period_end=date(2024, 9, 28), input_cell_ids=("revenue:2024-09-28", "revenue:2023-09-30"))
    margin = BaselineMetric(operation="net_margin", value="23.9713", unit="percent",
                           period_end=date(2024, 9, 28), input_cell_ids=("revenue:2024-09-28", "operating_income:2024-09-28"))
    rows = {row["operation"]: row for row in score_metrics((growth, margin), cells, gold)}
    assert rows["revenue_growth"]["citations_correct"] and not rows["revenue_growth"]["correct"]
    assert rows["net_margin"]["correct"] and not rows["net_margin"]["citations_correct"]
    assert all(not row["fully_supported"] for row in rows.values())
    assert rows["current_ratio"]["observed"] is None


def test_baseline_retains_model_number_and_invalid_reference_for_scoring():
    payload = {"question": "Assess FY2024 financial health", "requested_operations": ["revenue_growth"], "chunks": []}
    cells = {1: {"cell_id": "real-cell", "chunk_id": "real-chunk", "metric": "revenue", "value": "391035",
                 "currency": "USD", "scale": 1000000, "unit": "currency", "period_end": "2024-09-28"}}
    context, schema, _, restore = baseline_context(payload, cells)
    assert schema is LocalBaseline and context["cells"][0][3] == "391035"
    result = schema.model_validate({"source_cell_ids": [1], "analysis": [], "metrics": [
        {"operation": "revenue_growth", "value": "99.0000", "unit": "percent", "period_end": "2024-09-28", "input_ids": [1, 7]}]})
    restored = restore(result)
    assert restored["metrics"][0]["value"] == "99.0000"
    assert restored["metrics"][0]["input_cell_ids"] == ["real-cell", "unknown:7"]
