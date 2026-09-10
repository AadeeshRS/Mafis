"""Document Agent — extracts primitives (numbers/facts) with page-level citations.

Single source of truth for extracted primitives. Uses the shared RAG
retrieval tool. Every claim requires a citation or it is rejected at write time.
"""

from __future__ import annotations

from typing import Any


class DocumentAgent:
    """Extracts cited primitives into Shared Memory via RAG."""

    def extract_primitives(self, query: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Extract numbers/facts with page-level citations.

        Args:
            query: Extraction query / company context.
            filters: Optional retrieval filters (doc, section, year).

        Returns:
            List of structured claim dicts with non-null evidence entries.
        """
        raise NotImplementedError
