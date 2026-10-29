"""Explicit offline Batch 2 double; never a live-generation fallback."""
from tests.fakes import GroundedMockLLM


class Batch2MockLLM(GroundedMockLLM):
    mode = "offline mock; no live model execution"
    execution_kind = "offline_mock"

    def generate(self,schema,*,system,payload):
        if payload["task"]=="single_llm_baseline" and "analysis" in schema.model_fields:
            result=super().generate(schema,system=system,payload=payload)
            data=result.model_dump(mode="json")
            chunks=payload["chunks"]
            financial=next((c["chunk_id"] for c in chunks if c["cells"]),None)
            macro=next((c["chunk_id"] for c in chunks if c["source"]["source_type"]=="news"),None)
            statements={"Market Analysis":"The dated macro snapshot does not establish current market conditions.",
                "Risk Assessment":"Historical financial and macro observations identify review topics; causal exposure remains unproven.",
                "Bull Case":"Positive historical profitability supports a qualified strength perspective.",
                "Bear Case":"Historical profitability does not establish durable future performance.",
                "Key Contradictions":"No independent mechanical contradiction check occurred in this single-call comparator."}
            data["analysis"]=[{"section":s,"proposition":t,"source_chunk_ids":[i for i in (macro if s=="Market Analysis" else financial,) if i],
                "qualifications":["Explicit offline template double, not live model evidence","Historical, unverified interpretation; no recommendation"]} for s,t in statements.items()]
            return schema.model_validate(data)
        if payload["task"]=="unified_analysis":
            self.calls.append({"schema":schema.__name__,"system":system,"payload":payload})
            primitives=[{"chunk_id":c["chunk_id"],"cell_id":cell["cell_id"],"metric":cell["metric"],"value":cell["value"],
                "unit":cell["unit"],"currency":cell["currency"],"scale":cell["scale"],"period_end":cell["period"]["end_date"]}
                for c in payload["chunks"] for cell in c["cells"] if cell["metric"] in payload["requested_metrics"]]
            response={"primitives":primitives if payload["source_selection"] else [],"operations":payload["requested_operations"]}
            if self.transform:
                response=self.transform(response,payload)
            return schema.model_validate(response)
        if payload["task"] in ("bull_case","bear_case"):
            self.calls.append({"schema":schema.__name__,"system":system,"payload":payload})
            stance=payload["task"].split("_")[0]
            premises=payload["snapshot"]["premises"]
            selected=next((p for p in premises if p["metric"] in ("net_margin","operating_margin","revenue_growth") and float(p["value"] or 0)>0),None)
            if selected is None and payload.get("experimental_condition")=="without_engine":
                selected=next((p for p in premises if p["metric"]=="operating_income" and float(p["value"] or 0)>0),None)
            arguments=[] if selected is None else [{"stance":stance,"interpretation":"strength" if stance=="bull" else "uncertainty",
                "premises":[selected],"counterevidence":[],"qualifications":["historical_only","not_causal","not_recommendation"],
                "snapshot_hash":payload["snapshot"]["fingerprint"]}]
            response={"arguments":arguments,"evidence_gaps":[]}
            if self.transform:
                response=self.transform(response,payload)
            return schema.model_validate(response)
        if payload["task"]=="critic_explanation":
            self.calls.append({"schema":schema.__name__,"system":system,"payload":payload})
            return schema.model_validate({"explanations":[{"finding_id":f["finding_id"],"significance":"dimension_consistency"} for f in payload["findings"]]})
        return super().generate(schema,system=system,payload=payload)
