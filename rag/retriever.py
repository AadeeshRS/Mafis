"""One source-content Chroma collection, reusable by every Phase 1 agent."""

from __future__ import annotations

from typing import Any
from functools import wraps

import chromadb
from chromadb.config import Settings
from chromadb.errors import ChromaError

from config import CHROMA_COLLECTION, CHROMA_PATH, EMBEDDING_MODEL
from rag.models import IndexedDocument, RetrievalHit, SourceChunk


class RetrievalUnavailable(RuntimeError):
    pass


def _source_store_operation(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ChromaError as exc:
            raise RetrievalUnavailable(f"Source index unavailable ({type(exc).__name__}); no source data substituted") from exc
    return guarded


class SharedRetriever:
    @_source_store_operation
    def __init__(self, *, path=CHROMA_PATH, client=None, collection_name=CHROMA_COLLECTION,
                 embedder=None, embedding_model=EMBEDDING_MODEL):
        if embedder is None:
            if embedding_model != EMBEDDING_MODEL:
                raise ValueError("Only the explicitly configured MiniLM model is supported")
            from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
            embedder = ONNXMiniLM_L6_V2(preferred_providers=["CPUExecutionProvider"])
        self.embedder = embedder
        self.embedding_model = embedding_model
        self.retrieval_calls = 0
        self.client = client if client is not None else chromadb.PersistentClient(
            path=str(path), settings=Settings(anonymized_telemetry=False))
        self.collection = self.client.get_or_create_collection(
            name=collection_name, embedding_function=None,
            metadata={"hnsw:space": "cosine", "embedding_model": embedding_model, "chunk_schema": 2})
        metadata = self.collection.metadata or {}
        if (metadata.get("embedding_model") != embedding_model
                or metadata.get("chunk_schema") != 2):
            raise ValueError("Collection embedding/chunk configuration mismatch; use a separate explicit index")

    def _embed(self, texts):
        try:
            return self.embedder(texts)
        except Exception as exc:
            raise RetrievalUnavailable(f"Embedding model {self.embedding_model} unavailable ({type(exc).__name__})") from exc

    @staticmethod
    def _metadata(chunk):
        # Chroma scalar metadata cannot represent None; zero denotes page-less text.
        metadata = {"doc_id": chunk.source.source_id, "page": chunk.evidence.page or 0,
            "printed_page": chunk.evidence.printed_page or "", "kind": chunk.kind,
            "section": chunk.evidence.section or "", "source_url": str(chunk.source.source_url),
            "sha256": chunk.source.sha256, "payload": chunk.model_dump_json(round_trip=True)}
        for cell in chunk.cells:
            metadata["metric_" + cell.metric] = True
            metadata["year_" + str(cell.period.end_date.year)] = True
            metadata["period_" + cell.period.end_date.isoformat()] = True
        return metadata

    @_source_store_operation
    def index(self, document: IndexedDocument) -> int:
        document = IndexedDocument.model_validate(document.model_dump(round_trip=True))
        pending = []
        existing = self.collection.get(where={"doc_id": document.source.source_id}, include=["metadatas"])
        known = dict(zip(existing["ids"], existing["metadatas"]))
        if known:
            old_source = SourceChunk.model_validate_json(next(iter(known.values()))["payload"]).source
            if old_source != document.source:
                raise ValueError("Document identity/context differs from its existing immutable index")
        for chunk in document.chunks:
            if chunk.source != document.source or chunk.evidence.source_id != document.source.source_id:
                raise ValueError("Chunk belongs to another document")
            metadata = self._metadata(chunk)
            if chunk.chunk_id in known:
                # Compare semantic payloads under the current schema. Older JSON
                # may omit newly added optional defaults; never rewrite the store.
                stored = dict(known[chunk.chunk_id])
                stored["payload"] = SourceChunk.model_validate_json(stored["payload"]).model_dump_json(round_trip=True)
                if metadata != stored:
                    raise ValueError("Stable chunk ID collides with different content")
            else:
                pending.append((chunk, metadata))
        for start in range(0, len(pending), 64):
            batch = pending[start:start + 64]
            self.collection.add(ids=[c.chunk_id for c, _ in batch],
                documents=[c.text for c, _ in batch], metadatas=[m for _, m in batch],
                embeddings=self._embed([c.text for c, _ in batch]))
        return len(pending)

    @staticmethod
    def _filters(filters):
        clauses = []
        for key, value in (filters or {}).items():
            if key in ("doc_id", "section", "kind") and isinstance(value, str):
                clauses.append({key: value})
            elif key == "page" and type(value) is int and value > 0:
                clauses.append({key: value})
            elif key in ("year", "period_end", "metric") and isinstance(value, (str, int)):
                prefix = {"year": "year_", "period_end": "period_", "metric": "metric_"}[key]
                clauses.append({prefix + str(value): True})
            else:
                raise ValueError(f"Unsupported retrieval filter: {key}")
        return clauses[0] if len(clauses) == 1 else {"$and": clauses} if clauses else None

    @_source_store_operation
    def retrieve(self, query: str, filters: dict[str, Any] | None = None, top_k: int = 5) -> list[RetrievalHit]:
        self.retrieval_calls += 1
        if not isinstance(query, str) or not query.strip() or type(top_k) is not int or top_k < 1:
            raise ValueError("A nonblank query and positive top_k are required")
        filters = dict(filters or {})
        contains = filters.pop("text_contains", None)
        if contains is not None and (not isinstance(contains, str) or not contains.strip()):
            raise ValueError("text_contains must be nonblank source text")
        where = self._filters(filters)
        count = self.collection.count()
        if count == 0:
            return []
        arguments = {"where": where} if where else {}
        if contains is not None:
            arguments["where_document"] = {"$contains": contains}
        result = self.collection.query(query_embeddings=self._embed([query]),
            n_results=min(top_k, count), include=["metadatas", "distances"], **arguments)
        rows = sorted(zip(result["ids"][0], result["metadatas"][0], result["distances"][0]),
                      key=lambda row: (row[2], row[0]))
        return [RetrievalHit(chunk=SourceChunk.model_validate_json(meta["payload"]), rank=index,
                             distance=float(distance)) for index, (_, meta, distance) in enumerate(rows, 1)]

    @_source_store_operation
    def page_chunks(self, source_id: str, page: int | None) -> tuple[SourceChunk, ...]:
        """Exact source lookup for citation validation; no semantic reranking."""
        rows = self.collection.get(where={"$and": [{"doc_id": source_id}, {"page": page or 0}]}, include=["metadatas"])
        return tuple(SourceChunk.model_validate_json(meta["payload"]) for meta in rows["metadatas"])

    def validate_evidence(self, evidence) -> bool:
        chunks = self.page_chunks(evidence.source_id, evidence.page)
        for chunk in chunks:
            source = chunk.source
            if (evidence.source != source.title or evidence.source_url != source.source_url
                    or evidence.source_type != source.source_type):
                continue
            if evidence in (source.currency_evidence, source.fiscal_calendar_evidence, source.annual_period_evidence):
                if " ".join(evidence.quote.split()) in " ".join(chunk.text.split()):
                    return True
            if any(evidence == cell.evidence for cell in chunk.cells):
                return True
            if (evidence.quote in chunk.text and evidence.bbox == chunk.evidence.bbox
                    and evidence.printed_page == chunk.evidence.printed_page
                    and evidence.locator == chunk.evidence.locator + f";quote-offset={chunk.text.index(evidence.quote)}"):
                return True
        return False


_shared = None


def get_shared_retriever() -> SharedRetriever:
    global _shared
    if _shared is None:
        _shared = SharedRetriever()
    return _shared


def retrieve(query: str, filters: dict[str, Any] | None = None, top_k: int = 5) -> list[RetrievalHit]:
    return get_shared_retriever().retrieve(query, filters, top_k)
