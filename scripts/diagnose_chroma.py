"""Non-destructive Chroma lifecycle reproduction in a fresh TEMP directory only."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile

import chromadb
from chromadb.config import Settings


def diagnose():
    # No reset/delete/migration of any collection, including the diagnostic one.
    path = Path(tempfile.mkdtemp(prefix="mafis_chroma_diagnostic_"))
    settings = Settings(anonymized_telemetry=False)
    first = chromadb.PersistentClient(path=str(path), settings=settings)
    collection = first.get_or_create_collection("provider_lifecycle", embedding_function=None)
    checks = []
    try:
        for company in range(3):
            ids = [f"doc{company}_chunk{i}" for i in range(140)]
            for start in range(0, 140, 64):
                batch = ids[start:start + 64]
                collection.add(ids=batch, documents=[f"public document {company}" for _ in batch],
                    metadatas=[{"doc_id": f"doc{company}", "page": 1} for _ in batch],
                    embeddings=[[1.0, float(company + 1), 0.5] for _ in batch])
            second = chromadb.PersistentClient(path=str(path), settings=settings)
            other = second.get_collection("provider_lifecycle", embedding_function=None)
            rows = other.get(where={"doc_id": f"doc{company}"})
            hits = other.query(query_embeddings=[[1.0, float(company + 1), 0.5]],
                n_results=5, where={"$and": [{"doc_id": f"doc{company}"}, {"page": 1}]})
            checks.append({"stage": f"multi_client_doc{company}", "passed": len(rows["ids"]) == 140
                and len(hits["ids"][0]) == 5 and all(i.startswith(f"doc{company}_") for i in hits["ids"][0])})
        checks.append({"stage": "missing_document_filter", "passed": not collection.query(
            query_embeddings=[[1.0, 1.0, 0.5]], n_results=5, where={"doc_id": "missing"})["ids"][0]})
        code = """import json,sys,chromadb
from chromadb.config import Settings
c=chromadb.PersistentClient(path=sys.argv[1],settings=Settings(anonymized_telemetry=False)).get_collection('provider_lifecycle',embedding_function=None)
print(json.dumps({'count':c.count(),'filtered':len(c.get(where={'doc_id':'doc2'})['ids'])}))
"""
        reopened = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, text=True, timeout=30)
        values = json.loads(reopened.stdout) if reopened.returncode == 0 else {}
        checks.append({"stage": "fresh_process_reopen", "passed": values == {"count": 420, "filtered": 140}})
        return {"status": "passed" if all(c["passed"] for c in checks) else "failed",
            "isolated_temp": True, "existing_source_collection_touched": False, "rows": collection.count(),
            "checks": checks, "prior_failure_reproduced": False,
            "root_cause": "unknown; successful lifecycle checks do not establish historical failure cause"}
    except Exception as exc:
        return {"status": "failed", "error_type": type(exc).__name__, "checks": checks,
            "isolated_temp": True, "existing_source_collection_touched": False, "root_cause": "unknown"}


if __name__ == "__main__":
    result = diagnose()
    output = Path("output/controller_batch1/provider_chroma.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
