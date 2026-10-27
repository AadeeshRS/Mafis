import pytest

from agents.planner import PlannerAgent


def test_ordinary_financial_question_has_explicit_dependencies():
    plan = PlannerAgent().build_graph("Assess FY2024 financial health, profitability and liquidity", True)
    assert plan.status == "ready" and plan.target_year == 2024
    assert set(plan.operations) == {"revenue_growth", "operating_margin", "net_margin", "current_ratio"}
    assert next(t for t in plan.tasks if t.name == "financial").depends_on == ("document",)
    assert next(t for t in plan.tasks if t.name == "report").depends_on == ("analysis_map",)


@pytest.mark.parametrize(("query", "operations", "metrics"), [
    ("What is the net margin?", ("net_margin",), {"net_income", "revenue"}),
    ("What is the current ratio?", ("current_ratio",), {"current_assets", "current_liabilities"}),
    ("What revenue was reported?", (), {"revenue"}),
    ("Company overview", (), set()),
])
def test_minimal_scoped_plans(query, operations, metrics):
    plan = PlannerAgent().build_graph(query, True)
    assert plan.status == "ready" and plan.operations == operations and set(plan.metrics) == metrics


@pytest.mark.parametrize(("query", "documents", "status"), [
    ("financial health", False, "missing_document"), ("", True, "unsupported"),
    ("Perform a DCF valuation", True, "unsupported"), ("weather tomorrow", True, "unsupported"),
])
def test_missing_and_unsupported_inputs(query, documents, status):
    plan = PlannerAgent().build_graph(query, documents)
    assert plan.status == status and plan.issues


def test_supported_analysis_omits_out_of_scope_recommendations():
    plan = PlannerAgent().build_graph("Analyze financial health and give a buy recommendation", True)
    assert plan.status == "ready" and plan.operations
    assert plan.issues[0].code == "unsupported_scope_omitted"


@pytest.mark.parametrize("query", ["Q1 2024 revenue growth", "quarterly net margin", "TTM profitability", "calendar year 2024 revenue"])
def test_unsupported_periods_are_not_silently_treated_as_fiscal_years(query):
    plan = PlannerAgent().build_graph(query, True)
    assert plan.status == "unsupported" and plan.issues[0].code == "unsupported_period"
