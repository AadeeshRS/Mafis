"""Full-flow routing helpers; existing agents and the single Shared Memory only."""
from time import perf_counter

from agents.argument_contracts import evidence_snapshot
from agents.bull_agent import BullAgent
from agents.bear_agent import BearAgent
from agents.critic_agent import CriticAgent
from agents.contracts import AgentIssue
from agents.document_agent import DocumentAgent
from agents.financial_agent import FinancialAgent
from agents.market_agent import MarketAgent
from agents.risk_agent import RiskAgent
from agents.planner import PlannerAgent
from agents.verification_agent import VerificationAgent
from agents.verification_gate import VerificationHealthGate
from memory.shared_memory import ReanalysisRequest


def correction_roots(memory, claim_id, seen=frozenset()):
    """Find failing current owners; sound newer inputs require only repinning.

    A stale argument over sound current facts targets its author. A stale
    argument over an unchecked source chain targets that chain's failing root,
    then Planner follows the ordinary downstream dependency closure.
    """
    if claim_id in seen:
        raise ValueError("Correction dependency cycle")
    claim=memory.get_current(claim_id)
    dependencies=list(memory.get_dependency_references(claim_id))
    if claim.calculation_ref:
        dependencies.extend(i.claim_ref for i in memory.get_calculation(claim.calculation_ref).inputs)
    roots=[]
    for dep in dict.fromkeys(dependencies):
        if not memory.is_current_verified(dep.claim_id):
            roots.extend(correction_roots(memory,dep.claim_id,seen|{claim_id}))
    return tuple(dict.fromkeys(roots)) or (memory.reference(claim_id),)


def requests_for(state):
    memory = state["memory"]
    requests = []
    if state["health_gate"].decision == "blocked":
        failing = [memory.resolve(r) for r in state["health_gate"].failing_claim_refs]
        raw = [c for c in failing if c.claim_type == "raw_primitive"]
        current_metrics = {c.metric for c in memory.get_claims() if c.claim_type == "raw_primitive" and memory.is_current_verified(c.claim_id)}
        missing = set(state["plan"].metrics) - current_metrics
        operations = tuple(op for op in state["plan"].operations if not any(c.metric == op and c.agent == "FinancialAgent"
            and memory.is_current_verified(c.claim_id) for c in memory.get_claims()))
        components = []
        if raw or missing or state.get("document_result") and state["document_result"].issues:
            components.append("DocumentAgent")
        if operations:
            components.append("FinancialAgent")
        if state.get("market_result") and state["market_result"].issues:
            components.append("MarketAgent")
        if not components:
            components = list(state["health_gate"].reanalysis_scope)
        requests.append(ReanalysisRequest(trigger="health_gate", affected_refs=tuple(memory.reference(c.claim_id) for c in raw or failing),
            components=tuple(dict.fromkeys(components)), failure_types=state["health_gate"].failure_types,
            correction=(state["health_gate"].reason,),metrics=tuple(sorted(missing | {c.metric for c in raw})),operations=operations,
            retryable=bool(state.get("source_id"))))
    for key, component in (("bull_result","Bull"),("bear_result","Bear")):
        result = state.get(key)
        if result:
            requests.extend(result.evidence_gaps)
            if result.issues:
                requests.append(ReanalysisRequest(trigger="evidence_gap",components=(component,),
                    affected_refs=result.claim_refs, failure_types=tuple(i.code for i in result.issues),
                    correction=tuple(i.message for i in result.issues)))
    for finding in state["memory"].get_contradictions():
        if finding.status != "resolved":
            roots=tuple(dict.fromkeys(r for ref in finding.claim_refs for r in correction_roots(memory,ref.claim_id)))
            requests.append(ReanalysisRequest(trigger="critic",affected_refs=tuple(dict.fromkeys(finding.claim_refs+roots)),
                components=tuple(dict.fromkeys(memory.resolve(r).agent for r in roots)),
                failure_types=(finding.category,),correction=(finding.description,)))
    return tuple(requests)


