"""Bull Agent — builds positive case from verified claims only.

Constrained to cite only Shared Memory claim IDs with
verification_status == verified. Introduces no new evidence.
"""

from __future__ import annotations


class BullAgent:
    """Constructs the evidence-backed bullish case."""

    def build_case(self, verified_claim_ids: list[str]) -> dict[str, object]:
        """Build the bull case from verified claims.

        Args:
            verified_claim_ids: Claim IDs with verification_status == verified only.

        Returns:
            Structured argument citing existing claim IDs only.
        """
        raise NotImplementedError
