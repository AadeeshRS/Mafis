"""Dated descriptive quotations through the single shared retriever.

Selection is constrained and deterministic, not free-form research or live news
discovery. Optional llm is retained for compatibility and is never called.
"""
from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
import re
from typing import Any, Literal

from agents.contracts import AgentIssue
from memory.shared_memory import Claim, ClaimVersionRef, EvidenceModel, FiscalPeriod, SharedMemory, SourceDocument
from rag.models import RetrievalHit, SourceChunk
from rag.retriever import RetrievalUnavailable


class MarketResult(EvidenceModel):
    status: Literal["success", "partial", "failed"]
    claim_refs: tuple[ClaimVersionRef, ...] = ()
    issues: tuple[AgentIssue, ...] = ()
    as_of: date | None = None
    selection_method: Literal["constrained_source_quotes"] = "constrained_source_quotes"


def cutoff_date(value: date | datetime | None) -> date | None:
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("as_of datetime must be timezone aware")
        return value.date()
    if value is not None and type(value) is not date:
        raise ValueError("as_of must be a date or aware datetime")
    return value


def check_source_cutoff(source: SourceDocument, as_of: date | datetime | None,
                        memory: SharedMemory | None = None) -> None:
    cutoff = cutoff_date(as_of)
    if cutoff is None:
        return
    if market_source_date(source, memory) > cutoff:
        raise ValueError("Source postdates requested temporal cutoff")
    if source.published_at is not None:
        if ((isinstance(as_of, datetime) and source.published_at > as_of)
                or source.published_at.date() > cutoff):
            raise ValueError("Source publication postdates requested temporal cutoff")
    elif source.source_type in ("annual_report", "filing"):
        raise ValueError("Historical cutoff cannot establish availability of an undated filing")


def market_source_date(source: SourceDocument, memory: SharedMemory | None = None) -> date:
    """Use explicit metadata or an actual statement date, never today's date."""
    if source.as_of_date is not None:
        return source.as_of_date
    if source.published_at is not None:
        return source.published_at.date()
    if source.annual_period_ends:
        return max(source.annual_period_ends)
    if memory is not None:
        dates = [c.period.end_date for c in memory.get_claims()
                 if c.claim_type == "raw_primitive" and c.period is not None
                 and any(e.source_id == source.source_id for e in c.evidence)]
        if dates:
            return max(dates)
    raise ValueError("Source has no explicit publication/as-of or statement date")


_INSTRUCTIONS = re.compile(
    r"\b(ignore\s+(?:all\s+|the\s+|previous\s+)*(?:instructions|prompts)|"
    r"system\s*(?:prompt|message)|you\s+are\s+(?:an?\s+)?(?:assistant|agent)|"
    r"mark\s+.*\bverified|(?:call|execute|invoke)\s+(?:the\s+)?(?:tool|function)|"
    r"reveal\s+.*(?:key|secret)|buy\s+now)\b", re.I)


def _quote(chunk: SourceChunk, query: str) -> str:
    if _INSTRUCTIONS.search(chunk.text):
        raise ValueError("Source contains instruction-like text; no quotation selected")
    candidates = [m.group().strip() for m in re.finditer(r"[^\n.!?]+(?:[.!?](?=\s|$)|$)", chunk.text)]
    candidates = [q for q in candidates if 35 <= len(q) <= 600 and re.search(r"[A-Za-z]", q)]
    if not candidates:
        raise ValueError("No bounded descriptive source sentence available")
    words = set(re.findall(r"[a-z]{3,}", query.casefold()))
    return max(candidates, key=lambda q: len(words & set(re.findall(r"[a-z]{3,}", q.casefold()))))


