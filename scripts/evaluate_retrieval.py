"""Index the case manifest once and evaluate separate development/validation sets."""

import json
from pathlib import Path
from time import perf_counter

from rag.ingest import ingest_document
from rag.retriever import SharedRetriever
from rag.evaluate import evaluate


def main():
    cases=json.loads(Path("tests/fixtures/phase1_cases.json").read_text())["cases"]
    validation=json.loads(Path("tests/fixtures/retrieval_validation.json").read_text())
    index=SharedRetriever()
    results={"collection":index.collection.name,"chunk_schema":2,"reports":{}}
    for case in cases:
        start=perf_counter()
        document=ingest_document(**case["document"],retriever=index)
        labels=json.loads(Path("tests/fixtures/nvidia_2024/retrieval_queries.json").read_text()) if case["case_id"]=="nvidia_2024" else validation[case["case_id"]]
        score=evaluate(index,labels,document.source.source_id)
        score["index_and_evaluation_ms"]=(perf_counter()-start)*1000
        score["missing_document_returns_empty"]=not index.retrieve("revenue",{"doc_id":"sha256:"+"0"*64})
        results["reports"][case["case_id"]]=score
        print(json.dumps({"case":case["case_id"],**{k:v for k,v in score.items() if k!="per_query"}}),flush=True)
    rows=[r for key,score in results["reports"].items() if key!="nvidia_2024" for r in score["per_query"]]
    results["validation_aggregate"]={"queries":len(rows),"hit_at_5":sum(r["hit_at_5"] for r in rows)/len(rows),"recall_at_5":sum(r["recall_at_5"] for r in rows)/len(rows),"passage_coverage":sum(r["passage_covered"] for r in rows)/len(rows)}
    out=Path("output/phase1_acceptance/retrieval_results.json");out.parent.mkdir(exist_ok=True,parents=True)
    out.write_text(json.dumps(results,indent=2)+"\n",encoding="utf-8")


if __name__=="__main__":main()
