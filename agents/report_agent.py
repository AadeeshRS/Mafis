"""Report Generation Agent — synthesizes only supported findings + surfaces unresolved/unsupported items as Limitations.

Pulls claims, citations, confidence, contradictions, and unresolved flags
directly from Shared Memory (never re-derives from free text). Every prose
claim must trace to a claim_id. Unsupported/unresolved items appear only in
Limitations, never as settled fact.
"""

from __future__ import annotations

from typing import Any


class ReportAgent:
    """Synthesizes the final evidence-backed report from Shared Memory."""

    def generate_report(self) -> dict[str, Any]:
        """Pull final-state store and produce the report structure.

        Returns:
            Report dict (Executive Summary, Company Overview, Financial Health,
            Market Analysis, Risk Assessment, Valuation, Bull/Bear, Key
            Contradictions, Confidence/Uncertainty, Sources, Limitations).
        """
        raise NotImplementedError
