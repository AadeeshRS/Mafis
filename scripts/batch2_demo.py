"""Actual PDF + real MiniLM/Chroma offline acceptance; no model requests."""
import argparse
import json
from pathlib import Path
from graph import run_full_pipeline,save_outputs
from rag.retriever import SharedRetriever
from rag.market_sources import ingest_market_snapshot
from rag.ingest import ingest_document
from tests.batch2_fakes import Batch2MockLLM


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--output",default="output/batch2/demo"); parser.add_argument("--cases",default="tests/fixtures/phase1_cases.json"); parser.add_argument("--case-ids",nargs="+"); parser.add_argument("--index"); args=parser.parse_args()
    root=Path(args.output); root.mkdir(parents=True,exist_ok=True)
    index=SharedRetriever(path=Path(args.index) if args.index else root/"source_index")
    market=ingest_market_snapshot("tests/fixtures/market_snapshots/fomc_2024_01_31.json",retriever=index)
    results=[]
    cases=json.loads(Path(args.cases).read_text())["cases"]
    cases=[c for c in cases if c.get("document") and c.get("annotation_ready_for_primary",True) and (not args.case_ids or c["case_id"] in args.case_ids)]
    prepared={c["case_id"]:ingest_document(**c["document"],retriever=index) for c in cases}
    for case,scenario in [(c,"clean") for c in cases]+[(cases[0],"corrected"),(cases[0],"persistent"),(cases[0],"gate_blocked"),(cases[0],"compatible")]:
        attempts=[0]
        def transform(response,payload):
            if payload["task"]=="document_extraction":
                attempts[0]+=1
                if scenario=="persistent" or scenario=="corrected" and attempts[0]==1:
                    response["primitives"]=[p for p in response["primitives"] if p["metric"]!="net_income"]
            return response
        model=Batch2MockLLM(transform=transform)
        name=case["case_id"]+"_"+scenario
        retrieval_before=index.retrieval_calls
        try:
            state=run_full_pipeline(case["question"],None if scenario=="gate_blocked" else case["document"],retriever=index,
                document_llm=model,financial_llm=model,bull_llm=model,bear_llm=model,critic_llm=model,
                market_filters={"doc_id":market.source.source_id,"kind":"narrative"},risk_categories=("financial","macro"),
                prepared_document=None if scenario=="gate_blocked" else prepared[case["case_id"]])
            save_outputs(state,root/name)
            results.append({"case":name,"report":state["report"].status,"gate":state["health_gate"].decision,
                "retry_budget":state["memory"].retry_budget_remaining,"model_mode":model.mode,"generation_requests":0,
                "mock_model_calls":len(model.calls),"retrieval_calls":index.retrieval_calls-retrieval_before,
                "contradictions":len(state["memory"].get_contradictions()),
                "same_evidence_snapshot":state["bull_result"].snapshot_hash==state["bear_result"].snapshot_hash if "bull_result" in state and "bear_result" in state else None,
                "values":{a.operation:str(a.display_value) for a in state["memory"].get_calculations()},
                "source_values":[{"metric":c.metric,"value":str(c.value),"currency":c.currency,"scale":c.scale,"period":c.period.model_dump(mode="json"),"evidence":[e.model_dump(mode="json") for e in c.evidence]} for c in state["memory"].get_claims() if c.claim_type=="raw_primitive"],
                "current_checked":sum(state["memory"].is_current_verified(c.claim_id) for c in state["memory"].get_claims()),
                "candidate_refs_current":all(state["memory"].reference(r.claim_id)==r for c in state["memory"].get_claims() for r in c.candidate_claim_refs),
                "current_calculation_inputs":all(state["memory"].get_calculation_freshness(c.calculation_ref)=="current" for c in state["memory"].get_claims() if c.calculation_ref),
                "retry_execution":state.get("retry_execution",{}).get("nodes"),
                "retry":[d.model_dump(mode="json") for d in state["memory"].get_retry_decisions()]})
        except Exception as exc:
            results.append({"case":name,"error":type(exc).__name__+": "+str(exc)})
        (root/"results.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
    print(json.dumps(results,indent=2))
    if any("error" in r for r in results):
        raise SystemExit(1)


if __name__=="__main__":
    main()
