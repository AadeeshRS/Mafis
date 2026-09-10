"""Market Agent — industry/catalyst research.

Researches industry trends and external catalysts via the shared RAG tool.
Findings are descriptive of market conditions, not evaluative of
company-specific risk (that is Risk Agent's job).
"""

from __future__ import annotations

from typing import Any


class MarketAgent:
    """Produces market-context claims via shared retrieval."""

    def research(self, query: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Research industry trends and catalysts.

        Args:
            query: Company/query context.
            filters: Optional retrieval filters.

        Returns:
            List of structured market-finding claim dicts.
        """
        raise NotImplementedError
