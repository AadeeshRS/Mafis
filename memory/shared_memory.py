"""Shared Memory / Evidence Store — central append-only, versioned state.

All agents read structured data (never each other's free text) and append
new versioned entries (never overwrite in place). Every claim needs a
citation or calculation reference. Confidence is a rubric label, not a raw
probability. See useful_md_files/memory.md for the authoritative spec.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

AgentName = Literal[
    "DocumentAgent",
    "FinancialAgent",
    "MarketAgent",
    "RiskAgent",
    "Verification",
    "Critic",
    "Bull",
    "Bear",
]

ConfidenceLabel = Literal[
    "supported_2plus_sources",
    "single_source_unverified",
    "contradicted",
    "unverified",
]

VerificationStatus = Literal["verified", "unsupported", "flagged", "pending"]


class Evidence(BaseModel):
    """Single evidence pointer for a claim."""

    source: str = Field(description="Document/source name")
    page: int = Field(description="Page number")
    section: str | None = Field(default=None, description="Section name if known")
    year: int | None = Field(default=None, description="Fiscal year if applicable")


class Claim(BaseModel):
    """Versioned, structured claim per memory.md schema."""

    claim_id: str = Field(description="Unique claim identifier")
    agent: AgentName = Field(description="Authoring agent")
    claim: str = Field(description="Claim text")
    evidence: list[Evidence] = Field(default_factory=list)
    calculation_ref: str | None = Field(
        default=None, description="Engine call ID, if applicable"
    )
    confidence: ConfidenceLabel = Field(description="Rubric label, not a probability")
    verification_status: VerificationStatus = Field(description="Verification state")
    version: int = Field(default=1, description="Starts at 1, increments on re-analysis")
    run_iteration: int = Field(
        default=0, description="0 for initial pass, 1 for the single allowed retry"
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SharedMemory:
    """Append-only, versioned claim store (no in-place overwrites)."""

    def __init__(self) -> None:
        """Initialize an empty in-memory store."""
        raise NotImplementedError

    def append(self, claim: Claim) -> Claim:
        """Append a new claim or new version; reject citation-less writes.

        Args:
            claim: Claim to append (must carry evidence or calculation_ref).

        Returns:
            The appended claim.
        """
        raise NotImplementedError

    def get_claims(
        self,
        agent: AgentName | None = None,
        verification_status: VerificationStatus | None = None,
        min_version_only: bool = False,
    ) -> list[Claim]:
        """Query claims with optional filters.

        Args:
            agent: Filter by authoring agent.
            verification_status: Filter by verification status.
            min_version_only: If True, return only the latest version per claim_id.

        Returns:
            Matching claims.
        """
        raise NotImplementedError

    def get_verification_health(self) -> dict[str, float | int]:
        """Aggregate verification stats for the Health Gate.

        Returns:
            Dict with total, unsupported_count, contradicted_count, unsupported_rate.
        """
        raise NotImplementedError

    def get_unresolved(self) -> dict[str, list[Any]]:
        """Return claims/contradictions still flagged at final state.

        Returns:
            Dict of unresolved/unsupported items for the report Limitations section.
        """
        raise NotImplementedError
