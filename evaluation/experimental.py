"""Isolated engine ablation: model numerics never become calculation artifacts.

Document verification remains, but an experimental renderer accepts explicitly
unchecked model arithmetic. Production eligibility and ReportAgent are untouched.
"""
import json
from datetime import date
from pathlib import Path

from agents.argument_contracts import ArgumentProposal
from agents.critic_agent import CriticAgent
from agents.document_agent import DocumentAgent
from agents.market_agent import MarketAgent
from agents.planner import PlannerAgent
from agents.risk_agent import RiskAgent
from agents.verification_agent import VerificationAgent
from evaluation.baseline import BaselineResponse
from memory.shared_memory import ArgumentPremise,SharedMemory


def no_engine_run(bundle,llm,output):
    memory=SharedMemory(); memory.register_source(bundle.prepared.source)
    as_of=date.fromisoformat(bundle.payload["as_of"]) if bundle.payload.get("as_of") else None
    plan=PlannerAgent().build_full_plan(bundle.case["question"],True)
    extraction=DocumentAgent(memory,bundle.retriever,llm,source_id=bundle.prepared.source.source_id).extract_primitives(
        bundle.case["question"],metrics=plan.metrics)
    VerificationAgent(memory,bundle.retriever).verify_all()
    response=llm.generate(BaselineResponse,system="Engine ablation financial analyst. Produce numerical reasoning from the source cells. No engine tool is available. Do not label model arithmetic independently verified.",
        payload={**bundle.payload,"experimental_condition":"without_engine"})
    response=BaselineResponse.model_validate(response.model_dump(round_trip=True))
    market=MarketAgent(memory,bundle.retriever).research(bundle.case["question"],filters={"doc_id":bundle.market_id,"kind":"narrative"},as_of=as_of)
    VerificationAgent(memory,bundle.retriever).verify_all([r.claim_id for r in market.claim_refs])
    # Only source-backed risk context can use production verification here.
    # Model metrics have no deterministic artifacts and cannot enter this store.
    risk=RiskAgent(memory,bundle.retriever).assess_risk([],list(memory.reference(r.claim_id) for r in market.claim_refs),categories=("financial","macro"),as_of=as_of)
    VerificationAgent(memory,bundle.retriever).verify_all([r.claim_id for r in risk.claim_refs])
    premises=[ArgumentPremise(claim_ref=memory.reference(c.claim_id),entity=c.entity,metric=c.metric,value=c.value,
        period=c.period,unit=c.unit,currency=c.currency,scale=c.scale,accounting_scope=c.accounting_scope,calculation_ref=None,
        source_ids=tuple(e.source_id for e in c.evidence),quotations=tuple(e.quote for e in c.evidence)).model_dump(mode="json")
        for c in memory.get_claims() if c.claim_type=="raw_primitive" and memory.is_current_verified(c.claim_id)]
    arguments=[]
    for stance in ("bull","bear"):
        proposed=llm.generate(ArgumentProposal,system="Engine ablation interpretation. Source premises are checked; attached numerical results are unchecked model arithmetic. Use exact source premises, qualify interpretations, and abstain when unsupported.",
            payload={"task":stance+"_case","experimental_condition":"without_engine","model_metrics":response.model_dump(mode="json")["metrics"],
                "snapshot":{"run_id":memory.run_id,"fingerprint":bundle.fingerprint,"premises":premises}})
        arguments.append(ArgumentProposal.model_validate(proposed.model_dump(round_trip=True)).model_dump(mode="json"))
    critique=CriticAgent(memory,llm).check_contradictions()
    observed={m.operation:m.value for m in response.metrics if not m.abstained and m.value is not None}
    result={"run_id":memory.run_id,"experimental_numeric_results":observed,"experimental_arguments":arguments,
        "calculation_calls":len(memory.get_calculations()),"verification_records":len(memory.get_verification_records()),
        "critic_findings":[f.model_dump(mode="json") for f in critique.findings],
        "execution_scope":"Verified source extraction, separate model arithmetic, deterministic dated Market/source Risk, experimental adversarial outputs, factual Critic; no engine or fake artifacts",
        "limitations":"Model metrics and experimental arguments are unchecked. Financial risk requiring artifacts is an explicit gap; Critic covers admitted source context, not proof of unchecked arithmetic. No production success report or model-metric retry is fabricated.",
        "issues":[i.model_dump(mode="json") for i in extraction.issues+market.issues+risk.issues+critique.issues]}
    output=Path(output)
    (output/"experimental.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    lines=["# Engine ablation","","Experimental output: model numerical results are unchecked; no deterministic calculation artifacts.",""]
    lines.extend(f"- {m.operation}: {m.value if not m.abstained else 'abstained'} {m.unit}; {m.period_end}; inputs {m.input_cell_ids}" for m in response.metrics)
    lines.extend(["",result["limitations"]]+["- "+i["message"] for i in result["issues"]])
    (output/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return result
