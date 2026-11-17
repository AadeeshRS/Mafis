"""Present the requested results from an already validated financial report."""

from html import escape
import re

from agents.planner import PlannerAgent


SECTION_QUESTIONS = (
    (r"\bmarket analysis\b", "Market Context"),
    (r"\brisk assessment\b", "Risk Assessment"),
    (r"\bbull (?:and bear |(?:case|view))", "Bull Case"),
    (r"\bbear (?:and bull |(?:case|view))", "Bear Case"),
)


def metric_name(metric):
    return metric.replace("_", " ").capitalize()


def answer_item(memory, claim, entry, label):
    if claim.calculation_ref:
        artifact = memory.get_calculation(claim.calculation_ref)
        suffix = "%" if artifact.output_unit == "percent" else "×"
        value = f"{artifact.display_value}{suffix}"
    elif claim.claim_type == "raw_primitive":
        scale = {1: "", 1000: " thousand", 1000000: " million", 1000000000: " billion"}
        value = f"{claim.currency} {claim.value:,f}{scale.get(claim.scale, f' × {claim.scale:,}')}"
    else:
        value = claim.claim
    period = None
    if claim.period is not None:
        prefix = "As of" if claim.period.kind == "instant" else "Fiscal year ended"
        period = f"{prefix} {claim.period.end_date.isoformat()}"
    evidence = claim.evidence if claim.claim_type == "qualitative" else entry.evidence
    sources = list(dict.fromkeys(f"{e.source}, PDF page {e.page}" if e.page else e.source for e in evidence))
    return {"label": label, "value": value, "period": period, "entity": claim.entity,
            "verification": entry.verification_status, "sources": sources}


def build_question_answer(state):
    plan = state["plan"]
    result = {"question": state["question"], "status": "answered", "message": "", "items": []}
    if plan.status != "ready":
        status = "unsupported" if plan.status == "unsupported" else "unavailable"
        return dict(result, status=status, message=plan.issues[0].message)

    memory = state["memory"]
    sections = {section.title: section.entries for section in state["report"].analysis_map.sections}
    if plan.document_lookup:
        items = [answer_item(memory, memory.resolve(entry.claim_ref), entry, "Document evidence")
                 for entry in sections["Company Overview"]]
        issues = state["report"].analysis_map.issues
        if items:
            if issues:
                return dict(result, status="partial", message=issues[0].message, items=items)
            return dict(result, items=items)
        return dict(result, status="unavailable", message=issues[0].message if issues else
                    "The retrieved passages do not establish an answer to this question.")
    financial = [(memory.resolve(entry.claim_ref), entry) for entry in sections["Financial Health"]]
    topics = [title for pattern, title in SECTION_QUESTIONS if re.search(pattern, state["question"], re.I)]
    # Risk and stance routing can add financial work as supporting evidence.
    answer_plan = PlannerAgent().build_graph(state["question"], True) if topics else plan
    missing = []
    for metric in dict.fromkeys(answer_plan.operations + answer_plan.requested_facts):
        matches = [(claim, entry) for claim, entry in financial if claim.metric == metric and claim.period
                   and (plan.target_year is None or claim.period.end_date.year == plan.target_year)]
        label = metric_name(metric)
        if matches:
            latest = max(claim.period.end_date for claim, _ in matches)
            current = [(claim, entry) for claim, entry in matches if claim.period.end_date == latest]
            if len(current) == 1:
                result["items"].append(answer_item(memory, *current[0], label))
                continue
        missing.append(label)

    if answer_plan.overview:
        topics.append("Company Overview")
    for title in topics:
        entries = sections.get(title, ())
        for entry in entries:
            result["items"].append(answer_item(memory, memory.resolve(entry.claim_ref), entry, title))
        if not entries:
            missing.append(title)

    if not result["items"]:
        result["status"] = "unavailable"
        result["message"] = "The report contains no source-backed answer for the requested evidence or fiscal period."
    elif missing:
        result["status"] = "partial"
        result["message"] = "Unavailable from the checked evidence: " + ", ".join(missing) + "."
    return result


def render_question_answer(answer):
    lines = ["## Answer to your question", ""]
    lines.extend(f"> {escape(line)}" for line in answer["question"].splitlines())
    lines.append("")
    if answer["message"]:
        lines.extend((escape(answer["message"]), ""))
    for item in answer["items"]:
        context = " · ".join(value for value in (item["entity"], item["period"]) if value)
        lines.append(f"- **{escape(item['label'])}** — {escape(item['value'])}")
        if context:
            lines.append(f"  {escape(context)}.")
        if item["sources"]:
            lines.append(f"  Evidence: {escape(', '.join(item['sources']))}. Verification {item['verification']}.")
    return "\n".join(lines) + "\n\n"
