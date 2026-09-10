"""RAG retriever — shared retrieve(query, filters) tool.

Callable by every agent (Document, Financial, Market, Risk, Verification).
Returns ranked evidence chunks with metadata (doc, page, section, year).
"""

from __future__ import annotations

from typing import Any


def retrieve(
    query: str, filters: dict[str, Any] | None = None, top_k: int = 5
) -> list[dict[str, Any]]:
    """Retrieve ranked evidence chunks for a query.

    Args:
        query: Query string.
        filters: Optional metadata filters (doc, section, year).
        top_k: Number of chunks to return.

    Returns:
        Ranked evidence chunks with metadata.
    """
    raise NotImplementedError
