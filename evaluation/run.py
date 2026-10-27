"""Controlled Phase 1 harness. Live runs require independently confirmed free tier."""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
from time import perf_counter

from config import PRIMARY_MODEL
from gemini import GeminiAdapter, GeminiSettings
from graph import run_pipeline, save_outputs
from rag.models import SourceChunk
from rag.retriever import SharedRetriever
from evaluation.baseline import SingleLLMBaseline, context_digest, render_baseline, PROMPT_VERSION
from evaluation.metrics import score_mafis, score_baseline, usage
from agents.document_agent import CONTEXT_POLICY_VERSION


def compare_case(case, index, *, mocked=True, request_budget=None, free_tier_confirmed=False):
    if not mocked and not free_tier_confirmed:
        raise ValueError("Live comparison requires independently confirmed project free tier/quota")
    settings=GeminiSettings.from_env(PRIMARY_MODEL)
    if mocked:
        from tests.fakes import ReplaySDKClient
        client=ReplaySDKClient()
    else: client=None
    adapters=[GeminiAdapter(settings,client=client,allow_live=not mocked,request_budget=request_budget) for _ in range(3)]
    # The principal comparison uses the SAME ID and settings in both MAFIS roles
    # and the baseline. No Flash-Lite substitution is permitted here.
    assert all(a.settings==settings for a in adapters)
    output=Path("output/phase1_acceptance")/case["case_id"]
    before=index.retrieval_calls;start=perf_counter()
    state=run_pipeline(case["question"],case["document"],retriever=index,document_llm=adapters[0],financial_llm=adapters[1])
    mafis_ms=(perf_counter()-start)*1000
    mafis_retrievals=index.retrieval_calls-before
    save_outputs(state,output/"mafis",adapters=adapters[:2])
    ids=list(state.get("document_result").retrieved_chunk_ids) if state.get("document_result") else []
    rows=index.collection.get(ids=ids,include=["metadatas"]) if ids else {"metadatas":[]}
    mafis_context=tuple(SourceChunk.model_validate_json(m["payload"]) for m in rows["metadatas"])
    before=index.retrieval_calls
    baseline=SingleLLMBaseline(adapters[2],index).run(case["question"],case["document"])
    baseline_retrievals=index.retrieval_calls-before
    (output/"baseline.json").write_text(baseline.model_dump_json(indent=2),encoding="utf-8")
    (output/"baseline.md").write_text(render_baseline(baseline),encoding="utf-8")
    # Evaluation ground truth is opened only after both inference runs finish.
    gold=json.loads(Path(case["gold"]).read_text())
    measured={"mafis":score_mafis(state,index,gold),"single_llm":score_baseline(baseline,gold)}
    measured["mafis"].update(usage(adapters[:2],mocked=mocked),latency_ms=mafis_ms,retrieval_calls=mafis_retrievals,
        calculation_calls=len(state["memory"].get_calculations())+sum(i.code=="calculation_rejected" for i in state.get("financial_result").issues) if state.get("financial_result") else 0)
    measured["single_llm"].update(usage(adapters[2:],mocked=mocked),latency_ms=baseline.latency_ms,retrieval_calls=baseline_retrievals,calculation_calls=0)
    same_context=context_digest(mafis_context)==baseline.context_sha256
    manifest={"manifest_version":"1.0","case_id":case["case_id"],"execution_mode":"mock" if mocked else "live",
        "comparison_status":"offline harness validation only; empirical comparison pending" if mocked else "live controlled comparison",
        "run_ids":{"mafis":state["memory"].run_id,"single_llm":baseline.run_id},
        "company":case["document"]["entity"],"question":case["question"],"document":case["document"],
        "source_hash":sha256(Path(case["document"]["path"]).read_bytes()).hexdigest(),
        "model_id":settings.model_id,"generation_settings":settings.model_dump(),
        "prompt_versions":{"document":"1.0","financial":"1.0","baseline":PROMPT_VERSION,"context":CONTEXT_POLICY_VERSION,"report":"1.0"},
        "retrieval":{"model":index.embedding_model,"collection":index.collection.name,"chunk_schema":2,"top_k":5,
                     "context_sha256":baseline.context_sha256,"identical_source_context":same_context},
        "stage_timings_ms":state["stage_timings_ms"],"packages":{p:version(p) for p in ("google-genai","pdfplumber","chromadb","langgraph")},
        "outputs":{"mafis":str(output/"mafis"),"baseline":str(output/"baseline.md")},
        "failures":[i.model_dump() for i in state["analysis_map"].issues]+list(baseline.issues),
        "limitations":["No independent verification in Phase 1","Both arms receive deterministic source-cell metadata plus identical retrieval policy",
            "Warm shared index; each arm includes its own PDF preparation and retrieval latency","Mock arithmetic is an explicit test double, not evidence of LLM reasoning"] if mocked else ["Stochastic live outputs need not repeat"],
        "measurements":measured}
    (output/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode",choices=("mock","live"),default="mock")
    parser.add_argument("--free-tier-confirmed",action="store_true",help="Caller has verified project billing tier and remaining free quota")
    parser.add_argument("--request-budget",type=int,default=24)
    args=parser.parse_args()
    if args.mode=="live" and not args.free_tier_confirmed:
        parser.error("Project free tier/quota must be independently confirmed before live generation")
    if not 1<=args.request_budget<=30: parser.error("Request budget must be between 1 and 30")
    path=Path("tests/fixtures/phase1_cases.json");cases=json.loads(path.read_text())["cases"]
    index=SharedRetriever();budget=[args.request_budget];results=[]
    for case in cases:
        try:
            result=compare_case(case,index,mocked=args.mode=="mock",request_budget=budget,free_tier_confirmed=args.free_tier_confirmed)
            results.append(result)
            print(json.dumps({"case":case["case_id"],"same_context":result["retrieval"]["identical_source_context"],"measurements":result["measurements"]}),flush=True)
        except Exception as exc:
            results.append({"case_id":case["case_id"],"pipeline_failure":type(exc).__name__,"message":str(exc)})
            print(json.dumps({"case":case["case_id"],"pipeline_failure":type(exc).__name__}),flush=True)
    out=Path("output/phase1_acceptance/comparison.json");out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({"execution_mode":args.mode,"created_utc":datetime.now(timezone.utc).isoformat(),
        "case_manifest_hash":sha256(path.read_bytes()).hexdigest(),"remaining_request_budget":budget[0],"runs":results},indent=2)+"\n",encoding="utf-8")


if __name__=="__main__":main()
