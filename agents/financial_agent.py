"""Financial Agent — requests calculations, interprets results.

Reads primitives ONLY from Shared Memory (never re-reads raw PDFs — that is
Document Agent's job). Never computes numbers itself: every numeric result
must trace to a Deterministic Engine call ID. May use shared RAG retrieval
for contextual checks (e.g. debt covenant mention), not for re-extraction.
"""

from __future__ import annotations

from typing import Any


class FinancialAgent:
    """Interprets engine results from Shared Memory primitives."""

    def request_calculation(
        self, primitive_claim_ids: list[str], metric: str
    ) -> dict[str, Any]:
        """Build a structured calculation request for the Deterministic Engine.

        Args:
            primitive_claim_ids: Claim IDs of Document Agent primitives in Shared Memory.
            metric: Requested metric (e.g. revenue_growth, margin, leverage_ratio).

        Returns:
            Structured calc request dict for the engine.
        """
        raise NotImplementedError

    def interpret_result(self, calculation_ref: str) -> dict[str, Any]:
        """Interpret a deterministic engine result into a Shared Memory claim.

        Args:
            calculation_ref: Engine call ID whose numeric output is interpreted.

        Returns:
            Structured claim dict with calculation_ref set (no LLM-computed numbers).
        """
        raise NotImplementedError
