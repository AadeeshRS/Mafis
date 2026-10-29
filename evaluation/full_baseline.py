"""Single-call comparator can express the same analytical scope as full MAFIS.

All narrative remains explicitly unverified. Citation presence is not treated as
semantic support, and no engine/Verifier/Critic is called by this renderer.
"""
from typing import Literal
from pydantic import Field
from evaluation.baseline import BaselineResponse,render_baseline
from memory.shared_memory import EvidenceModel

FULL_SCOPE=("Executive Summary","Company Overview","Financial Health","Market Analysis","Risk Assessment",
    "Bull Case","Bear Case","Key Contradictions","Sources","Support and Uncertainty","Limitations")


class UnverifiedAnalysis(EvidenceModel):
    section: Literal["Market Analysis","Risk Assessment","Bull Case","Bear Case","Key Contradictions"]
    proposition: str=Field(min_length=1)
    source_chunk_ids: tuple[str,...]=()
    qualifications: tuple[str,...]=()


class FullBaselineResponse(BaselineResponse):
    analysis: tuple[UnverifiedAnalysis,...]=()


def render_full_baseline(run,response):
    from html import escape
    text=render_baseline(run)
    for section in FULL_SCOPE:
        entries=[a for a in response.analysis if a.section==section]
        if entries:
            text+="\n## "+section+"\n\nUnverified single-call model interpretation.\n\n"
            for a in entries:
                text+="- "+escape(a.proposition)+"\n"
                text+="  Source references (support not independently established): "+escape(", ".join(a.source_chunk_ids) or "none")+"\n"
                text+="  Qualifications: "+escape("; ".join(a.qualifications) or "none supplied")+"\n"
    return text
