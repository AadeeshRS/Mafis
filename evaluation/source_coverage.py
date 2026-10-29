"""Record extraction-profile failures without reading gold or tuning inference."""
import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from rag.ingest import extract_financial_facts


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--cases",default="tests/fixtures/batch2_cases.json")
    parser.add_argument("--output",default="output/batch2/source_coverage.json")
    args=parser.parse_args()
    data=Path(args.cases).read_bytes();cases=json.loads(data)["cases"]
    rows=[]
    for case in cases:
        row={"case_id":case["case_id"],"split":case["split"],"model_calls":0,"mode":"offline source-profile compatibility; gold not opened"}
        doc=case.get("document")
        if doc is None:
            row.update(status="source_unavailable",attempts=case["attempts"],accepted_primitives=0)
        else:
            start=perf_counter()
            result=extract_financial_facts(doc["path"],source_url=doc["source_url"],title=doc["title"],entity=doc["entity"])
            row.update(status="supported" if result.ok else "extraction_failure_or_partial",accepted_primitives=len(result.claims),
                source_url=doc["source_url"],source_sha256=sha256(Path(doc["path"]).read_bytes()).hexdigest(),
                failures=[asdict(f) for f in result.failures],latency_ms=(perf_counter()-start)*1000,
                source_claims=[c.model_dump(mode="json") for c in result.claims])
        if doc is not None:
            # Scoring/annotation access happens only after source inference.
            gold=json.loads(Path(case["gold"]).read_text(encoding="utf-8"))
            expected={(v["metric"],v["period_end"]):v for v in gold["values"]}
            row["annotated_available_requested_facts"]=len(expected)
            row["annotations_primary_ready"]=case.get("annotation_ready_for_primary",True)
            row["annotation_method"]=gold.get("annotation_method")
            row["unavailable_or_ambiguous"]=gold.get("ambiguities",[])
            row["source_fact_matches"]=sum(str(c.value)==expected.get((c.metric,str(c.period.end_date)),{}).get("value") for c in result.claims)
            from engine.financial_engine import FinancialEngine,CalculationRequest
            from memory.shared_memory import SharedMemory
            memory=SharedMemory();memory.register_source(result.source)
            for claim in result.claims:memory.append(claim)
            calculations=[]
            for op in ("revenue_growth","operating_margin","net_margin","current_ratio"):
                inputs={}
                for role,metric in FinancialEngine.operation_inputs(op):
                    found=sorted((c for c in result.claims if c.metric==metric),key=lambda c:c.period.end_date,reverse=True)
                    index=1 if role=="previous_revenue" else 0
                    if len(found)>index:inputs[role]=memory.reference(found[index].claim_id)
                if len(inputs)!=2:
                    calculations.append({"operation":op,"status":"missing_inputs"});continue
                outcome=FinancialEngine(memory).calculate(CalculationRequest(operation=op,inputs=inputs))
                calculations.append({"operation":op,"status":outcome.status,"value":str(outcome.artifact.output_value) if outcome.artifact else None,
                    "artifact":outcome.artifact.model_dump(mode="json") if outcome.artifact else None,
                    "findings":[f.model_dump(mode="json") for f in outcome.findings]})
            if len(gold["values"])==6:
                from evaluation.metrics import expectations,numerically_equal
                _,oracle=expectations(gold)
                for calculation in calculations:
                    expected_value=oracle[calculation["operation"]]
                    calculation.update(expected=str(expected_value),correct=numerically_equal(calculation.get("value"),expected_value))
            row["derived_operations"]=calculations
            row["verification_scope"]="Extraction/arithmetic compatibility only; full fresh checked eligibility separately tested in full-flow demonstrations"
        rows.append(row)
        Path(args.output).parent.mkdir(parents=True,exist_ok=True)
        Path(args.output).write_text(json.dumps({"split_manifest_sha256":sha256(data).hexdigest(),"rows":rows,
            "note":"Failures remain in accounting. No extractor/prompt/threshold tuning follows this compatibility probe. Not held-out live model evaluation."},indent=2),encoding="utf-8")
        print(case["case_id"],row["status"],row["accepted_primitives"],flush=True)


if __name__=="__main__":
    main()
