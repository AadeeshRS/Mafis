"""Offline regressions for the four Batch 1 reliability review findings."""
from decimal import Decimal
import configparser

import pytest

from agents.contracts import AgentIssue
from agents.report_agent import AnalysisMap, ReportAgent
from agents.verification_agent import VerificationAgent
from agents.verification_gate import VerificationHealthGate
from memory.shared_memory import Claim, SharedMemory, VerificationCheck, VerificationRecord
from tests.test_verification_agent import source_case, calculate, derived


@pytest.mark.parametrize("kind", ["qualitative", "risk", "argument"])
@pytest.mark.parametrize("payload", [Decimal("999999"), "999999", None])
def test_relabeling_cannot_verify_structured_numeric_payload(source_case, kind, payload):
    memory, retriever, claims = source_case
    # None retains misleading numeric dimensions; quotation text is legitimate.
    original = memory.append(claims[0].model_copy(update={"claim_id": "relabelled",
        "claim_type": kind, "value": payload, "claim": claims[0].evidence[0].quote}))
    record = VerificationAgent(memory, retriever).verify_claim(original.claim_id)
    assert record.outcome != "verified"
    assert not memory.is_current_verified(original.claim_id)
    assert memory.get_history(original.claim_id)[0] == original
    assert memory.get_current(original.claim_id).value == original.value


def test_legitimate_document_quote_can_contain_numbers(source_case):
    memory, retriever, claims = source_case
    quote = Claim(claim_id="quote", agent="DocumentAgent", claim_type="qualitative",
        entity="Acme", metric="source_statement", claim="revenue 100",
        evidence=claims[0].evidence, support_level="single_source")
    memory.append(quote)
    assert VerificationAgent(memory, retriever).verify_claim("quote").outcome == "verified"
    assert memory.is_current_verified("quote")


def test_legacy_success_record_cannot_confer_eligibility_on_invalid_shape(source_case):
    memory, retriever, claims = source_case
    legacy = memory.append(claims[0].model_copy(update={"claim_type": "qualitative",
        "claim": "revenue 100", "value": Decimal("999999")}))
    reference = memory.reference(legacy.claim_id)
    memory.append_verification(VerificationRecord(verification_id="legacy-check", checked_ref=reference,
        resulting_ref=reference.model_copy(update={"version": 2}), outcome="verified", support_level="single_source",
        checks=(VerificationCheck(code="source_fact", outcome="passed", message="Historical quote-only check"),)))
    assert not memory.is_current_verified(legacy.claim_id)
    assert memory.get_unresolved()["claims"][0].claim_id == legacy.claim_id
    record = VerificationAgent(memory, retriever).verify_claim(legacy.claim_id)
    assert record.outcome == "unsupported" and record.resulting_ref.version == 3
    assert memory.get_history(legacy.claim_id)[1].verification_status == "verified"
    assert all(c.value == legacy.value for c in memory.get_history(legacy.claim_id))


def checked_store(case):
    memory, retriever, claims = case
    retriever.page_chunks = lambda source_id, page: tuple(c for c in retriever.chunks
        if c.source.source_id == source_id and c.evidence.page == page)
    for claim in claims:
        memory.append(claim)
    verifier = VerificationAgent(memory, retriever)
    verifier.verify_all()
    metric = derived(memory, calculate(memory))
    verifier.verify_claim(metric.claim_id)
    return memory, retriever


@pytest.fixture
def checked_report(source_case):
    memory, retriever = checked_store(source_case)
    gate = VerificationHealthGate(memory, 0.25).evaluate()
    agent = ReportAgent(memory, retriever, extended=True)
    analysis = agent.build_analysis_map(health_gate=gate)
    assert agent.generate_report(analysis).status == "success"
    return memory, retriever, agent, analysis


