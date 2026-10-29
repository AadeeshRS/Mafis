"""Report exclusions are derived disclosures, not caller-controlled status hints."""
from decimal import Decimal

import pytest

from agents.contracts import AgentIssue
from agents.report_agent import ReportAgent
from agents.verification_gate import VerificationHealthGate
from tests.test_batch1_review_fixes import checked_store
from tests.test_verification_agent import source_case


@pytest.fixture(params=[False, True], ids=["phase1", "extended"])
def excluded_map(source_case, request):
    memory, retriever = checked_store(source_case)
    rejected = memory.append(source_case[2][0].model_copy(update={
        "claim_id": "unsupported-number", "claim_type": "qualitative",
        "value": Decimal("999999"), "claim": "revenue 100",
        "verification_status": "unsupported", "support_level": "unsupported"}))
    gate = VerificationHealthGate(memory, 0.5).evaluate()
    assert gate.decision == "passed" and gate.verified_count == 3 and gate.total == 4
    agent = ReportAgent(memory, retriever, extended=request.param)
    analysis = agent.build_analysis_map(health_gate=gate if request.param else None)
    assert analysis.excluded_claim_refs == (memory.reference(rejected.claim_id),)
    assert any(i.code == "report_claim_excluded" for i in analysis.issues)
    assert agent.generate_report(analysis).status == "partial"
    return memory, retriever, agent, analysis


@pytest.mark.parametrize("removed", ["references", "issues", "both"])
def test_required_exclusion_metadata_cannot_be_removed(excluded_map, removed):
    _, _, agent, analysis = excluded_map
    changes = {}
    if removed in ("references", "both"):
        changes["excluded_claim_refs"] = ()
    if removed in ("issues", "both"):
        changes["issues"] = ()
    with pytest.raises(ValueError):
        agent.generate_report(analysis.model_copy(update=changes))


def test_checked_claim_cannot_be_falsely_excluded(excluded_map):
    memory, _, agent, analysis = excluded_map
    false_refs = analysis.excluded_claim_refs + (memory.reference("revenue"),)
    with pytest.raises(ValueError):
        agent.generate_report(analysis.model_copy(update={"excluded_claim_refs": false_refs}))


def test_unrelated_issue_does_not_replace_required_exclusion_reason(excluded_map):
    _, _, agent, analysis = excluded_map
    caller = AgentIssue(code="caller_limitation", message="Legitimate extra qualification")
    with pytest.raises(ValueError):
        agent.generate_report(analysis.model_copy(update={"issues": (caller,)}))


def test_fabricated_exclusion_issue_is_rejected(excluded_map):
    _, _, agent, analysis = excluded_map
    forged = AgentIssue(code="report_claim_excluded", message="Checked revenue was excluded")
    with pytest.raises(ValueError):
        agent.generate_report(analysis.model_copy(update={"issues": analysis.issues + (forged,)}))


def test_identical_exclusion_reasons_keep_required_multiplicity(excluded_map):
    memory, _, agent, _ = excluded_map
    rejected = memory.get_current("unsupported-number")
    memory.append(rejected.model_copy(update={"claim_id": "second-unsupported-number"}))
    gate = VerificationHealthGate(memory, 0.5).evaluate()
    assert gate.decision == "passed"
    analysis = agent.build_analysis_map(health_gate=gate if agent.extended else None)
    required = [i for i in analysis.issues if i.code == "report_claim_excluded"]
    assert len(required) == 2 and required[0] == required[1]
    with pytest.raises(ValueError):
        agent.generate_report(analysis.model_copy(update={"issues": (required[0],)}))


def test_validate_report_also_rejects_erased_disclosures(excluded_map):
    _, _, agent, analysis = excluded_map
    original = agent.generate_report(analysis)
    erased = analysis.model_copy(update={"issues": (), "excluded_claim_refs": ()})
    forged = original.model_copy(update={"status": "success", "analysis_map": erased,
        "markdown": agent._render(erased)})
    with pytest.raises(ValueError):
        agent.validate_report(forged)


def test_legitimate_partial_preserves_extra_caller_issues_and_history(excluded_map):
    memory, _, agent, analysis = excluded_map
    before = [c.model_dump_json() for c in memory.get_claims(min_version_only=False)]
    caller = AgentIssue(code="caller_limitation", message="Legitimate extra qualification")
    report = agent.generate_report(analysis.model_copy(update={"issues": analysis.issues + (caller,)}))
    assert report.status == "partial"
    assert "Excluded claim unsupported-number v1" in report.markdown
    assert "report_claim_excluded" in report.markdown and caller.message in report.markdown
    assert before == [c.model_dump_json() for c in memory.get_claims(min_version_only=False)]
    if agent.extended:
        assert report.analysis_map.health_gate.decision == "passed"
        assert report.analysis_map.health_gate.threshold == 0.5


@pytest.mark.parametrize("extended", [False, True], ids=["phase1", "extended"])
def test_clean_checked_store_stays_successful(source_case, extended):
    memory, retriever = checked_store(source_case)
    gate = VerificationHealthGate(memory, 0.5).evaluate()
    agent = ReportAgent(memory, retriever, extended=extended)
    analysis = agent.build_analysis_map(health_gate=gate if extended else None)
    assert analysis.excluded_claim_refs == () and analysis.issues == ()
    assert agent.generate_report(analysis).status == "success"
