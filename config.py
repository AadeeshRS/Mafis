"""MAFIS configuration — thresholds and caps.

Centralizes the Verification Health Gate threshold and the shared
re-analysis iteration cap so behavior is bounded and testable.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

VERIFICATION_HEALTH_GATE_THRESHOLD: float = float(
    os.getenv("VERIFICATION_HEALTH_GATE_THRESHOLD", "0.5")
)
"""Aggregate unsupported/contradicted rate above which the Health Gate fails (default 0.5)."""

MAX_REANALYSIS_ITERATIONS: int = int(os.getenv("MAX_REANALYSIS_ITERATIONS", "1"))
"""Shared total re-analysis budget across Health Gate and Critic triggers (default 1, never exceed)."""