@pytest.mark.parametrize("changes", [
    {"verified_count": 999}, {"verified_count": 2}, {"total": 4},
    {"unsupported_count": 1}, {"flagged_count": 1}, {"pending_count": 1},
    {"unresolved_count": 1}, {"stale_count": 1}, {"unsupported_rate": 0.1},
    {"decision": "blocked"}, {"threshold": 1.0}, {"failure_types": ("invented",)},
    {"reanalysis_scope": ("MarketAgent",)}, {"reason": "Invented reason"},
])
def test_report_rejects_changed_gate_metadata(checked_report, changes):
    _, _, agent, analysis = checked_report
    altered = analysis.model_copy(update={"health_gate": analysis.health_gate.model_copy(update=changes)})
    with pytest.raises(ValueError):
        agent.generate_report(altered)


def test_report_rejects_changed_failing_refs(checked_report):
    memory, _, agent, analysis = checked_report
    gate = analysis.health_gate.model_copy(update={"failing_claim_refs": (memory.reference("revenue"),)})
    with pytest.raises(ValueError):
        agent.generate_report(analysis.model_copy(update={"health_gate": gate}))


def test_optional_gate_in_phase1_report_cannot_render_forged_metadata(checked_report):
    memory, retriever, _, analysis = checked_report
    agent = ReportAgent(memory, retriever)
    phase1 = agent.build_analysis_map(health_gate=analysis.health_gate)
    forged = phase1.model_copy(update={"health_gate": analysis.health_gate.model_copy(update={"verified_count": 999})})
    with pytest.raises(ValueError):
        agent.generate_report(forged)


def test_extended_map_requires_gate_even_through_construct(checked_report):
    _, _, agent, analysis = checked_report
    for forged in (analysis.model_copy(update={"health_gate": None}),
                   AnalysisMap.model_construct(**{**analysis.__dict__, "health_gate": None})):
        with pytest.raises(ValueError):
            agent.generate_report(forged)


def test_cross_run_gate_with_identical_counts_is_rejected(checked_report, source_case):
    _, _, agent, analysis = checked_report
    # Another genuinely checked store has matching values, counts and versions.
    other, tool, claims = source_case
    # source_case was used by checked_report; use detached records in a new store.
    independent = SharedMemory("other-run")
    independent.register_source(other.get_source(claims[0].evidence[0].source_id))
    for claim in claims:
        independent.append(claim)
    verifier = VerificationAgent(independent, tool)
    verifier.verify_all()
    verifier.verify_claim(derived(independent, calculate(independent)).claim_id)
    gate = VerificationHealthGate(independent, 0.25).evaluate()
    assert gate.verified_count == analysis.health_gate.verified_count
    with pytest.raises(ValueError):
        agent.generate_report(analysis.model_copy(update={"health_gate": gate}))


@pytest.mark.parametrize("field,value", [("run_id", "another-run"), ("evaluation_id", "invented"),
    ("claim_refs", ()), ("verified_count", True), ("threshold", float("nan"))])
def test_gate_context_and_bypassed_model_inputs_are_revalidated(checked_report, field, value):
    _, _, agent, analysis = checked_report
    forged = analysis.health_gate.model_construct(**{**analysis.health_gate.__dict__, field: value})
    with pytest.raises(ValueError):
        agent.generate_report(analysis.model_copy(update={"health_gate": forged}))


def test_gate_policy_and_original_issues_survive_fresh_map_build(source_case):
    memory, retriever = checked_store(source_case)
    issue = AgentIssue(code="market_retrieval_unavailable", message="Original required evidence unavailable")
    gate = VerificationHealthGate(memory, 0.125).evaluate(issues=(issue,))
    detached = memory.get_health_gate_context()
    detached["result"]["threshold"] = 1.0
    detached["issues"].clear()
    memory.get_verification_health()  # Aggregate reads must not replace the policy.
    assert memory.get_health_gate_context()["result"]["evaluation_id"] == gate.evaluation_id
    agent = ReportAgent(memory, retriever, extended=True)
    analysis = agent.build_analysis_map()  # Omitted caller issues cannot erase them.
    assert analysis.health_gate.threshold == 0.125 and issue in analysis.issues
    assert agent.generate_report(analysis).status == "partial"


