"""Bear Agent — builds negative case from verified claims only.

Constrained to cite only Shared Memory claim IDs with
verification_status == verified. Introduces no new evidence.
"""

from agents.argument_contracts import ArgumentBuilder


class BearAgent(ArgumentBuilder):
    """Constructs the evidence-backed bearish case."""

    stance = "bear"
