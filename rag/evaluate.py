"""Small page-relevance development evaluation; labels never enter inference."""

import argparse
import json
from pathlib import Path

from rag.ingest import ingest_document
from rag.retriever import SharedRetriever


def evaluate(retriever, labels, doc_id):
    rows = []
    for item in labels["queries"]:
        hits = retriever.retrieve(item["query"], {"doc_id": doc_id}, top_k=5)
        retrieved = [hit.chunk.evidence.page for hit in hits]
        expected = set(item["relevant_pages"])
        overlap = expected.intersection(retrieved)
        anchor = " ".join(item.get("source_anchor", "").casefold().split())
        covered = any(h.chunk.evidence.page in expected and anchor in " ".join(h.chunk.text.casefold().split()) for h in hits) if anchor else None
        source_correct = all(h.chunk.source.source_id == doc_id for h in hits)
        locators_correct = all(h.chunk.evidence.page and f"pdf-page={h.chunk.evidence.page};" in h.chunk.evidence.locator for h in hits)
        printed = item.get("printed_pages", {})
        locators_correct = locators_correct and all(h.chunk.evidence.printed_page == printed[str(h.chunk.evidence.page)] for h in hits if str(h.chunk.evidence.page) in printed)
        rows.append({"id": item["id"], "query": item["query"], "expected_pages": sorted(expected),
            "retrieved_pages": retrieved, "chunk_ids": [h.chunk.chunk_id for h in hits],
            "hit_at_5": bool(overlap), "recall_at_5": len(overlap) / len(expected),
            "passage_covered": covered, "source_filter_correct": source_correct, "locator_correct": locators_correct})
    return {"embedding_model": retriever.embedding_model, "relevance_unit": "PDF page",
        "query_count": len(rows), "hit_at_5": sum(r["hit_at_5"] for r in rows) / len(rows),
        "recall_at_5": sum(r["recall_at_5"] for r in rows) / len(rows),
        "passage_coverage": sum(bool(r["passage_covered"]) for r in rows)/len(rows),
        "source_filter_correct": all(r["source_filter_correct"] for r in rows),
        "locator_correct": all(r["locator_correct"] for r in rows), "per_query": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pdf", "source-url", "title", "entity", "labels", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    index = SharedRetriever()
    document = ingest_document(args.pdf, source_url=args.source_url, title=args.title, entity=args.entity, retriever=index)
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    result = evaluate(index, labels, document.source.source_id)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "per_query"}))


if __name__ == "__main__":
    main()
