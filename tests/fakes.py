"""Mock language model: selects supplied cells, never reads gold annotations."""


class GroundedMockLLM:
    def __init__(self, transform=None, include_overview=False):
        self.calls = []
        self.transform = transform
        self.include_overview = include_overview

    def generate(self, schema, *, system, payload):
        self.calls.append({"schema": schema.__name__, "system": system, "payload": payload})
        if payload["task"] in ("document_extraction", "single_llm_baseline"):
            response = {"primitives": [], "facts": [], "missing": []}
            for chunk in payload["chunks"]:
                for cell in chunk["cells"]:
                    if cell["metric"] in payload["requested_metrics"]:
                        response["primitives"].append({"chunk_id": chunk["chunk_id"], "cell_id": cell["cell_id"],
                            "metric": cell["metric"], "value": cell["value"], "unit": cell["unit"],
                            "currency": cell["currency"], "scale": cell["scale"], "period_end": cell["period"]["end_date"]})
            if self.include_overview:
                import re
                for chunk in payload["chunks"]:
                    match = re.search(r"(?:Headquartered|Our headquarters)[^.]+\.", chunk["text"])
                    if match:
                        response["facts"].append({"chunk_id": chunk["chunk_id"], "quote": match[0]})
                        break
            if payload["task"] == "single_llm_baseline":
                from fractions import Fraction
                from decimal import Decimal,localcontext
                cells=[cell for c in payload["chunks"] for cell in c["cells"]]
                grouped={m:sorted([c for c in cells if c["metric"]==m],key=lambda c:c["period"]["end_date"],reverse=True)
                         for m in payload["requested_metrics"]}
                response["metrics"]=[]
                for op in payload["requested_operations"]:
                    roles={"revenue_growth":("revenue","revenue"),"operating_margin":("operating_income","revenue"),
                        "net_margin":("net_income","revenue"),"current_ratio":("current_assets","current_liabilities")}[op]
                    a=grouped[roles[0]][0];b=grouped[roles[1]][1 if op=="revenue_growth" else 0]
                    x,y=Fraction(a["value"]),Fraction(b["value"])
                    value=(x-y)/y*100 if op=="revenue_growth" else x/y*(1 if op=="current_ratio" else 100)
                    with localcontext() as ctx:
                        ctx.prec=60
                        output=str((Decimal(value.numerator)/Decimal(value.denominator)).quantize(Decimal("0.0001")))
                    response["metrics"].append({"operation":op,"value":output,"unit":"ratio" if op=="current_ratio" else "percent",
                        "period_end":a["period"]["end_date"],"input_cell_ids":[a["cell_id"],b["cell_id"]]})
                del response["missing"]
                response["sections"]=["Executive Summary","Company Overview","Financial Health","Sources","Support and Uncertainty","Limitations"]
                response["limitations"]=["Explicit arithmetic test double; not live LLM performance"]
        elif payload["task"] == "financial_plan":
            response = {"operations": payload["requested_operations"]}
        elif payload["task"] == "financial_interpretation":
            from decimal import Decimal
            artifact = payload["artifact"]
            value = Decimal(artifact["output_value"])
            if artifact["operation"] == "revenue_growth":
                label = "increase" if value > 0 else "decrease" if value < 0 else "unchanged"
            elif artifact["operation"] == "current_ratio":
                label = "assets_above_liabilities" if value > 1 else "assets_below_liabilities" if value < 1 else "assets_equal_liabilities"
            else:
                label = "profit" if value > 0 else "loss" if value < 0 else "break_even"
            response = {"calculation_ref": artifact["calculation_ref"], "label": label}
        else:
            raise AssertionError("Unknown mock model task")
        if self.transform:
            response = self.transform(response, payload)
        return schema.model_validate(response)


class ReplaySDKClient:
    """Offline SDK transport double; no real model inference or token usage."""

    def __init__(self, *, include_overview=True, transform=None):
        self.models = self
        self.mock = GroundedMockLLM(transform=transform, include_overview=include_overview)
        self.calls = []

    def generate_content(self, **arguments):
        import json
        from types import SimpleNamespace
        from agents.document_agent import DocumentExtraction
        from agents.financial_agent import FinancialInterpretation, FinancialPlan
        from evaluation.baseline import BaselineResponse
        payload = json.loads(arguments["contents"])
        schema = {"document_extraction": DocumentExtraction, "financial_plan": FinancialPlan,
                  "financial_interpretation": FinancialInterpretation,"single_llm_baseline":BaselineResponse}[payload["task"]]
        result = self.mock.generate(schema, system=arguments["config"].system_instruction, payload=payload)
        self.calls.append(arguments)
        return SimpleNamespace(text=result.model_dump_json(), candidates=[SimpleNamespace(finish_reason="STOP")],
            usage_metadata=None, model_version="offline-mock-no-live-model")
