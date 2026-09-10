"""RAG ingest — chunk/embed/index documents.

Parses PDFs (pdfplumber/unstructured + Tesseract OCR fallback), chunks,
embeds, and indexes into Chroma/FAISS for the shared retriever.
"""

from __future__ import annotations

from typing import Any


def ingest_document(path: str) -> dict[str, Any]:
    """Chunk, embed, and index a single document.

    Args:
        path: Filesystem path to the source document.

    Returns:
        Ingest summary (chunks indexed, doc id, metadata).
    """
    raise NotImplementedError


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 100) -> list[str]:
    """Split text into overlapping chunks.

    Args:
        text: Raw document text.
        chunk_size: Max chunk length.
        overlap: Overlap between chunks.

    Returns:
        List of text chunks.
    """
    raise NotImplementedError