@pytest.mark.parametrize("fields", [{"value": "999999"}, {"unit": "percent"}, {"currency": "EUR"},
    {"scale": 1000}, {"accounting_scope": "consolidated"}])
def test_narrative_value_strings_and_dimensions_never_become_checked(source_case, fields):
    memory, retriever, claims = source_case
    claim = Claim(claim_id="quote", agent="DocumentAgent", claim_type="qualitative", entity="Acme",
        metric="source_statement", claim="revenue 100", evidence=claims[0].evidence,
        support_level="single_source", **fields)
    memory.append(claim)
    assert VerificationAgent(memory, retriever).verify_claim("quote").outcome != "verified"
    assert not memory.is_current_verified("quote")


def test_gate_snapshot_stales_even_when_added_claim_is_not_in_map(checked_report):
    memory, _, agent, analysis = checked_report
    # Existing map entries are unchanged; only the gate's run snapshot changes.
    raw = memory.get_current("revenue")
    memory.append(raw.model_copy(update={"claim_id": "additional", "version": 1,
        "verification_status": "pending"}))
    with pytest.raises(ValueError):
        agent.generate_report(analysis)


def test_blocked_report_cannot_clear_original_issues_or_weaken_threshold(source_case):
    memory, retriever = checked_store(source_case)
    issue = AgentIssue(code="missing_metrics", message="Original upstream extraction gap")
    gate = VerificationHealthGate(memory, 0.125).evaluate(issues=(issue,))
    agent = ReportAgent(memory, retriever, extended=True)
    analysis = agent.build_analysis_map((issue,), health_gate=gate)
    assert agent.generate_report(analysis).status == "partial"
    for update in ({"issues": ()}, {"limitations": ()},
                   {"health_gate": gate.model_copy(update={"decision": "passed", "threshold": 1.0})}):
        with pytest.raises(ValueError):
            agent.generate_report(analysis.model_copy(update=update))


def test_unresolved_includes_unchecked_verified_status(source_case):
    memory, _, claims = source_case
    memory.append(claims[0].model_copy(update={"verification_status": "verified"}))
    assert not memory.is_current_verified("revenue")
    assert [c.claim_id for c in memory.get_unresolved()["claims"]] == ["revenue"]


def test_checked_current_claim_is_not_unresolved(source_case):
    memory, retriever, claims = source_case
    memory.append(claims[0])
    VerificationAgent(memory, retriever).verify_all()
    assert memory.is_current_verified("revenue")
    assert memory.get_unresolved()["claims"] == []


def test_unresolved_includes_superseded_calculation_and_transitive_support(source_case):
    memory, _ = checked_store(source_case)
    # Legacy support records can be stored and independently source-checked.
    # Revise upstream, leaving the logical intermediates' versions unchanged.
    for identifier, support in (("middle", "margin"), ("leaf", "middle")):
        raw = memory.get_current("revenue")
        quote = Claim(claim_id=identifier, agent="DocumentAgent", claim_type="qualitative",
            entity="Acme", claim=raw.evidence[0].quote, evidence=raw.evidence,
            supports_claim_ids=(support,), support_level="single_source")
        memory.append(quote)
        VerificationAgent(memory, source_case[1]).verify_claim(identifier)
        assert memory.is_current_verified(identifier)
    original = memory.get_current("revenue")
    memory.append(original.model_copy(update={"version": original.version + 1}))
    assert memory.get_dependency_freshness("leaf") == "current"
    assert not memory.is_current_verified("leaf")
    unresolved = {c.claim_id for c in memory.get_unresolved()["claims"]}
    assert {"revenue", "margin", "middle", "leaf"} <= unresolved
    assert memory.get_history("revenue")[0].version == 1


def test_default_discovery_is_limited_to_real_tests():
    configuration = configparser.ConfigParser()
    configuration.read("pytest.ini")
    assert configuration.get("pytest", "testpaths", fallback="").split() == ["tests"]
