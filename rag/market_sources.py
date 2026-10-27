"""Immutable official public text excerpts for the existing shared source index.

Hashes identify UTF-8 excerpt bytes, not the entire remote HTML response.
No fetching, private index, model call or synthesized source text occurs here.
"""
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl

from memory.shared_memory import Evidence, EvidenceModel, SourceDocument
from rag.models import IndexedDocument, SourceChunk


class TextSnapshot(EvidenceModel):
    title: str = Field(min_length=1)
    entity: str = Field(min_length=1)
    source_url: HttpUrl
    source_type: Literal["news", "market_data", "other"]
    published_at: datetime
    retrieved_at: datetime
    as_of_date: date
    section: str = Field(min_length=1)
    text_file: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    capture_note: str = Field(min_length=1)


def prepare_market_snapshot(manifest_path: str | Path) -> IndexedDocument:
    manifest_path = Path(manifest_path)
    manifest = TextSnapshot.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    if Path(manifest.text_file).name != manifest.text_file or "/" in manifest.text_file or "\\" in manifest.text_file:
        raise ValueError("Snapshot text_file must be a local filename")
    data = (manifest_path.parent / manifest.text_file).read_bytes()
    if sha256(data).hexdigest() != manifest.sha256:
        raise ValueError("Snapshot excerpt hash does not match manifest")
    text = data.decode("utf-8")
    if not text.strip():
        raise ValueError("Snapshot excerpt is empty")
    if manifest.retrieved_at.utcoffset() is None or manifest.published_at.utcoffset() is None:
        raise ValueError("Snapshot timestamps must be timezone aware")
    if manifest.retrieved_at < manifest.published_at:
        raise ValueError("Snapshot retrieval precedes publication")
    source = SourceDocument(title=manifest.title, entity=manifest.entity, source_url=manifest.source_url,
        sha256=manifest.sha256, source_type=manifest.source_type, published_at=manifest.published_at,
        retrieved_at=manifest.retrieved_at, as_of_date=manifest.as_of_date)
    chunks, start = [], 0
    for paragraph in text.split("\n\n"):
        if paragraph.strip():
            offset = text.index(paragraph, start)
            end = offset + len(paragraph)
            identity = f"text-snapshot-v1|{source.source_id}|{offset}:{end}|{paragraph}"
            chunk_id = "chunk:" + sha256(identity.encode()).hexdigest()
            evidence = Evidence(source=source.title, source_id=source.source_id,
                source_url=source.source_url, source_type=source.source_type, section=manifest.section,
                year=manifest.as_of_date.year, quote=paragraph,
                locator=f"text-snapshot;chars={offset}:{end};chunk={chunk_id}")
            chunks.append(SourceChunk(chunk_id=chunk_id, source=source, kind="narrative",
                                      text=paragraph, evidence=evidence))
            start = end
    return IndexedDocument(source=source, chunks=tuple(chunks), page_count=0,
        limitations=("Selected official excerpts; hash identifies excerpt bytes, not full remote HTML.",
                     "Historical context only; no current-price or live-news inference.", manifest.capture_note))


def ingest_market_snapshot(manifest_path: str | Path, *, retriever) -> IndexedDocument:
    """Use the caller's existing shared retriever; never create another collection."""
    document = prepare_market_snapshot(manifest_path)
    retriever.index(document)
    return document


def validate_market_claim(claim, source, memory=None) -> None:
    """Shared canonical check used by independent Verification and Report.

    Imported lazily so snapshot preparation does not load an agent/retriever.
    Retrieval validation remains a separate, independent verifier responsibility.
    """
    from agents.market_agent import validate_market_claim as validate
    validate(claim, source, memory)
