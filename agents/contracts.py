"""Small typed agent outcomes; claims and calculations remain in Shared Memory."""

import re

from memory.shared_memory import EvidenceModel


MARKET_SHARE = re.compile(r"\bmarket[ -]+share\b", re.I)


class AgentIssue(EvidenceModel):
    code: str
    message: str
