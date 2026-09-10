"""Deterministic Financial Engine — executes exact calculations; validates inputs and outputs.

Sole path to any numeric result in the report. Rejects out-of-range inputs
(e.g. 340% single-period revenue growth) before computing and sanity-checks
outputs. Called only via structured requests from Financial Agent.
"""

from __future__ import annotations

from typing import Any


class FinancialEngine:
    """Exact financial computations with two-sided sanity checks."""

    def calculate(self, request: dict[str, Any]) -> dict[str, Any]:
        """Execute a validated calculation (ratios, CAGR, DCF, multiples).

        Args:
            request: Structured calc request from Financial Agent.

        Returns:
            Exact numeric result dict with calculation_ref, or rejection with reason.
        """
        raise NotImplementedError

    def validate_inputs(self, request: dict[str, Any]) -> bool:
        """Validate calc inputs for range sanity before computing.

        Args:
            request: Structured calc request.

        Returns:
            True if inputs are in sane range, False otherwise.
        """
        raise NotImplementedError

    def validate_outputs(self, result: dict[str, Any]) -> bool:
        """Validate computed outputs for range sanity before returning.

        Args:
            result: Raw numeric result.

        Returns:
            True if outputs are sane, False otherwise.
        """
        raise NotImplementedError
