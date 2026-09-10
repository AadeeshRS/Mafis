"""Critic Agent — mechanical contradiction check + LLM explanation; decides re-analysis.

Cross-references structured fields rule-first (LLM explains flagged conflicts,
never discovers them from scratch). Writes findings back to Shared Memory.
Respects the shared single-iteration re-analysis cap.
"""

from __future__ import annotations

from typing import Any


class CriticAgent:
    """Detects contradictions and decides on scoped re-analysis."""

    def check_contradictions(
        self, bull_case: dict[str, Any], bear_case: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Mechanically cross-reference structured Bull/Bear/underlying claims.

        Args:
            bull_case: Structured Bull output.
            bear_case: Structured Bear output.

        Returns:
            List of contradiction finding dicts.
        """
        raise NotImplementedError

    def decide_reanalysis(
        self, contradictions: list[dict[str, Any]], retry_used: bool
    ) -> dict[str, Any]:
        """Decide whether to trigger scoped re-analysis or mark unresolved.

        Args:
            contradictions: Findings from check_contradictions.
            retry_used: Whether the single shared retry budget is spent.

        Returns:
            Decision dict with re-analysis scope or unresolved flag (never exceeds cap of 1).
        """
        raise NotImplementedError
