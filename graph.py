"""LangGraph wiring — nodes, edges, conditional routing, iteration cap.

Authoritative flow: Planner -> Document/Financial/Market/Risk ->
Verification -> Health Gate -> Bull/Bear -> Critic -> (scoped re-analysis,
max 1 total) -> Report. Health Gate failure skips Bull/Bear/Critic and
consumes the shared retry budget.
"""

from __future__ import annotations

from typing import Any

from config import MAX_REANALYSIS_ITERATIONS, VERIFICATION_HEALTH_GATE_THRESHOLD


def build_graph() -> Any:
    """Build and compile the LangGraph state graph.

    Returns:
        Compiled graph with conditional edges for the Health Gate,
        Critic decision, and the shared capped re-analysis loop.
    """
    raise NotImplementedError


def verification_health_gate(state: dict[str, Any]) -> str:
    """Route on aggregate unsupported/contradicted rate.

    Args:
        state: Graph state including verification stats.

    Returns:
        Route label: 'proceed' (below threshold) or 'reanalysis'/'unresolved'.
    """
    raise NotImplementedError


def should_reanalyze(state: dict[str, Any]) -> str:
    """Critic-gated re-analysis decision respecting the shared iteration cap.

    Args:
        state: Graph state including retry count and contradictions.

    Returns:
        Route label: 'reanalyze', 'unresolved', or 'report'.
    """
    raise NotImplementedError
