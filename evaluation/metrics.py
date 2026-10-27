"""Fixture-based scoring. Gold and rational oracles are evaluation-only."""

from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction

from agents.report_agent import ReportAgent


OPERATIONS=("revenue_growth","operating_margin","net_margin","current_ratio")


def expectations(gold):
    raw={(v["metric"],v["period_end"]):Decimal(v["value"]) for v in gold["values"]}
    def latest(metric): return sorted(((end,value) for (name,end),value in raw.items() if name==metric),reverse=True)
    (_,rev),(_,prior)=latest("revenue")[:2]
    _,op=latest("operating_income")[0];_,net=latest("net_income")[0]
    _,assets=latest("current_assets")[0];_,liabilities=latest("current_liabilities")[0]
    rev,prior,op,net,assets,liabilities=map(Fraction,(rev,prior,op,net,assets,liabilities))
    rational={"revenue_growth":(rev-prior)/prior*100,"operating_margin":op/rev*100,"net_margin":net/rev*100,"current_ratio":assets/liabilities}
    with localcontext() as ctx:
        ctx.prec=80
        calculated={k:Decimal(v.numerator)/Decimal(v.denominator) for k,v in rational.items()}
    return raw,calculated


def numerically_equal(value, expected):
    try:
        value=Decimal(value)
        return value.is_finite() and (value-expected).copy_abs()<=Decimal("0.00005")
    except (InvalidOperation,TypeError,ValueError): return False


def _summary(observations, calculated, sections, failures=(), abstained=()):
    metrics={k:v for k,v in observations.items() if k in OPERATIONS}
    rows=[{"operation":op,"expected":str(expected),"observed":str(metrics[op][0]) if op in metrics else None,
           "correct":numerically_equal(metrics[op][0],expected) if op in metrics else False,
           "citation_correct":bool(metrics[op][1]) if op in metrics else False} for op,expected in calculated.items()]
    supplied=list(observations.values())
    cited=[v for v in supplied if v[2]]
    return {"numerical_correct":sum(r["correct"] for r in rows),"required_calculations":4,
        "numerical_accuracy":sum(r["correct"] for r in rows)/4,
        "citation_coverage":len(cited)/len(supplied) if supplied else 0,
        "citation_correctness":sum(bool(v[1]) for v in cited)/len(cited) if cited else 0,
        "unsupported_factual_claims":sum(not v[1] for v in supplied),
        "reported_claims":len(supplied),"section_completeness":len(set(sections))/6,
        "missing_calculations":[op for op in OPERATIONS if op not in metrics],
        "abstained_calculations":list(abstained),"pipeline_failures":list(failures),"per_calculation":rows}


def score_mafis(state, retriever, gold):
    raw,calculated=expectations(gold); observations={}; failures=[]
    try: ReportAgent(state["memory"],retriever).validate_report(state["report"])
    except ValueError as exc: failures.append(str(exc))
    entries=next(s.entries for s in state["analysis_map"].sections if s.title=="Sources")
    for entry in entries:
        claim=state["memory"].resolve(entry.claim_ref)
        if claim.claim_type=="raw_primitive":
            key=(claim.metric,str(claim.period.end_date))
            correct=raw.get(key)==claim.value and all(retriever.validate_evidence(e) for e in entry.evidence)
            observations[str(key)]=(claim.value,correct,bool(entry.evidence))
        elif claim.claim_type=="derived_metric":
            correct=numerically_equal(claim.value,calculated[claim.metric]) and bool(entry.calculation_ref) and not failures
            observations[claim.metric]=(claim.value,correct,bool(entry.evidence) and bool(entry.calculation_ref))
        else: observations[claim.claim_id]=(claim.claim,all(retriever.validate_evidence(e) for e in entry.evidence),bool(entry.evidence))
    if state["report"].status=="partial": failures.extend(i.code for i in state["analysis_map"].issues)
    summary=_summary(observations,calculated,[s.title for s in state["analysis_map"].sections],failures)
    summary["source_fact_completeness"]=sum(state["memory"].resolve(e.claim_ref).claim_type=="raw_primitive" for e in entries)/len(raw)
    return summary


def score_baseline(run, gold):
    raw,calculated=expectations(gold); observations={}; abstained=[]
    if run.response is None: return _summary({},calculated,(),run.issues)
    chunks={c.chunk_id:c for c in run.context}
    cells={cell.cell_id:cell for c in run.context for cell in c.cells}
    for index,p in enumerate(run.response.primitives):
        cell=cells.get(p.cell_id); chunk=chunks.get(p.chunk_id)
        correct=bool(cell and chunk and cell in chunk.cells and numerically_equal(p.value,raw.get((p.metric,str(p.period_end)),Decimal("NaN")))
            and (p.metric,p.currency,p.scale,p.unit,p.period_end)==(cell.metric,cell.currency,cell.scale,cell.unit,cell.period.end_date))
        observations["primitive:"+str(index)]=(p.value,correct,bool(p.cell_id and p.chunk_id))
    for m in run.response.metrics:
        if m.abstained or m.value is None: abstained.append(m.operation);continue
        expected_metrics={"revenue_growth":["revenue","revenue"],"operating_margin":["operating_income","revenue"],
            "net_margin":["net_income","revenue"],"current_ratio":["current_assets","current_liabilities"]}[m.operation]
        input_cells=[cells[c] for c in m.input_cell_ids if c in cells]
        required_dates=sorted(end for (name,end) in raw if name=="revenue") if m.operation=="revenue_growth" else [max(end for name,end in raw if name==expected_metrics[0])]*2
        correct=(len(input_cells)==len(set(m.input_cell_ids))==2 and sorted(c.metric for c in input_cells)==sorted(expected_metrics)
            and sorted(str(c.period.end_date) for c in input_cells)==sorted(required_dates)
            and str(m.period_end)==max(required_dates) and m.unit==("ratio" if m.operation=="current_ratio" else "percent")
            and numerically_equal(m.value,calculated[m.operation]))
        observations[m.operation]=(m.value,correct,bool(m.input_cell_ids))
    for index,fact in enumerate(run.response.facts):
        correct=fact.chunk_id in chunks and fact.quote in chunks[fact.chunk_id].text
        observations["fact:"+str(index)]=(fact.quote,correct,bool(fact.chunk_id))
    summary=_summary(observations,calculated,run.response.sections,run.issues,abstained)
    summary["source_fact_completeness"]=len({(p.metric,str(p.period_end)) for p in run.response.primitives}.intersection(raw))/len(raw)
    return summary


def usage(adapters, *, mocked, rates=None):
    records=[r for adapter in adapters for r in adapter.telemetry]
    def total(field):
        values=[getattr(r,field) for r in records]
        return sum(values) if values and all(v is not None for v in values) else None
    input_tokens,output_tokens,thinking=total("prompt_tokens"),total("output_tokens"),total("thinking_tokens")
    estimate=None
    if rates is not None and input_tokens is not None and output_tokens is not None:
        estimate=str((Decimal(input_tokens)*Decimal(rates["input_per_million"])+Decimal(output_tokens+(thinking or 0))*Decimal(rates["output_per_million"]))/Decimal(1000000))
    return {"llm_calls":len({r.request_id for r in records}),"transport_attempts":len(records),
        "input_tokens":input_tokens,"output_tokens":output_tokens,"thinking_tokens":thinking,
        "actual_api_cost_usd":"0" if mocked else None,"estimated_api_cost_usd":estimate,
        "cost_basis":"No API generation in mocked mode" if mocked else "Actual billing unavailable; estimate requires explicit pricing rates",
        "request_latency_ms":sum(r.latency_ms for r in records)}
