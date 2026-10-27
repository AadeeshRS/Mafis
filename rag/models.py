"""Source-content contracts, not an alternative run/claim store."""

from decimal import Decimal
from typing import Literal

from memory.shared_memory import Evidence, EvidenceModel, FiscalPeriod, SourceDocument


class TableCell(EvidenceModel):
    """A deterministically parsed source cell for grounding proposed extractions."""

    cell_id: str
    metric: str
    value: Decimal
    unit: Literal["currency"]
    currency: str
    scale: int
    period: FiscalPeriod
    accounting_scope: Literal["consolidated", "standalone"]
    evidence: Evidence


class SourceChunk(EvidenceModel):
    chunk_id: str
    source: SourceDocument
    kind: Literal["narrative", "table"]
    text: str
    evidence: Evidence
    cells: tuple[TableCell, ...] = ()


class IndexedDocument(EvidenceModel):
    source: SourceDocument
    chunks: tuple[SourceChunk, ...]
    page_count: int
    limitations: tuple[str, ...] = ()


class RetrievalHit(EvidenceModel):
    chunk: SourceChunk
    rank: int
    distance: float
