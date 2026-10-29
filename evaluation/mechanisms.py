"""Labelled injected-case mechanism study, explicitly not live model accuracy."""
from decimal import Decimal
import json
from pathlib import Path
from agents.verification_agent import VerificationAgent
from agents.critic_agent import Assertion,CriticAgent
from evaluation.batch2 import detection_metrics,freeze_threshold
from tests.test_verification_agent import source_case
from tests.test_batch1_review_fixes import checked_store


def run(output="output/batch2/mechanisms"):
    root=Path(output);root.mkdir(parents=True,exist_ok=True)
    verification=[]
    for name,change,bad in [("supported",{},False),("value",{"value":Decimal("999")},True),
        ("sign",{"value":Decimal("-100")},True),("scale",{"scale":1000},True),("currency",{"currency":"EUR"},True),
        ("quote_numeric_payload",{"claim_type":"qualitative","value":Decimal("999")},True),
        ("wrong_page",{"_evidence_update":{"page":99}},True),
        ("wrong_cell",{"_evidence_update":{"locator":"invented-cell"}},True),
        ("unsupported_quotation",{"_evidence_update":{"quote":"Invented unsupported assertion"}},True)]:
        memory,index,claims=source_case.__wrapped__()
        change=dict(change)
        if "_evidence_update" in change:
            change["evidence"]=(claims[0].evidence[0].model_copy(update=change.pop("_evidence_update")),)
        memory.append(claims[0].model_copy(update=change))
        actual=VerificationAgent(memory,index).verify_claim("revenue")
        verification.append({"label":name,"injected_error":bad,"detected":actual.outcome!="verified","outcome":actual.outcome})
    memory,index=checked_store(source_case.__wrapped__());c=memory.get_current("revenue")
    a=Assertion(reference=memory.reference("revenue"),entity=c.entity,metric=c.metric,period=c.period,
        value=c.value,unit=c.unit,currency=c.currency,scale=c.scale,source_ids=(c.evidence[0].source_id,))
    contradictions=[]
    for name,change,bad in [("same_fact",{},False),("value",{"value":Decimal("999")},True),
        ("scaled_equivalent",{"value":Decimal("100000000"),"scale":1},False),
        ("currency",{"currency":"EUR"},True),("causal",{"predicate":"causes"},True),
        ("compatible_perspectives",{"predicate":"caution"},False),("citation",{"source_ids":("wrong",)},True)]:
        findings=CriticAgent(memory).mechanical([a,a.model_copy(update=change)])
        contradictions.append({"label":name,"injected_error":bad,"detected":bool(findings),"categories":[f.category for f in findings]})
    other=a.model_copy(update={"period":a.period.model_copy(update={"end_date":a.period.end_date.replace(year=2022),"start_date":None})})
    extra=[("different_periods",[a,other],False),
        ("equated_periods",[a,other.model_copy(update={"equates_ref":a.reference})],True),
        ("logical_opposites",[a.model_copy(update={"predicate":"increase","proposition_key":"direction"}),a.model_copy(update={"predicate":"decrease","proposition_key":"direction"})],True),
        ("unqualified_risk",[a.model_copy(update={"predicate":"resilient","qualified":False})],True),
        ("different_metrics",[a,a.model_copy(update={"metric":"different_metric","value":Decimal("999")})],False)]
    for name,views,bad in extra:
        findings=CriticAgent(memory).mechanical(views)
        contradictions.append({"label":name,"injected_error":bad,"detected":bool(findings),"categories":[f.category for f in findings]})
    # Freshness/gate admission checks remain strict outside the argument injector.
    from agents.report_agent import ReportAgent
    from agents.verification_gate import VerificationHealthGate
    admission=[]
    gate=VerificationHealthGate(memory).evaluate()
    report=ReportAgent(memory,index,extended=True)
    analysis=report.build_analysis_map(health_gate=gate)
    try:
        report.generate_report(analysis.model_copy(update={"health_gate":gate.model_copy(update={"verified_count":1})}))
        blocked=False
    except ValueError:
        blocked=True
    admission.append({"label":"fabricated_gate_count","injected_error":True,"detected":blocked})
    old=memory.get_current("revenue")
    memory.append(old.model_copy(update={"version":old.version+1}))
    admission.append({"label":"stale_calculation_input","injected_error":True,"detected":not memory.is_current_verified("margin")})
    record={"mode":"deterministic injected fixtures; no live model or human ratings",
        "verification":verification,"contradictions":contradictions,"admission":admission,
        "verification_metrics":detection_metrics([r["injected_error"] for r in verification],[r["detected"] for r in verification]),
        "contradiction_metrics":detection_metrics([r["injected_error"] for r in contradictions],[r["detected"] for r in contradictions])}
    (root/"results.json").write_text(json.dumps(record,indent=2),encoding="utf-8")
    freeze_threshold([{"empty":False,"upstream_failure":False,"ineligible_rate":0,"should_block":False},
        {"empty":False,"upstream_failure":False,"ineligible_rate":0.25,"should_block":False},
        {"empty":False,"upstream_failure":False,"ineligible_rate":0.75,"should_block":True},
        {"empty":True,"upstream_failure":False,"ineligible_rate":0,"should_block":True}],split="validation",output=root/"threshold.json")
    print(json.dumps(record,indent=2))


if __name__=="__main__":
    run()
