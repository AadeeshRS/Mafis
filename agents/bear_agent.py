"""Bear Agent — builds negative case from verified claims only.

Constrained to cite only Shared Memory claim IDs with
verification_status == verified. Introduces no new evidence.
"""

from __future__ import annotations


class BearAgent:
    """Constructs the evidence-backed bearish case."""

    def build_case(self, verified_claim_ids: list[str]) -> dict[str, object]:
        """Build the bear case from verified claims.

        Args:
            verified_claim_ids: Claim IDs with verification_status == verified only.

        Returns:
            Structured argument citing existing claim IDs only.
        """
        raise NotImplementedError
