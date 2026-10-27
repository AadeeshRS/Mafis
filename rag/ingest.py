"""First deterministic, born-digital PDF slice. No agent, OCR, or indexing.

The supported profile uses single-page consolidated income/balance tables,
English full-date column headers, and explicit thousands/millions/billions.
Retrieved text is data: no source text is executed or used as instructions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
from typing import Any

import pdfplumber
from pdfplumber.utils.exceptions import PdfminerException
from pdfminer.pdfparser import PDFSyntaxError
from pdfminer.psparser import PSEOF

from memory.shared_memory import Claim, Evidence, FiscalPeriod, SourceDocument


@dataclass(frozen=True)
class TextLine:
    text: str
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class StatementPage:
    page: int  # one-based PDF page
    height: float
    lines: tuple[TextLine, ...]

    @property
    def printed_page(self) -> str | None:
        labels = [line.text if line.text.isdigit() else line.text.rsplit("|", 1)[-1].strip()
                  for line in self.lines if line.bbox[1] > self.height * 0.9
                  and (line.text.isdigit() or re.search(r"\|\s*\d+\s*$", line.text))]
        return labels[0] if len(labels) == 1 else None


@dataclass(frozen=True)
class ExtractionFailure:
    code: str
    message: str
    page: int | None = None
    metric: str | None = None


@dataclass(frozen=True)
class ExtractionResult:
    source: SourceDocument | None
    claims: tuple[Claim, ...] = ()
    failures: tuple[ExtractionFailure, ...] = ()

    @property
    def ok(self) -> bool:
        return bool(self.claims) and not self.failures


# Row labels and counts are a format profile, never expected financial values.
_STATEMENTS = {
    "Consolidated Statements of Income": (
        ("revenue", "Revenue", 2),
        ("operating_income", "Operating income", 1),
        ("net_income", "Net income", 1),
    ),
    "Consolidated Balance Sheets": (
        ("current_assets", "Total current assets", 1),
        ("current_liabilities", "Total current liabilities", 1),
    ),
}
_DATE = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(\d{1,2}),\s+(\d{4})\b"
)
_MONTHS = {name: i for i, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
)}
_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_CURRENCY_QUOTE = "We use the U.S. dollar as our functional currency for our subsidiaries."
_FISCAL_WEEKS = re.compile(r"Fiscal years (\d{4}), (\d{4}) and (\d{4}) were all (52|53)-\s*week years\.")
_PRESENTATION_CURRENCY = re.compile(r"(?:financial statements are presented in U\.S\. dollars|net sales and gross margins as expressed in U\.S\. dollars)", re.I)


def normalize_number(raw: str) -> Decimal:
    """Parse accounting signs without guessing missing values or bad grouping."""
    text = raw.strip().replace("\u2212", "-")
    if text.startswith("$"):
        text = text[1:].strip()
    if re.fullmatch(rf"\({_NUMBER}\)", text):
        return -Decimal(text[1:-1].replace(",", ""))
    if re.fullmatch(rf"[+-]?{_NUMBER}", text):
        return Decimal(text.replace(",", ""))
    raise ValueError(f"Missing or ambiguous financial number: {raw!r}")


def _evidence(source: SourceDocument, page: StatementPage, line: TextLine,
              section: str, locator: str, **fields: Any) -> Evidence:
    return Evidence(
        source=source.title, source_id=source.source_id, source_url=source.source_url,
        source_type=source.source_type, page=page.page, printed_page=page.printed_page,
        section=section, locator=locator, quote=line.text, bbox=line.bbox, **fields,
    )


def extract_statement(page: StatementPage, title: str, source: SourceDocument
                      ) -> tuple[list[Claim], list[ExtractionFailure]]:
    """Parse one supported statement's source lines; also used for failure tests.

    This consumes source text/geometry only. It has no access to test labels.
    On an ambiguous row, no value from that row is returned.
    """
    failures: list[ExtractionFailure] = []
    claims: list[Claim] = []

    def fail(code: str, message: str, metric: str | None = None) -> None:
        failures.append(ExtractionFailure(code, message, page.page, metric))

    if title not in _STATEMENTS:
        fail("unsupported_statement", title)
        return claims, failures
    if sum(line.text == title for line in page.lines) != 1:
        fail("ambiguous_statement", "Expected exactly one exact statement heading")
        return claims, failures
    if page.printed_page is None:
        fail("missing_page_label", "Cannot identify a unique printed footer page")
        return claims, failures
    if source.currency != "USD" or source.currency_evidence is None:
        fail("missing_currency", "An explicit supported USD context is required; '$' alone is insufficient")
        return claims, failures

    scale_lines = [(line, re.fullmatch(
        r"\(In (thousands|millions|billions)(?:, except [^)]+)?\)", line.text
    )) for line in page.lines]
    scales = [(line, match) for line, match in scale_lines if match]
    if len(scales) != 1:
        fail("ambiguous_scale", "Expected one explicit table scale header")
        return claims, failures
    scale_line, scale_match = scales[0]
    scale = {"thousands": 1_000, "millions": 1_000_000, "billions": 1_000_000_000}[scale_match[1]]

    # A header line must contain only full dates, not prose mentioning dates.
    headers = [(line, list(_DATE.finditer(line.text))) for line in page.lines
               if line.bbox[1] > scale_line.bbox[1]]
    headers = [(line, dates) for line, dates in headers
               if len(dates) >= 2 and not _DATE.sub("", line.text).strip()]
    if len(headers) != 1:
        fail("ambiguous_period", "Expected one full-date column header")
        return claims, failures
    header, matches = headers[0]
    try:
        periods = [date(int(m[3]), _MONTHS[m[1][:3]], int(m[2])) for m in matches]
    except ValueError as exc:
        fail("invalid_period", str(exc))
        return claims, failures
    if len(set(periods)) != len(periods) or periods != sorted(periods, reverse=True):
        fail("ambiguous_period", "Periods must be unique and newest first")
        return claims, failures
    is_income = title == "Consolidated Statements of Income"
    if is_income and sum(line.text == "Year Ended" for line in page.lines
                         if scale_line.bbox[1] < line.bbox[1] < header.bbox[1]) != 1:
        fail("missing_period_kind", "Income columns must explicitly be 'Year Ended'")
        return claims, failures

    for metric, label, count in _STATEMENTS[title]:
        # Anchored exact labels avoid 'Net income per share' and component rows.
        row_pattern = re.compile(re.escape(label) + r"\s+(?=\$|\(?[+\-\u2212]?\d|[\u2014\u2013\ufffd])")
        rows = [line for line in page.lines if row_pattern.match(line.text)
                and line.bbox[1] > header.bbox[1]]
        if not rows:
            fail("missing_row", f"No row for {label}", metric)
            continue
        if len(rows) != 1:
            fail("ambiguous_row", f"Multiple rows for {label}", metric)
            continue
        row = rows[0]
        raw_values = row.text[len(label):].replace("$", "").split()
        if len(raw_values) != len(periods):
            fail("column_mismatch", "Value count differs from date-column count", metric)
            continue
        try:
            values = [normalize_number(raw) for raw in raw_values]
        except ValueError as exc:
            fail("invalid_value", str(exc), metric)
            continue
        for column in range(count):
            end = periods[column]
            column_label = matches[column][0]
            period = FiscalPeriod(
                kind="duration" if is_income else "instant", end_date=end,
                label=("Year ended " if is_income else "As of ") + column_label,
            )
            evidence = _evidence(
                source, page, row, title,
                f"pdf-page={page.page};table={title};row={label};column={column_label}",
                year=end.year, row_label=label, column_header=column_label,
                raw_value=raw_values[column], scale_header=scale_line.text,
                period_header=header.text,
            )
            claims.append(Claim(
                claim_id=f"{source.source_id}:{metric}:{end.isoformat()}",
                agent="DocumentAgent", claim_type="raw_primitive", entity=source.entity,
                accounting_scope="consolidated",  # established by the exact table heading
                metric=metric, value=values[column], unit="currency", currency=source.currency,
                scale=scale, period=period, claim=f"{label}: {raw_values[column]} USD ({scale_line.text}), {period.label}",
                evidence=(evidence,), support_level="single_source", verification_status="pending",
            ))
    return claims, failures


def extract_financial_facts(path: str | Path, *, source_url: str,
                            title: str, entity: str) -> ExtractionResult:
    """Extract the six pilot facts from the PDF, without fixture/gold inputs.

    Document bytes are hashed and parsed from the same snapshot. No downloading,
    embeddings, database writes, model calls, or shared-store mutations occur.
    Layout/metadata failures return explicit diagnostics and any unaffected rows.
    """
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        return ExtractionResult(None, failures=(ExtractionFailure("unreadable_document", str(exc)),))
    source = SourceDocument(title=title, entity=entity, source_url=source_url,
                            sha256=sha256(data).hexdigest())
    if not data.startswith(b"%PDF-"):
        return ExtractionResult(source, failures=(ExtractionFailure("invalid_document", "Not a PDF"),))
    statements: dict[str, list[StatementPage]] = {title: [] for title in _STATEMENTS}
    currency_locations: list[Evidence] = []
    calendars: list[tuple[tuple[tuple[int, int], ...], Evidence]] = []
    alternate = {"income": [], "balance": []}
    presentation_currency = []
    try:
        with pdfplumber.open(BytesIO(data)) as pdf:
            for number, page in enumerate(pdf.pages, 1):
                lines = tuple(TextLine(line["text"], (line["x0"], line["top"], line["x1"], line["bottom"]))
                              for line in page.extract_text_lines())
                parsed = StatementPage(number, page.height, lines)
                for statement in statements:
                    if any(line.text == statement for line in lines):
                        statements[statement].append(parsed)
                for kind, pattern in (("income", r"consolidated statements of (income|operations)"),
                                      ("balance", r"consolidated balance sheets")):
                    if any(re.fullmatch(pattern, line.text, re.I) and line.text not in statements for line in lines):
                        alternate[kind].append(parsed)
                for index, line in enumerate(lines):
                    if _CURRENCY_QUOTE in line.text:
                        currency_locations.append(_evidence(
                            source, parsed, line, "Foreign Currency Remeasurement",
                            f"pdf-page={number};section=Foreign Currency Remeasurement",
                        ))
                    # The pilot's explicit fiscal-year policy spans two source lines.
                    text = " ".join(item.text for item in lines[index:index + 2])
                    window3 = lines[index:index + 3]
                    currency_text = " ".join(item.text for item in window3)
                    currency_match = _PRESENTATION_CURRENCY.search(currency_text)
                    if currency_match:
                        box = (min(x.bbox[0] for x in window3), line.bbox[1], max(x.bbox[2] for x in window3), window3[-1].bbox[3])
                        presentation_currency.append(_evidence(source, parsed, TextLine(currency_match[0], box),
                            "Reporting currency", f"pdf-page={number};section=Reporting currency"))
                    match = _FISCAL_WEEKS.search(text) if "Fiscal years " in line.text else None
                    if match:
                        window = lines[index:index + 2]
                        bbox = (min(item.bbox[0] for item in window), line.bbox[1],
                                max(item.bbox[2] for item in window), window[-1].bbox[3])
                        calendars.append((tuple((int(match[n]), int(match[4])) for n in (1, 2, 3)),
                            _evidence(source, parsed, TextLine(text, bbox), "Fiscal Year",
                                      f"pdf-page={number};section=Fiscal Year")))
                page.close()
    except (PdfminerException, PDFSyntaxError, PSEOF, ValueError, OSError) as exc:
        return ExtractionResult(source, failures=(ExtractionFailure("invalid_document", str(exc)),))
    if len(currency_locations) == 1:
        source = SourceDocument(**source.model_dump(exclude={"currency", "currency_evidence"}),
                                currency="USD", currency_evidence=currency_locations[0])
    elif presentation_currency:
        # All accepted phrases explicitly establish USD presentation, not '$'.
        source = SourceDocument(**source.model_dump(exclude={"currency", "currency_evidence"}),
                                currency="USD", currency_evidence=presentation_currency[0])
    if len(calendars) == 1:
        source = SourceDocument(**source.model_dump(exclude={"fiscal_year_weeks", "fiscal_calendar_evidence"}),
                                fiscal_year_weeks=calendars[0][0], fiscal_calendar_evidence=calendars[0][1])
    claims: list[Claim] = []
    failures: list[ExtractionFailure] = []
    for statement, pages in statements.items():
        kind = "income" if statement == "Consolidated Statements of Income" else "balance"
        alternatives = alternate[kind]
        if not pages and len(alternatives) == 1:
            found, errors, anchors = extract_alternate_statement(alternatives[0], kind, source)
            claims.extend(found)
            failures.extend(errors)
            if anchors is not None:
                dates, evidence = anchors
                source = source.model_copy(update={"annual_period_ends": tuple(dates), "annual_period_evidence": evidence})
            continue
        if len(pages) != 1:
            code = "missing_statement" if not pages else "ambiguous_statement"
            failures.append(ExtractionFailure(code, f"Expected one {statement}, found {len(pages)}"))
            continue
        found, errors = extract_statement(pages[0], statement, source)
        claims.extend(found)
        failures.extend(errors)
    return ExtractionResult(source, tuple(claims), tuple(failures))


def extract_alternate_statement(page: StatementPage, kind: str, source: SourceDocument):
    try:
        return _parse_alternate_statement(page,kind,source)
    except (ValueError,KeyError,IndexError):
        return [],[ExtractionFailure("invalid_table_context","Malformed comparative header or unsupported calendar",page.page)],None


def _parse_alternate_statement(page: StatementPage, kind: str, source: SourceDocument):
    """Observed reusable layouts: split month/day/year and shared-date headers.

    Exact consolidated headings and anchored total-row aliases prevent selecting
    segment tables, component sales, or parent-only net income as consolidated.
    """
    failures, claims = [], []
    def failure(code, message, metric=None):
        failures.append(ExtractionFailure(code, message, page.page, metric))
    if kind not in ("income", "balance"):
        failure("unsupported_statement", "Unsupported statement kind")
        return claims, failures, None
    headings = [x.text for x in page.lines if re.fullmatch(
        r"consolidated statements of (income|operations)" if kind == "income" else r"consolidated balance sheets", x.text, re.I)]
    if len(headings) != 1:
        failure("ambiguous_statement", "Require exactly one consolidated statement heading")
        return claims, failures, None
    heading = headings[0]
    scales = [(line, re.match(r"\(In (thousands|millions|billions)\b", line.text, re.I)) for line in page.lines]
    scales = [(line, m) for line, m in scales if m]
    if len(scales) != 1 or page.printed_page is None or source.currency != "USD":
        failure("missing_table_context", "Require a unique scale, printed page, and explicit USD presentation")
        return claims, failures, None
    scale_line, scale_match = scales[0]
    scale = {"thousands": 1000, "millions": 1000000, "billions": 1000000000}[scale_match[1].lower()]
    headers = []
    for index, line in enumerate(page.lines):
        if line.bbox[1] <= scale_line.bbox[1]:
            continue
        full = list(_DATE.finditer(line.text))
        if full and re.fullmatch(r"(?:Year[s]? [Ee]nded )?" + re.escape(full[0][0]) + r"(?:\s+\d{4})*", line.text):
            m = full[0]
            years = [int(v) for v in re.findall(r"\b\d{4}\b", line.text)]
            dates = [date(y, _MONTHS[m[1][:3]], int(m[2])) for y in years]
            if len(dates) >= 2:
                headers.append((line, dates))
        parts = list(re.finditer(r"([A-Z][a-z]+)\s+(\d{1,2}),", line.text))
        if len(parts) >= 2 and index + 1 < len(page.lines) and not full:
            following = page.lines[index + 1]
            if re.fullmatch(r"\d{4}(?:\s+\d{4})+", following.text):
                years = [int(y) for y in following.text.split()]
                if len(years) == len(parts):
                    dates = [date(y, _MONTHS[m[1][:3]], int(m[2])) for m, y in zip(parts, years)]
                    box = (min(line.bbox[0], following.bbox[0]), line.bbox[1], max(line.bbox[2], following.bbox[2]), following.bbox[3])
                    headers.append((TextLine(line.text + "\n" + following.text, box), dates))
    if len(headers) != 1:
        failure("ambiguous_period", "Expected one complete, supported comparative date header")
        return claims, failures, None
    header, dates = headers[0]
    if len(set(dates)) != len(dates) or dates != sorted(dates, reverse=True):
        failure("ambiguous_period", "Comparative dates must be unique, newest first")
        return claims, failures, None
    if kind == "income" and not any(re.search(r"\byears? ended\b", x.text, re.I) for x in page.lines):
        failure("missing_period_kind", "Annual income durations must be explicit")
        return claims, failures, None
    specs = (("revenue", ("Total net sales", "Net Operating Revenues", "Revenue"), 2),
             ("operating_income", ("Operating income",), 1),
             ("net_income", ("Consolidated Net Income", "Net income"), 1)) if kind == "income" else (
             ("current_assets", ("Total current assets",), 1), ("current_liabilities", ("Total current liabilities",), 1))
    for metric, aliases, count in specs:
        rows = [(line, label) for line in page.lines for label in aliases
                if re.match(re.escape(label) + r"\s+(?=\$|\(?[+\-\u2212\d]|[\u2014\u2013])", line.text, re.I) and line.bbox[1] > header.bbox[1]]
        if len(rows) != 1:
            failure("missing_row" if not rows else "ambiguous_row", "Require exactly one consolidated total row", metric)
            continue
        row, label = rows[0]
        values = row.text[len(label):].replace("$", "").split()
        try:
            if len(values) != len(dates):
                raise ValueError("Column/value count mismatch")
            numbers = [normalize_number(v) for v in values]
        except ValueError as exc:
            failure("invalid_value", str(exc), metric)
            continue
        for column in range(count):
            end = dates[column]
            column_label = end.strftime("%B %d, %Y").replace(" 0", " ")
            period = FiscalPeriod(kind="duration" if kind == "income" else "instant", end_date=end,
                label=("Year ended " if kind == "income" else "As of ") + column_label)
            evidence = _evidence(source, page, row, heading,
                f"pdf-page={page.page};table={heading};row={row.text[:len(label)]};column={column_label}",
                row_label=row.text[:len(label)], column_header=column_label, raw_value=values[column], year=end.year,
                scale_header=scale_line.text, period_header=header.text)
            claims.append(Claim(claim_id=f"{source.source_id}:{metric}:{end.isoformat()}", agent="DocumentAgent",
                claim_type="raw_primitive", entity=source.entity, accounting_scope="consolidated", metric=metric,
                value=numbers[column], unit="currency", currency="USD", scale=scale, period=period,
                claim=f"{evidence.row_label}: {values[column]} USD; {period.label}", evidence=(evidence,),
                support_level="single_source", verification_status="pending"))
    anchors = (dates, _evidence(source, page, header, heading, f"pdf-page={page.page};table={heading};annual-period-header")) if kind == "income" else None
    return claims, failures, anchors


def prepare_document(path: str | Path, *, source_url: str, title: str, entity: str):
    """Build stable, page-bounded source chunks; never read answer annotations.

    Existing deterministic parsing supplies grounded financial cells. Remaining
    content remains searchable as narrative, including unsupported table layouts.
    A supported financial row carries repeated table/date/scale headers.
    """
    from rag.models import IndexedDocument, SourceChunk, TableCell

    data = Path(path).read_bytes()
    extraction = extract_financial_facts(path, source_url=source_url, title=title, entity=entity)
    if extraction.source is None or not data.startswith(b"%PDF-"):
        raise ValueError("An accessible born-digital PDF is required")
    source = extraction.source
    if sha256(data).hexdigest() != source.sha256:
        raise ValueError("Document changed while preparing source chunks")
    chunks = []

    def add(parsed, text, kind, bbox, locator, cells=(), section_label=None):
        identity = f"v2|{source.source_id}|{parsed.page}|{kind}|{locator}|{text}"
        chunk_id = "chunk:" + sha256(identity.encode()).hexdigest()
        # Decorative/cropped PDF content can have negative coordinates. Retain
        # its page/text locator without inventing a valid on-page bounding box.
        valid_bbox = bbox if 0 <= bbox[0] < bbox[2] and 0 <= bbox[1] < bbox[3] else None
        evidence = Evidence(source=source.title, source_id=source.source_id,
            source_url=source.source_url, source_type=source.source_type,
            page=parsed.page, printed_page=parsed.printed_page,
            section=section_label or text.splitlines()[0][:160], quote=text, bbox=valid_bbox,
            locator=f"pdf-page={parsed.page};chunk={chunk_id};offset={locator}")
        chunks.append(SourceChunk(chunk_id=chunk_id, source=source, kind=kind,
                                  text=text, evidence=evidence, cells=cells))

    with pdfplumber.open(BytesIO(data)) as pdf:
        count = len(pdf.pages)
        for number, page in enumerate(pdf.pages, 1):
            lines = tuple(TextLine(item["text"], (item["x0"], item["top"], item["x1"], item["bottom"]))
                          for item in page.extract_text_lines())
            parsed = StatementPage(number, page.height, lines)
            text = "\n".join(line.text for line in lines)
            if text.strip():
                offset = 0
                for part in chunk_text(text, chunk_size=900, overlap=150):
                    start = text.find(part, offset)
                    offset = start + max(1, len(part) - 150)
                    bbox = (min(x.bbox[0] for x in lines), min(x.bbox[1] for x in lines),
                            max(x.bbox[2] for x in lines), max(x.bbox[3] for x in lines))
                    add(parsed, part, "narrative", bbox, str(start))
                # Short source headings otherwise get buried in page-wide
                # windows. Index their following paragraph with title metadata,
                # independent of company, topic, query, or relevance labels.
                headings = [i for i, line in enumerate(lines) if 3 <= len(line.text) <= 65
                    and re.fullmatch(r"[A-Z][A-Za-z-]*(?: (?:[A-Z][A-Za-z-]*|and|of|the|to|for|or|&)){0,9}", line.text)]
                for h, start_line in enumerate(headings):
                    stop = headings[h + 1] if h + 1 < len(headings) else len(lines)
                    section_lines = lines[start_line:stop]
                    if len(section_lines) < 2:
                        continue
                    section_text = "\n".join(x.text for x in section_lines)
                    box = (min(x.bbox[0] for x in section_lines), section_lines[0].bbox[1],
                           max(x.bbox[2] for x in section_lines), section_lines[-1].bbox[3])
                    for ordinal, part in enumerate(chunk_text(section_text, chunk_size=800, overlap=100)):
                        # Source text remains a contiguous excerpt. The heading
                        # is metadata on continuation chunks, never an invented
                        # prefix inside a purported verbatim quotation.
                        add(parsed, part, "narrative", box, f"section:{start_line}:{ordinal}",
                            section_label=section_lines[0].text)
            rows = {}
            for claim in extraction.claims:
                ev = claim.evidence[0]
                if ev.page == number:
                    rows.setdefault((ev.section, ev.row_label), []).append(claim)
            for (section, row), claims in rows.items():
                ev = claims[0].evidence[0]
                cells = tuple(TableCell(cell_id=c.claim_id, metric=c.metric, value=c.value,
                    unit=c.unit, currency=c.currency, scale=c.scale, period=c.period,
                    accounting_scope=c.accounting_scope, evidence=c.evidence[0]) for c in claims)
                text = "\n".join((section, ev.scale_header, ev.period_header, ev.quote))
                add(parsed, text, "table", ev.bbox, f"{section}|{row}", cells)
            page.close()
    if not chunks:
        raise ValueError("PDF contains no extractable text; OCR is not implemented")
    return IndexedDocument(source=source, chunks=tuple(chunks), page_count=count,
        limitations=tuple(f"{f.code}: {f.message}" for f in extraction.failures))


def ingest_document(path: str | Path, *, source_url: str, title: str, entity: str, retriever=None):
    """Prepare and idempotently index source content in the shared Chroma store."""
    from rag.retriever import get_shared_retriever

    document = prepare_document(path, source_url=source_url, title=title, entity=entity)
    index = retriever if retriever is not None else get_shared_retriever()
    index.index(document)
    return document


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 100) -> list[str]:
    """Split text into overlapping chunks.

    Args:
        text: Raw document text.
        chunk_size: Max chunk length.
        overlap: Overlap between chunks.

    Returns:
        List of text chunks.
    """
    if chunk_size <= 0 or not 0 <= overlap < chunk_size:
        raise ValueError("Require chunk_size > overlap >= 0")
    parts = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            boundary = text.rfind("\n", start + chunk_size // 2, end)
            if boundary > start:
                end = boundary
        part = text[start:end]
        if part.strip():
            parts.append(part)
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
    return parts