def run_reasoning(state, retriever, bull_llm, bear_llm, critic_llm, *, stances=("Bull","Bear"), critic=True):
    memory = state["memory"]
    issues = list(state["issues"])
    snapshot = evidence_snapshot(memory)
    iteration = 1 - memory.retry_budget_remaining
    for component, cls, llm, key in (("Bull",BullAgent,bull_llm,"bull_result"),("Bear",BearAgent,bear_llm,"bear_result")):
        if component not in stances:
            continue
        old = state.get(key)
        if old:
            issues = [i for i in issues if i not in old.issues]
        result = cls(memory,llm).build_case(snapshot=snapshot,run_iteration=iteration)
        VerificationAgent(memory,retriever).verify_all([r.claim_id for r in result.claim_refs if not memory.is_current_verified(r.claim_id)])
        state[key] = result.model_copy(update={"claim_refs":tuple(memory.reference(r.claim_id) for r in result.claim_refs)})
        issues.extend(result.issues)
    if critic:
        old = state.get("critic_result")
        if old:
            issues = [i for i in issues if i not in old.issues]
        state["critic_result"] = CriticAgent(memory,critic_llm).check_contradictions(run_iteration=iteration,exhausted=not memory.retry_budget_remaining)
        issues.extend(state["critic_result"].issues)
    state["issues"] = tuple(issues)
    return state


def execute_targeted(state, decision, retriever, document_llm, financial_llm, market_filters, risk_categories, as_of):
    """Execute only allocated roots/necessary downstream stages; never ingest."""
    memory = state["memory"]
    actual = []
    before = {c.claim_id:memory.reference(c.claim_id) for c in memory.get_claims()}
    issues = list(state["issues"])
    # health_gate_blocked is a derived terminal disclosure from Batch 1, not an
    # upstream failure. Reevaluate it after this actual correction pass.
    issues = [i for i in issues if i.code != "health_gate_blocked"]
    def replace(key, result):
        old = state.get(key)
        if old:
            for issue in old.issues:
                if issue in issues:
                    issues.remove(issue)
        state[key] = result
        issues.extend(result.issues)
    def verify(agent):
        ids = [c.claim_id for c in memory.get_claims() if c.agent == agent and not memory.is_current_verified(c.claim_id)]
        if ids:
            VerificationAgent(memory,retriever).verify_all(ids)
            actual.append("verify:"+agent)
    if "DocumentAgent" in decision.rerun_nodes:
        result = DocumentAgent(memory,retriever,document_llm,source_id=state["source_id"],allow_revisions=True,run_iteration=1).extract_primitives(
            state["question"],metrics=decision.metrics or state["plan"].metrics)
        replace("document_result",result); actual.append("DocumentAgent"); verify("DocumentAgent")
    if "FinancialAgent" in decision.rerun_nodes:
        ids = [c.claim_id for c in memory.get_claims() if c.claim_type == "raw_primitive" and memory.is_current_verified(c.claim_id)]
        result = FinancialAgent(memory,financial_llm,stable_ids=True,run_iteration=1).analyze(state["question"],
            operations=decision.operations, primitive_claim_ids=ids,target_year=state["plan"].target_year)
        replace("financial_result",result); actual.append("FinancialAgent"); verify("FinancialAgent")
    if "MarketAgent" in decision.rerun_nodes:
        result = MarketAgent(memory,retriever).research(state["question"],filters=market_filters or {"doc_id":state["source_id"],"kind":"narrative"},as_of=as_of)
        replace("market_result",result); actual.append("MarketAgent"); verify("MarketAgent")
    if "RiskAgent" in decision.rerun_nodes:
        financial = [memory.reference(c.claim_id) for c in memory.get_claims() if c.agent == "FinancialAgent" and memory.is_current_verified(c.claim_id)]
        market = [memory.reference(c.claim_id) for c in memory.get_claims() if c.agent == "MarketAgent" and memory.is_current_verified(c.claim_id)]
        result = RiskAgent(memory,retriever,stable_ids=True,run_iteration=1).assess_risk(financial,market,categories=risk_categories,as_of=as_of)
        replace("risk_result",result); actual.append("RiskAgent"); verify("RiskAgent")
    state["issues"] = tuple(issues)
    state["retry_execution"] = {"decision_id":decision.decision_id,"nodes":tuple(actual),
        "before_refs":tuple(before.values()),"after_refs":tuple(memory.reference(c.claim_id) for c in memory.get_claims()),
        "changed_ids":tuple(c.claim_id for c in memory.get_claims() if before.get(c.claim_id) != memory.reference(c.claim_id))}
    return state
