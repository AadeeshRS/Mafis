"""Planner Agent — builds the task/dependency graph, decides which agents run, computes re-analysis scope.

Single entry point for query routing. Owns the shared re-analysis budget
(max 1 total iteration across Health Gate and Critic triggers).
"""

from __future__ import annotations

from typing import Any


class PlannerAgent:
    """Plans task graph and scoped re-analysis within the retry budget."""

    def build_graph(self, query: str, has_documents: bool) -> dict[str, Any]:
        """Build the task/dependency graph for a query.

        Args:
            query: User query string.
            has_documents: Whether source documents were provided.

        Returns:
            Task graph with agent assignments and explicit dependencies
            (Financial waits on Document; Risk waits on Financial + Market).
        """
        raise NotImplementedError

    def compute_reanalysis_scope(
        self, contradiction_scope: dict[str, Any], retry_used: bool
    ) -> dict[str, Any]:
        """Compute the minimal subgraph to re-run for targeted re-analysis.

        Args:
            contradiction_scope: Implicated agent(s) flagged by Critic/Health Gate.
            retry_used: Whether the single shared retry budget is spent.

        Returns:
            Scoped re-run plan, or an unresolved marker if budget is spent.
        """
        raise NotImplementedError