def validate_market_claim(claim: Claim, source: SourceDocument,
                          memory: SharedMemory | None = None) -> None:
    """Structural check; fresh retrieval separately validates the quote and locator."""
    dated = market_source_date(source, memory)
    if (claim.agent != "MarketAgent" or claim.claim_type != "qualitative"
            or len(claim.evidence) != 1 or claim.value is not None or claim.metric != "market_context"
            or claim.calculation_ref or claim.candidate_claim_refs or claim.supports_claim_ids
            or claim.unit is not None or claim.currency is not None or claim.accounting_scope is not None or claim.scale != 1
            or claim.entity != source.entity or claim.period != FiscalPeriod(
                kind="instant", end_date=dated, label=f"Historical source context as of {dated.isoformat()}")):
        raise ValueError("Market finding does not match its constrained source/date contract")
    evidence = claim.evidence[0]
    if (evidence.source_id != source.source_id or evidence.source != source.title
            or evidence.source_url != source.source_url or evidence.source_type != source.source_type
            or claim.claim != f"Historical source context as of {dated.isoformat()}: {evidence.quote}"
            or _INSTRUCTIONS.search(evidence.quote)):
        raise ValueError("Market finding changed source identity or canonical quotation")


class MarketAgent:
    def __init__(self, memory: SharedMemory, retriever, llm=None):
        self.memory, self.retriever, self.llm = memory, retriever, llm

    def research(self, query: str, filters: dict[str, Any] | None = None,
                 as_of: date | datetime | None = None) -> MarketResult:
        issues, refs = [], []
        try:
            cutoff = cutoff_date(as_of)
            if not isinstance(query, str) or not query.strip():
                raise ValueError("Market research requires a nonblank query")
            hits = self.retriever.retrieve(query, filters=filters, top_k=5)
        except (RetrievalUnavailable, ValueError, TypeError) as exc:
            return MarketResult(status="failed", issues=(AgentIssue(code="market_retrieval_unavailable", message=str(exc)),))
        seen = set()
        for hit in hits:
            try:
                if not isinstance(hit, RetrievalHit):
                    raise ValueError("Shared retrieval must return typed RetrievalHit records")
                chunk = SourceChunk.model_validate(hit.chunk.model_dump(round_trip=True))
                source = chunk.source
                try:
                    existing = self.memory.get_source(source.source_id)
                except KeyError:
                    existing = self.memory.register_source(source)
                if existing != source:
                    raise ValueError("Retrieved source differs from registered immutable source")
                dated = market_source_date(source, self.memory)
                check_source_cutoff(source, as_of, self.memory)
                quote = _quote(chunk, query)
                key = (source.source_id, quote)
                if key in seen:
                    continue
                evidence = chunk.evidence.model_copy(update={"quote": quote,
                    "locator": chunk.evidence.locator + f";quote-offset={chunk.text.index(quote)}"})
                if not self.retriever.validate_evidence(evidence):
                    raise ValueError("Quote/locator failed shared retriever evidence check")
                identity = sha256((source.source_id + "|" + evidence.locator + "|" + quote).encode()).hexdigest()
                identifier = "market:" + identity
                claim = Claim(claim_id=identifier, agent="MarketAgent", claim_type="qualitative",
                    entity=source.entity, metric="market_context", claim=f"Historical source context as of {dated.isoformat()}: {quote}",
                    period=FiscalPeriod(kind="instant", end_date=dated, label=f"Historical source context as of {dated.isoformat()}"),
                    evidence=(evidence,), support_level="single_source", verification_status="pending")
                validate_market_claim(claim, source, self.memory)
                try:
                    old = self.memory.get_current(identifier)
                except KeyError:
                    self.memory.append(claim)
                else:
                    validate_market_claim(old, source, self.memory)
                refs.append(self.memory.reference(identifier))
                seen.add(key)
            except (ValueError, TypeError, KeyError, RetrievalUnavailable) as exc:
                issues.append(AgentIssue(code="market_evidence_rejected", message=str(exc)))
        if not refs and not issues:
            issues.append(AgentIssue(code="missing_market_evidence", message="No dated market source matched the shared query"))
        return MarketResult(status="partial" if refs and issues else "success" if refs else "failed",
                            claim_refs=tuple(refs), issues=tuple(issues), as_of=cutoff)
