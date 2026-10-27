"""MAFIS configuration — thresholds and caps.

Centralizes the Verification Health Gate threshold and the shared
re-analysis iteration cap so behavior is bounded and testable.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent / ".env"
# Stable across CLI working directories; process variables retain precedence.
load_dotenv(ENV_PATH, override=False)

VERIFICATION_HEALTH_GATE_THRESHOLD: float = float(
    os.getenv("VERIFICATION_HEALTH_GATE_THRESHOLD", "0.5")
)
"""Aggregate unsupported/contradicted rate above which the Health Gate fails (default 0.5)."""

MAX_REANALYSIS_ITERATIONS: int = int(os.getenv("MAX_REANALYSIS_ITERATIONS", "1"))
"""Shared total re-analysis budget across Health Gate and Critic triggers (default 1, never exceed)."""

# One shared, explicitly identified local embedding model. No automatic fallback.
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
CHROMA_COLLECTION = "mafis_sources_v2"
CHROMA_PATH = os.getenv("MAFIS_CHROMA_PATH", "chroma_db")
PRIMARY_MODEL = os.getenv("MAFIS_PRIMARY_MODEL", "gemini-3.8-flash")
DOCUMENT_MODEL = os.getenv("MAFIS_DOCUMENT_MODEL", PRIMARY_MODEL)
FINANCIAL_MODEL = os.getenv("MAFIS_FINANCIAL_MODEL", PRIMARY_MODEL)
