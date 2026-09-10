"""Verification Agent — checks claims against fresh RAG retrieval + deterministic results; assigns confidence.

Independently re-queries RAG to confirm citations (never trusts Document
Agent's self-reported citation blindly). Never checks against its own
knowledge: every check is grounded in a fresh retrieval or deterministic
result. Writes verified status back as a new Shared Memory version.
"""

from __future__ import annotations

from typing import Any


class VerificationAgent:
    """Retrieval-grounded claim verifier."""

    def verify_claim(self, claim_id: str) -> dict[str, Any]:
        """Verify a single claim via fresh retrieval / calculation reference.

        Args:
            claim_id: Claim to verify in Shared Memory.

        Returns:
            New-version claim dict with updated verification_status and rubric confidence.
        """
        raise NotImplementedError

    def verify_all(self) -> list[dict[str, Any]]:
        """Verify all pending claims in Shared Memory.

        Returns:
            List of new-version claim dicts with verification outcomes.
        """
        raise NotImplementedError
