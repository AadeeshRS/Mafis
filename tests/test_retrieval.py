"""Real PDF chunks + real Chroma, with explicitly mocked embeddings (offline)."""

import pytest

from rag.ingest import chunk_text
from rag.models import IndexedDocument
from rag.retriever import RetrievalUnavailable, SharedRetriever


def test_page_chunks_and_source_cells(prepared_document):
    document = prepared_document
    assert document.page_count == 187 and not document.limitations
    assert len({c.chunk_id for c in document.chunks}) == len(document.chunks)
    assert all(c.evidence.page and c.evidence.source_id == document.source.source_id for c in document.chunks)
    assert any(c.evidence.page == 9 and c.evidence.bbox is None for c in document.chunks)
    cells = [cell for chunk in document.chunks for cell in chunk.cells]
    assert len(cells) == 6
    assert {cell.evidence.page for cell in cells} == {150, 152}
    assert all(cell.evidence.quote in chunk.text for chunk in document.chunks for cell in chunk.cells)
    assert all(cell.evidence.period_header in chunk.text and cell.evidence.scale_header in chunk.text
               for chunk in document.chunks for cell in chunk.cells)


def test_idempotence_filters_and_detached_reads(prepared_document, offline_retriever):
    index = offline_retriever
    assert index.index(prepared_document) == len(prepared_document.chunks)
    assert index.index(prepared_document) == 0
    hits = index.retrieve("current assets", {"doc_id": prepared_document.source.source_id,
        "page": 152, "kind": "table", "metric": "current_assets", "year": 2024,
        "period_end": "2024-01-28"})
    assert len(hits) == 1 and hits[0].rank == 1
    assert hits[0].chunk.cells[0].metric == "current_assets"
    hits[0].chunk.evidence.__dict__["page"] = 999
    assert index.retrieve("assets", {"metric": "current_assets"})[0].chunk.evidence.page == 152
    assert index.retrieve("absent", {"doc_id": "sha256:" + "0" * 64}) == []
    matched = index.retrieve("headquarters", {"text_contains": "Our headquarters"})
    assert matched and all("Our headquarters" in h.chunk.text for h in matched)


def test_collection_cannot_silently_switch_models(offline_retriever):
    with pytest.raises(ValueError, match="configuration mismatch"):
        SharedRetriever(client=offline_retriever.client, collection_name=offline_retriever.collection.name,
            embedder=offline_retriever.embedder, embedding_model="another-model")


def test_source_context_cannot_change_under_same_hash(prepared_document, offline_retriever):
    document = IndexedDocument(source=prepared_document.source, chunks=prepared_document.chunks[:1], page_count=187)
    offline_retriever.index(document)
    changed = document.model_copy(update={"source": document.source.model_copy(update={"title": "Different"})})
    with pytest.raises(ValueError, match="identity/context"):
        offline_retriever.index(changed)


def test_missing_embeddings_are_explicit(prepared_document, offline_retriever):
    def unavailable(texts):
        raise OSError("download blocked")
    offline_retriever.embedder = unavailable
    with pytest.raises(RetrievalUnavailable):
        offline_retriever.index(prepared_document)
    assert offline_retriever.collection.count() == 0


@pytest.mark.parametrize(("query", "filters", "top_k"), [
    ("", None, 5), ("query", None, 0), ("query", {"unknown": "x"}, 5),
    ("query", {"page": -1}, 5),
])
def test_bad_queries_rejected(offline_retriever, query, filters, top_k):
    with pytest.raises(ValueError):
        offline_retriever.retrieve(query, filters, top_k)


def test_empty_collection_is_explicit(offline_retriever):
    assert offline_retriever.retrieve("no evidence") == []


def test_chunking_preserves_text_and_bounds():
    text = "first line\n" * 100
    chunks = chunk_text(text, chunk_size=100, overlap=20)
    assert chunks and all(0 < len(c) <= 100 for c in chunks)
    assert chunks == chunk_text(text, chunk_size=100, overlap=20)
    assert chunk_text("") == []
    with pytest.raises(ValueError):
        chunk_text(text, 10, 10)


def test_section_chunks_are_contiguous_source_quotes(prepared_document):
    import pdfplumber
    from pathlib import Path

    with pdfplumber.open(Path("tests/fixtures/nvidia_2024/annual_report.pdf")) as pdf:
        text = "\n".join(x["text"] for x in pdf.pages[154].extract_text_lines())
    sections = [c for c in prepared_document.chunks if c.evidence.page == 155
                and ";offset=section:" in c.evidence.locator]
    assert sections and any(c.evidence.section == "Fiscal Year" for c in sections)
    assert all(c.text in text and c.evidence.quote == c.text for c in sections)


def test_retrieval_evaluation_detects_wrong_source_and_locator(prepared_document):
    from rag.evaluate import evaluate
    from rag.models import RetrievalHit
    from types import SimpleNamespace

    chunk = prepared_document.chunks[0]
    broken = chunk.model_copy(update={"evidence": chunk.evidence.model_copy(update={"locator": "wrong"})})
    index = SimpleNamespace(embedding_model="test", retrieve=lambda *a, **k: [RetrievalHit(chunk=broken, rank=1, distance=0)])
    labels = {"queries": [{"id": "q", "query": "test", "relevant_pages": [chunk.evidence.page], "source_anchor": "absent phrase"}]}
    score = evaluate(index, labels, "sha256:" + "0" * 64)
    assert score["hit_at_5"] == 1 and score["passage_coverage"] == 0
    assert not score["source_filter_correct"] and not score["locator_correct"]


@pytest.mark.parametrize("operation", ("index", "retrieve", "page_chunks"))
def test_chroma_failure_is_explicit(offline_retriever, prepared_document, monkeypatch, operation):
    from chromadb.errors import InternalError
    from types import SimpleNamespace

    def broken(**kwargs):
        raise InternalError("Error finding id")
    monkeypatch.setattr(offline_retriever, "collection", SimpleNamespace(get=broken, count=lambda: 1, query=broken))
    with pytest.raises(RetrievalUnavailable, match="InternalError"):
        if operation == "index": offline_retriever.index(prepared_document)
        elif operation == "retrieve": offline_retriever.retrieve("test")
        else: offline_retriever.page_chunks(prepared_document.source.source_id, 150)
