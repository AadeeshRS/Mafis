"""Bull Agent — builds positive case from verified claims only.

Constrained to cite only Shared Memory claim IDs with
verification_status == verified. Introduces no new evidence.
"""

from agents.argument_contracts import ArgumentBuilder


class BullAgent(ArgumentBuilder):
    """Constructs the evidence-backed bullish case."""

    stance = "bull"
