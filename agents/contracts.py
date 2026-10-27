"""Small typed agent outcomes; claims and calculations remain in Shared Memory."""

from memory.shared_memory import EvidenceModel


class AgentIssue(EvidenceModel):
    code: str
    message: str
