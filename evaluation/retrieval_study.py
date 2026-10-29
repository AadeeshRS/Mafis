"""Post-inference relevance scoring against an existing real MiniLM index."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from evaluation.batch2 import score_retrieval
from rag.retriever import SharedRetriever


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--index",default="output/batch2/demo_final/source_index")
    parser.add_argument("--output",default="output/batch2/retrieval_results.json")
    args=parser.parse_args()
    if not Path(args.index).is_dir():
        parser.error("Run the real MiniLM demonstration before post-inference scoring")
    index=SharedRetriever(path=Path(args.index))
    separate=json.loads(Path("tests/fixtures/retrieval_validation.json").read_text())
    cases=json.loads(Path("tests/fixtures/phase1_cases.json").read_text())["cases"]
    results={}
    for case in cases:
        labels=(json.loads(Path("tests/fixtures/nvidia_2024/retrieval_queries.json").read_text()) if case["case_id"]=="nvidia_2024" else separate[case["case_id"]])["queries"]
        source_id="sha256:"+sha256(Path(case["document"]["path"]).read_bytes()).hexdigest()
        results[case["case_id"]]=score_retrieval(index,source_id,labels,k=5)
    Path(args.output).write_text(json.dumps({"mode":"real local Chroma/ONNX MiniLM, labelled development queries; no model generation", "results":results},indent=2),encoding="utf-8")
    print(json.dumps({k:{n:v for n,v in r.items() if n!="rows"} for k,r in results.items()},indent=2))


if __name__=="__main__":
    main()
