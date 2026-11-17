"""Build the editable, 16-slide MAFIS course deck and its matching blueprint."""
from argparse import ArgumentParser
from pathlib import Path
import re

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_TICK_MARK
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.opc.package import XmlPart
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt

from evidence import ASSETS, HERE, closeout, filing_results, read_json

W, H = 13 + 1/3, 7.5
M = .64
FONT = "Poppins"
BG, WHITE, INK, MUTED = "F3EBDD", "FFF9EE", "013230", "465C54"
DARK, LIGHT, RULE = "013230", "EADCC6", "D5C7B4"
PINE, RUST = "19574D", "823711"
PINE_LIGHT, RUST_LIGHT = "DEE7D9", "F8DDC9"
ORANGE, APRICOT = "FF6A1F", "FFD1AC"
THEME_COLORS = {
    "dk1": DARK, "lt1": BG, "dk2": PINE, "lt2": WHITE,
    "accent1": ORANGE, "accent2": DARK, "accent3": RUST,
    "accent4": APRICOT, "accent5": MUTED, "accent6": RULE,
    "hlink": PINE, "folHlink": RUST,
}
BANNED = ("delve,tapestry,testament,underscores,pivotal,crucial,landscape,realm,foster,beacon,"
          "intricate,meticulous,leverage,utilize,harness,elevate,streamline,embark,myriad,plethora,"
          "game-changer,cutting-edge,state-of-the-art,revolutionize,seamless,robust,in conclusion,"
          "furthermore,moreover").split(",")


def rgb(color):
    return RGBColor.from_string(color)


def pt(value):
    return Inches(value)


def text_style(p, size, color, bold=False, align=PP_ALIGN.LEFT):
    p.font.name = FONT
    p.font.size = Pt(size)
    p.font.bold = bold
    p.font.color.rgb = rgb(color)
    p.alignment = align
    p.space_before, p.space_after, p.line_spacing = Pt(0), Pt(0), 1.07


class Deck:
    def __init__(self, assets):
        self.p = Presentation()
        self.p.slide_width, self.p.slide_height = pt(W), pt(H)
        props = self.p.core_properties
        props.title = "MAFIS | Multi-Agent Financial Intelligence System"
        props.subject = "Artificial Intelligence course project"
        props.keywords = "financial filings; evidence verification; retrieval; LangGraph"
        self.assets, self.records = assets, []

    def box(self, x, y, w, h, fill, line=None, shape=MSO_SHAPE.RECTANGLE):
        s = self.s.shapes.add_shape(shape, pt(x), pt(y), pt(w), pt(h))
        style = s._element.find("{http://schemas.openxmlformats.org/presentationml/2006/main}style")
        if style is not None:
            s._element.remove(style)
        if fill:
            s.fill.solid()
            s.fill.fore_color.rgb = rgb(fill)
        else:
            s.fill.background()
        if line:
            s.line.color.rgb = rgb(line)
            s.line.width = Pt(1)
        else:
            s.line.fill.background()
        return s

    def line(self, x1, y1, x2, y2, color=RULE, *, width=1, arrow=False):
        s = self.s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, pt(x1), pt(y1), pt(x2), pt(y2))
        style = s._element.find("{http://schemas.openxmlformats.org/presentationml/2006/main}style")
        if style is not None:
            s._element.remove(style)
        s.line.color.rgb, s.line.width = rgb(color), Pt(width)
        if arrow:
            end = OxmlElement("a:tailEnd")
            end.set("type", "triangle")
            s.line._get_or_add_ln().append(end)
        return s

    def register(self, text):
        if text:
            self.records[-1]["text"].append(text)

    def tx(self, content, x, y, w, h=.42, size=20, color=INK, *, bold=False,
           align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE, record=True, wrap=False):
        s = self.s.shapes.add_textbox(pt(x), pt(y), pt(w), pt(h))
        self.fill_text(s.text_frame, content, size, color, bold, align, anchor, wrap)
        if record:
            self.register(content)
        return s

    @staticmethod
    def fill_text(tf, text, size, color, bold=False, align=PP_ALIGN.LEFT,
                  anchor=MSO_ANCHOR.MIDDLE, wrap=False):
        tf.clear()
        tf.word_wrap, tf.vertical_anchor = wrap, anchor
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        for index, line in enumerate(text.split("\n")):
            p = tf.paragraphs[0] if index == 0 else tf.add_paragraph()
            p.text = line
            text_style(p, size, color, bold, align)

    def slide(self, title, layout, placement, notes, sources=(), *, dark=False, cover=False, section=None):
        self.s = self.p.slides.add_slide(self.p.slide_layouts[6])
        self.records.append(dict(title=title, layout=layout, placement=placement,
                                 notes=notes, sources=sources, text=[], image_text=[]))
        bg = self.s.background.fill
        bg.solid()
        bg.fore_color.rgb = rgb(DARK if dark else BG)
        number = len(self.records)
        if section:
            self.tx(section.upper(), M, .28, 11.9, .33, 11, APRICOT if dark else RUST, bold=True)
        if not cover:
            self.tx(title, M, .67, 12, .77, 29, WHITE if dark else INK, bold=True)
        self.line(M, 7.03, W-M, 7.03, "506B60" if dark else RULE)
        self.tx(f"{number:02}", W-1.17, 7.08, .53, .28, 11,
                LIGHT if dark else MUTED, align=PP_ALIGN.RIGHT, record=False)
        self.fill_text(self.s.notes_slide.notes_text_frame,
                       notes + ("\n\nSources\n" + "\n".join(sources) if sources else ""),
                       11, INK, wrap=True)

    def node(self, content, x, y, w, h=.78, *, tone="rust", size=17):
        fill, fg = {"rust": (RUST_LIGHT, RUST), "pine": (PINE_LIGHT, PINE),
                    "neutral": (WHITE, INK), "dark": (DARK, WHITE)}[tone]
        s = self.box(x, y, w, h, fill, RULE if tone == "neutral" else None)
        self.fill_text(s.text_frame, content, size, fg, True, PP_ALIGN.CENTER)
        self.register(content)

    def flow(self, labels, y, *, x=M, w=12.05, gap=.27, h=.83, tones=None, size=17):
        width = (w - gap * (len(labels) - 1)) / len(labels)
        for i in range(len(labels) - 1):
            end = x + (i + 1) * (width + gap)
            self.line(end-gap+.035, y+h/2, end-.035, y+h/2, MUTED, arrow=True)
        for i, label in enumerate(labels):
            self.node(label, x + i*(width+gap), y, width, h,
                      tone=tones[i] if tones else "rust", size=size)

    def table(self, rows, x, y, widths, row_h, font=17, *, center=(), highlight=(), header=True):
        table = self.s.shapes.add_table(len(rows), len(widths), pt(x), pt(y), pt(sum(widths)),
                                        pt(len(rows)*row_h)).table
        table.first_row = table.first_col = table.horz_banding = table.vert_banding = False
        for col, width in zip(table.columns, widths):
            col.width = pt(width)
        for i, row in enumerate(rows):
            table.rows[i].height = pt(row_h)
            assert len(row) == len(widths)
            for j, value in enumerate(row):
                cell = table.cell(i, j)
                is_header = header and i == 0
                fill = DARK if is_header else PINE_LIGHT if i in highlight else WHITE if i % 2 else "E9DFCE"
                color = WHITE if is_header else PINE if i in highlight else INK
                cell.fill.solid()
                cell.fill.fore_color.rgb = rgb(fill)
                cell.margin_left = cell.margin_right = pt(.14)
                cell.margin_top = cell.margin_bottom = 0
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                self.fill_text(cell.text_frame, value, font, color, is_header or i in highlight,
                               PP_ALIGN.CENTER if j in center else PP_ALIGN.LEFT)
                self.register(value)

    def pic(self, name, x, y, width, height=None, *, alt="", image_text=()):
        path = self.assets / name
        if not path.is_file():
            raise FileNotFoundError(f"{path}: run the asset generation commands in README.md")
        with Image.open(path) as im:
            natural = width*im.height/im.width
        if height is not None and natural > height:
            new_width = width*height/natural
            x += (width-new_width)/2
            width, natural = new_width, height
        pic = self.s.shapes.add_picture(str(path), pt(x), pt(y), width=pt(width), height=pt(natural))
        pic._element.nvPicPr.cNvPr.set("descr", alt)
        self.records[-1]["image_text"].extend(image_text)
        return pic

    def retrieval(self, labels, values, x, y, w, h):
        data = CategoryChartData()
        data.categories = labels
        data.add_series("Queries", values)
        chart = self.s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, pt(x), pt(y), pt(w), pt(h), data).chart
        chart.has_legend = chart.has_title = False
        plot = chart.plots[0]
        plot.gap_width = 85
        chart.category_axis.reverse_order = True
        chart.category_axis.tick_labels.font.name = FONT
        chart.category_axis.tick_labels.font.size = Pt(18)
        chart.category_axis.tick_labels.font.color.rgb = rgb(INK)
        chart.category_axis.major_tick_mark = chart.category_axis.minor_tick_mark = XL_TICK_MARK.NONE
        chart.category_axis.format.line.fill.background()
        chart.value_axis.minimum_scale = 0
        chart.value_axis.maximum_scale = 34
        chart.value_axis.visible = False
        chart.value_axis.has_major_gridlines = False
        for i, point in enumerate(chart.series[0].points):
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = rgb(DARK if i == 0 else ORANGE)
            if i != 0:
                point.format.line.color.rgb = rgb(RUST)
        plot.has_data_labels = True
        dl = plot.data_labels
        dl.show_value, dl.position = True, XL_LABEL_POSITION.OUTSIDE_END
        dl.font.name, dl.font.size, dl.font.bold = FONT, Pt(18), True
        dl.font.color.rgb = rgb(INK)
        for label, value in zip(labels, values):
            self.register(f"{label} {value}")

    def save(self, output, blueprint):
        assert len(self.p.slides) == len(self.records) == 16
        md = ["# MAFIS slide blueprint", "",
              "16 slides, 16:9. Poppins. Deep green (#013230), cream (#F3EBDD) and orange (#FF6A1F).", "",
              "Sources: current implementation, saved workflow runs and the offline evaluation records. "
              "Course rubric: `report things/Final Guidelines.docx.pdf`.", ""]
        for i, r in enumerate(self.records, 1):
            visible = [*r["text"], f"{i:02}"]
            fixed, alternatives = [], []
            for item in r["image_text"]:
                (alternatives if isinstance(item, tuple) else fixed).append(item)
            longest = max(alternatives, key=lambda a: len(" ".join(a).split()), default=())
            n = len(" ".join([*visible, *fixed, *longest]).split())
            for word in BANNED:
                assert not re.search(rf"\b{re.escape(word)}\b", " ".join([*visible, *fixed, *longest]), re.I), (i, word)
            md += [f"## {i:02}. {r['title']}", "", f"**Layout:** {r['layout']}", "",
                   f"**Placement:** {r['placement']}", "", f"**Exact visible text** ({n} words"
                   + (", longest animation frame included" if alternatives else "") + "):", "", "```text",
                   *visible, *fixed, "```", ""]
            if alternatives:
                md += ["Embedded GIF text by frame (the final frame holds briefly):", "", "```text"]
                md += [" / ".join(a) for a in alternatives] + ["```", ""]
            md += ["**Speaker notes:** " + r["notes"], ""]
            md += ["**Sources:** " + " · ".join(f"`{s}`" if not s.startswith("https://") else f"<{s}>"
                                              for s in r["sources"]), ""]
        output.parent.mkdir(parents=True, exist_ok=True)
        blueprint.parent.mkdir(parents=True, exist_ok=True)
        for part in self.p.part.package.iter_parts():
            if part.content_type == "application/vnd.openxmlformats-officedocument.theme+xml":
                theme = part._element if isinstance(part, XmlPart) else etree.fromstring(part.blob)
                scheme = theme.find(".//" + qn("a:clrScheme"))
                scheme.set("name", "Deep Green, Cream and Orange")
                for role, value in THEME_COLORS.items():
                    entry = scheme.find(qn(f"a:{role}"))
                    entry[:] = [etree.Element(qn("a:srgbClr"), val=value)]
                if not isinstance(part, XmlPart):
                    part._blob = etree.tostring(theme, encoding="UTF-8", xml_declaration=True, standalone=True)
        self.p.save(output)
        blueprint.write_text("\n".join(md), encoding="utf-8")


def build(assets):
    data = closeout()
    arms = data["arms"]
    filings = filing_results()
    demo = read_json(assets / "apple_demo_scores.json")
    baseline, full = (demo["arms"][arm] for arm in ("baseline", "mafis"))
    metric_names = ["Revenue growth", "Operating margin", "Net margin", "Current ratio"]
    deck = Deck(assets)
    report = "report things/MAFIS Project Report.docx"
    results = "evaluation/results.md"
    graph = "graph.py"

    def add(title, section, layout, placement, notes, *sources, dark=False, cover=False):
        deck.slide(title, layout, placement, notes, (report, *sources),
                   dark=dark, cover=cover, section=section)

    def text(value, x, y, w, h, size=16, color=INK, *, bold=False):
        deck.tx(value, x, y, w, h, size, color, bold=bold,
                anchor=MSO_ANCHOR.TOP, wrap=True)

    def block(label, body, x, y, w, h=1.15, *, dark=False):
        text(label, x, y, w, .40, 17, ORANGE if dark else RUST, bold=True)
        text(body, x, y+.44, w, h-.42, 15.5, LIGHT if dark else INK)

    def band(value, y=6.19, *, dark=False):
        deck.box(M, y, W-2*M, .60, "194943" if dark else PINE_LIGHT)
        text(value, M+.17, y+.10, W-2*M-.34, .42, 14, WHITE if dark else PINE, bold=True)

    add("MAFIS", "Artificial Intelligence course project", "Dark cover with title and two results.",
        "Project scope on the left, Apple demo and retrieval findings on the right.",
        "MAFIS takes a question and a company filing and gives the reader a cited answer. A disclosure question can "
        "return checked excerpts, while a financial analysis can trace its calculations to filing cells. I'll show "
        "how we assign those cells to calculations, what happens when a required cell is missing, and what "
        "we measured in the Apple FY2024 demonstration. Both workflows ran local DeepSeek-R1. Full MAFIS delivered "
        "four results with correct values and inputs, and the single-call baseline delivered zero. The saved runs use one development filing.",
        "Readme.md", "agents/question_answer.py", demo["source"], results, cover=True, dark=True)
    text("MAFIS", M-.04, 1.33, 7.2, 1.56, 77, WHITE, bold=True)
    text("Multi-Agent Financial\nIntelligence System", M, 3.02, 7.05, 1.25, 30, WHITE, bold=True)
    text("Cited filing answers with local DeepSeek-R1 and a deterministic financial engine.",
         M, 4.70, 6.77, .97, 20, LIGHT)
    deck.line(8.00, 1.36, 8.00, 6.42, "506B60")
    text(f"{full['fully_supported']}/4", 8.39, 1.79, 4.17, 1.00, 52, ORANGE, bold=True)
    text(f"fully supported results in the Apple demo vs {baseline['fully_supported']}/4 for single DeepSeek",
         8.43, 2.90, 4.20, .91, 16, WHITE)
    text(f"{data['pages'][0]}/{data['pages'][1]}", 8.39, 3.98, 4.17, .95, 49, APRICOT, bold=True)
    text("labelled queries found the right PDF page in the top five", 8.43, 5.05, 4.16, .87, 17, WHITE)

    add("The correct row can contain the wrong answer", "Introduction", "Problem and example above an objective band.",
        "Question, source ambiguity and supported outputs appear in two columns.",
        "A filing row can contain several years. Finding the revenue row is only the first step. For the NVIDIA example, "
        "the system also needs to choose the right fiscal column and preserve the scale in millions. A balance-sheet "
        "number is a position on a date, while income describes activity over a period. For a disclosure question, "
        "the answer is drawn from verified passages. We compare the full financial workflow against a single model "
        "call on common source material.", "graph.py", "agents/question_answer.py", "tests/fixtures/nvidia_2024/annual_report.pdf")
    block("Task", "Answer questions about a filing. Full financial analysis also draws on dated market context.",
          M, 1.88, 5.55, 1.24)
    block("A concrete risk", "The NVIDIA revenue row contains FY2024, FY2023 and FY2022. The chosen cell must match the requested fiscal period.",
          6.75, 1.88, 5.94, 1.52)
    deck.line(M, 3.46, W-M, 3.46)
    block("Four financial calculations", "Annual revenue growth, operating margin, net margin and the current ratio.",
          M, 3.80, 5.55, 1.23)
    block("Design objective", "Link each answer to filing evidence. Show which inputs or disclosures the source leaves unavailable.",
          6.75, 3.80, 5.94, 1.52)
    band("Can source checks, exact arithmetic and a targeted correction improve annual filing analysis?")

    add("How MAFIS relates to prior financial QA work", "Literature review", "Three-column comparison table.",
        "Six papers from report Table 1, compared with the matching design choice in MAFIS.",
        "FinQA and FinanceBench give examples of evaluating reasoning and checking evidence. FinRAGBench-V and FinRank "
        "focus on evidence location and confusing alternatives. FinDebate and CLAIR-Fin are closer to our workflow. "
        "We use two interpretations of the same verified evidence and a mechanical Critic. These studies use different "
        "benchmarks, so our comparison here is about the technique.",
        "https://aclanthology.org/2021.emnlp-main.300/", "https://arxiv.org/abs/2311.11944",
        "https://aclanthology.org/2025.emnlp-main.211/", "https://aclanthology.org/2025.finnlp-2.20/",
        "https://arxiv.org/abs/2608.07400", "https://aclanthology.org/2026.finnlp-1.41/")
    deck.table([
        ["Related work", "Technique or focus", "MAFIS design choice"],
        ["FinQA (2021)", "Annotated numerical reasoning", "Fixed operations and exact input versions"],
        ["FinanceBench (2023)", "Questions with reference evidence", "Source-based scoring on local filings"],
        ["FinRAGBench-V (2025)", "Retrieval with visual citations", "Page and bounding-box locators"],
        ["FinDebate (2025)", "Specialist analysis and debate", "Checked Bull/Bear views and Critic rules"],
        ["FinRank (2026)", "Ranking confusable SEC passages", "Source and fiscal-period constraints"],
        ["CLAIR-Fin (2026)", "Claim ledger and adaptive rebuttal", "Versioned claims and one shared retry"],
    ], M, 1.67, [2.80, 4.12, 5.13], .59, 14)
    band("The course experiment uses its own single-call and unified-analyst baselines.")

    add("A state graph routes each filing question", "Methodology / State-space search",
        "State notation above three stages and a search explanation.",
        "Editable state tuple, transition chain and search comparison.",
        "This is the report's state-space abstraction of ExtendedState. We start with a question, its document descriptor "
        "and a fresh run store. Every transition changes the plan, evidence, verification status or retry budget. "
        "The Test Lab routes a disclosure question to document lookup. The financial path plans requested facts "
        "and operations. Both routes end with a cited answer or a record of what evidence is missing. "
        "The system searches the evidence index by cosine distance, so BFS over alternative workflows would solve a different problem.",
        graph, "agents/planner.py::PlannerAgent", "scripts/test_lab.py::sample_run", "rag/retriever.py::SharedRetriever")
    deck.box(M, 1.63, W-2*M, 1.04, RUST_LIGHT)
    text("S = (q, d, p, M, g, b, i)", M+.22, 1.74, 5.45, .61, 24, RUST, bold=True)
    text("Question, document, plan, SharedMemory,\ngate decision, retry budget, issues",
         6.17, 1.81, 6.28, .70, 15)
    deck.flow(["Initial state", "Graph transitions", "Terminal state"], 3.03, gap=.46, h=.69,
              tones=["neutral", "rust", "pine"], size=16)
    text("Question and document\nFresh run store", M+.12, 3.95, 3.52, .90, 15)
    text("Route the question, retrieve,\nverify and calculate if needed", 4.83, 3.95, 3.62, 1.03, 15)
    text("Cited answer and report\nEvidence gaps when applicable", 8.98, 3.95, 3.58, 1.03, 15)
    block("Where search happens", "LangGraph follows prescribed stages and checks branch conditions. SharedRetriever ranks evidence by cosine distance.",
          M, 5.33, 12, 1.23)

    add("Versioned claims preserve the evidence chain", "Methodology / Knowledge representation",
        "Index records and analytical records in parallel columns.",
        "Two record types above a four-node provenance chain.",
        "The index holds chunks for finding candidate evidence. The ledger holds the claims we can verify and the version "
        "each calculation used. A record includes its fiscal period, scale and exact source location. When a claim is "
        "revised, the old version remains in the ledger. is_current_verified checks that the referenced claim and its "
        "dependencies are still current before the result can support the report.",
        "rag/models.py", "memory/shared_memory.py")
    block("Retrieval index", "SourceChunk holds page-bounded text. TableCell adds typed values, fiscal headers and source locators.",
          M, 1.79, 5.68, 1.53)
    block("Run ledger", "ClaimVersionRef binds a run ID, claim ID and version. VerificationRecord and CalculationArtifact retain the evidence trail.",
          6.83, 1.79, 5.85, 1.53)
    deck.line(M, 3.41, W-M, 3.41)
    block("A financial primitive records", "Metric, value, entity, currency, scale, fiscal period and accounting scope.",
          M, 3.66, 5.68, 1.28)
    block("The source link records", "PDF page, printed page, quoted text, bounding box and table row or column.",
          6.83, 3.66, 5.85, 1.28)
    deck.flow(["Filing cell", "Verified claim\nversion", "Calculation\nartifact", "Report entry"], 5.11,
              h=.83, gap=.35, tones=["neutral", "rust", "pine", "dark"], size=15)
    band("The eligibility check follows the current claim and every dependency it cites.")

    add("NVIDIA revenue growth as a CSP", "Methodology / Constraint satisfaction",
        "Report figure above an input-assignment table and formula.",
        "The report’s NVIDIA income statement excerpt sits above the editable constraints and worked result.",
        "The operation is annual revenue growth. The variables are the current and previous revenue inputs. Their domain "
        "is the checked primitive references in this run. Both cells belong to NVIDIA's consolidated income statement. "
        "They have comparable adjacent annual periods, the same currency and scale, and the previous revenue is positive. "
        "Switching the two cells fails the period-role check. The engine validates the selected pair with Boolean rules.",
        "engine/financial_engine.py::_prepare", "tests/fixtures/nvidia_2024/annual_report.pdf, PDF page 150", results)
    deck.pic("report_figure_2.png", M, 1.59, 12.05, 2.19,
             alt="NVIDIA consolidated income statement excerpt with fiscal-year columns and revenue values",
             image_text=("NVIDIA Corporation and Subsidiaries. Consolidated Statements of Income. In millions, except per share data. "
                         "Year Ended. Jan 28, 2024. Jan 29, 2023. Jan 30, 2022. Revenue $60,922 $26,974 $26,914. "
                         "Cost of revenue 16,621 11,618 9,439.",))
    text("NVIDIA annual report, PDF page 150 (printed page 50)", M, 3.87, 12.05, .36, 12, MUTED)
    deck.table([["Variable", "Assigned cell", "Admissibility"],
                ["Current revenue", "60,922 · FY2024", "Same entity, scope and USD scale"],
                ["Previous revenue", "26,974 · FY2023", "Adjacent fiscal year, positive denominator"]],
               M, 4.28, [2.82, 3.08, 6.15], .43, 13)
    text("Input domain  ·  Verified primitive claim versions in this run", M, 5.71, 12.05, .35, 13, MUTED)
    band("(60,922 − 26,974) ÷ 26,974 × 100 = 125.8545%   ·   Swapping the years fails the period check.")

    add("The retriever preserves fiscal context", "Implementation / Document preparation",
        "Four-stage pipeline above retrieval settings.",
        "Editable source-to-selection workflow and paired interpretation of retrieval parameters.",
        "The parser reads born-digital annual filings. Narrative windows preserve page boundaries and table chunks retain "
        "headers, typed cells and evidence locations. The Apple benchmark uses all-MiniLM-L6-v2 text embeddings "
        "through ONNX on the CPU. DeepSeek-R1 handles generation and selection on this machine. "
        "Chroma ranks by cosine distance after applying metadata filters. Structured analysis uses a schema-bound "
        "choice of cells and quotes. In document lookup, the model chooses up to three excerpt IDs from the five "
        "retrieved narrative chunks. The code resolves the IDs to verbatim text and the verifier checks the citation.",
        "config.py::EMBEDDING_MODEL", "rag/ingest.py::prepare_document", "rag/retriever.py::SharedRetriever", "agents/document_agent.py::collect_context")
    deck.flow(["Parse PDF", "Chunk text\nand tables", "Filter and\nrank in Chroma", "Select cells\nand quotations"], 1.83,
              h=.91, gap=.41, tones=["neutral", "rust", "rust", "pine"], size=16)
    block("Narrative windows", "Page text 900 characters with 150 overlap. Section text 800 characters with 100 overlap.",
          M, 3.16, 5.66, 1.29)
    block("Structured table chunks", "Retain the exact statement row, fiscal header, units and source locator.",
          6.82, 3.16, 5.87, 1.29)
    block("Text embeddings", "all-MiniLM-L6-v2 runs on CPU. Chroma ranks by cosine distance within document and task filters.",
          M, 4.61, 5.66, 1.31)
    block("Retrieval limits", "Analysis uses up to 3 hits per narrative query and 5 per table query. Document Q&A selects up to 3 excerpts from 5 narrative hits.",
          6.82, 4.61, 5.87, 1.48)
    band("MiniLM and the generation models run inference. The project uses no training or fine-tuning.")

    add("Verification determines the next stage", "Implementation / Workflow",
        "Two-row workflow recreated from report Figure 1.",
        "The main diagram shows full financial analysis. A separate strip summarizes document Q&A.",
        "Planner decides scope, then we prepare the filing and select and verify its primitives. Financial and dated "
        "Market findings feed Risk, which is also verified. The gate checks the current evidence. If it passes, Bull "
        "and Bear use the same checked claims and Critic tests their structured assertions. A blocked gate routes "
        "straight to Planner. A retry reruns affected dependencies. Early planning or ingestion failures route to the "
        "gate. In document Q&A, the verifier checks the selected quotations before the report and answer use them. "
        "Test Lab shows the answer and offers the Markdown report for download. Its Shared Memory feed displays "
        "committed claims, calculation artifacts and stage events as the run proceeds.",
        graph, "agents/full_workflow.py", "agents/report_agent.py", "agents/question_answer.py", "dashboard/server.py", "memory/live_feed.py")
    deck.flow(["Planner\nSet scope", "Prepare PDF\nParse + index", "DocumentAgent\nSelect + verify",
               "Financial, Market, Risk\nCheck findings", "Health Gate\nTest eligibility"], 1.81,
              h=1.02, size=13.3, tones=["neutral", "rust", "rust", "rust", "pine"])
    y = 4.30
    for x1, x2 in [(3.19, 3.61), (6.37, 6.79), (9.63, 10.02)]:
        deck.line(x1, y+.47, x2, y+.47, MUTED, arrow=True)
    deck.line(11.59, 2.84, 11.59, 3.27, MUTED)
    deck.line(11.59, 3.27, 1.90, 3.27, MUTED)
    deck.line(1.90, 3.27, 1.90, y-.035, MUTED, arrow=True)
    deck.line(4.99, 3.27, 4.99, y-.035, MUTED, arrow=True)
    text("Pass", 2.02, 3.53, .8, .34, 12, PINE, bold=True)
    text("Blocked", 5.12, 3.53, 1.3, .34, 12, RUST, bold=True)
    deck.node("Bull, Bear, Critic\nInterpret + check", M, y, 2.55, .94, size=14)
    deck.node("Planner decision\nAt most one retry", 3.65, y, 2.72, .94, tone="pine", size=14)
    deck.node("Targeted correction\nRerun affected stages", 6.83, y, 2.80, .94, tone="pine", size=14)
    deck.node("Analysis map + report\nFindings and gaps", 10.06, y, 2.63, .94, tone="dark", size=14)
    deck.line(4.99, y+.94, 4.99, 5.73, MUTED)
    deck.line(4.99, 5.73, 11.37, 5.73, MUTED)
    deck.line(11.37, 5.73, 11.37, y+.98, MUTED, arrow=True)
    text("No retry needed or available", 6.37, 5.83, 3.49, .33, 12, MUTED)
    band("Document Q&A   Retrieve passages → select excerpts → verify wording and pages → cited answer.")

    add("Models propose. Rules decide eligibility.", "Implementation / Agents and settings",
        "Two responsibility columns above a settings strip.",
        "Left presents model roles. Right presents arithmetic, screening and routing checks.",
        "DocumentAgent selects filing cells. FinancialAgent selects allowed operations. The Bull and Bear agents use "
        "the same verified snapshot, and an optional Critic model call describes findings already detected by rules. "
        "The arithmetic runs in a 50-digit Decimal context, with half-up rounding for the four-decimal display. "
        "Market screens dated sources and Risk labels hypotheses. Ollama runs DeepSeek-R1 on the same machine. "
        "It uses compact evidence IDs for structured selection and restores full references before agent checks. "
        f"The Apple comparison used temperature {demo['settings']['temperature']}, thinking disabled and a "
        f"{demo['settings']['output_tokens_per_request']:,}-token output cap for both arms. The injected validation sweep "
        "from 0 to 1 in steps of 0.25 leaves the 0.5 engineering default in place.",
        "config.py", "gemini.py::GeminiSettings", "ollama_adapter.py::OllamaAdapter", "agents/verification_gate.py", "agents/critic_agent.py",
        "engine/financial_engine.py", "evaluation/batch2.py::freeze_threshold")
    deck.line(6.57, 1.66, 6.57, 5.78)
    block("Model calls", "Document and Financial agents propose source cells and operations. Bull and Bear propose interpretations from one checked snapshot.",
          M, 1.70, 5.60, 1.73)
    block("Deterministic checks", "Verification can replay 50-digit Decimal calculations. The Critic applies conflict rules to typed claims.",
          6.89, 1.70, 5.80, 1.64)
    block("Local Ollama · deepseek-r1:8b", "4,096-token context and 8 KiB JSON request limit. Compact IDs resolve to exact filing references.",
          M, 3.57, 5.60, 1.46)
    block("Demo settings for both arms", "Temperature 0, thinking disabled, 1,024 output tokens per request. Gemini is an opt-in cloud path.",
          6.89, 3.57, 5.80, 1.55)
    band("Health Gate blocks above 0.5 ineligible, on empty evidence or on explicit upstream issues. One analytical retry.")

    add("Seven filings produced all four calculations", "Offline closeout / Source coverage",
        "Coverage metrics above the report’s seven-issuer result table.",
        "Editable reproduction of report Table 3, with fiscal-year percentages and unitless current ratios.",
        "Thirteen FY2024 source slots yielded ten local PDFs. Seven were admitted and each contributed six primitives "
        "and four calculations. The other three local filings failed preparation, and three requested sources were "
        "unavailable. The market excerpt was from the January 31, 2024 FOMC statement. Some layouts had already "
        "informed parser development, so the admitted files do not represent a fresh held-out evaluation.",
        results, "tests/fixtures/batch2_cases.json")
    for x, num, label in [(M, data["slots"], "FY2024 source slots"), (4.70, data["local"], "local PDFs"),
                          (8.75, data["supported"], "admitted filings")]:
        text(str(num), x, 1.54, .9, .72, 33, PINE, bold=True)
        text(label, x+.99, 1.75, 2.83, .40, 14, MUTED)
    deck.table([["Filing", "Revenue growth %", "Operating margin %", "Net margin %", "Current ratio"], *filings],
               M, 2.39, [2.00, 2.49, 2.78, 2.33, 2.45], .44, 14, center=(1, 2, 3, 4), highlight=(1,))
    text("Market source  ·  31 January 2024 FOMC statement excerpt. The closeout includes parser-exposed filings.",
         M, 6.30, 12.05, .46, 14, MUTED)

    add("Page retrieval and numerical coverage", "Results / Evaluation metrics",
        "Native retrieval chart beside numerical scoring and misses.",
        "Top-five page and anchor counts on the left. Reference arithmetic and denominators on the right.",
        "The first bar counts queries with a labelled page among the top five chunks. The second bar requires the "
        "labelled text anchor to appear in a retrieved chunk. Coca-Cola currency and AMD income missed the page. "
        "NVIDIA operating cash and Apple's calendar missed the anchor despite making the page. The independent "
        "oracle uses Fraction and 80-digit Decimal. Twenty-eight returned scorable outputs all matched within "
        "0.00005 in the reported unit. Across the 52 requested slots, 13 lacked reference values.",
        results, "evaluation/batch2.py::score_retrieval", "evaluation/metrics.py::numerically_equal")
    text("MiniLM retrieval · 30 labelled queries · top 5", M, 1.62, 6.65, .42, 16, RUST, bold=True)
    deck.retrieval(["Page hit", "Anchor passage"], [data["pages"][0], data["anchors"][0]], M, 2.06, 6.55, 2.92)
    text("Page recall 28/30\nPage misses  Coca-Cola currency and AMD income",
         M, 5.13, 6.22, .92, 14, MUTED)
    deck.line(7.32, 1.69, 7.32, 6.64)
    block("Independent calculation reference", "Fraction arithmetic and 80-digit Decimal division. Absolute tolerance 0.00005 in the reported unit.",
          7.61, 1.67, 5.07, 1.55)
    block("28/28 returned and scorable", "All returned, scorable results matched. The 28/52 figure counts correct results across all requested slots.",
          7.61, 3.34, 5.07, 1.55)
    block("Missing reference values", "39 slots had source-inspected inputs. The other 13 had no reference value.",
          7.61, 5.06, 5.07, 1.38)

    add("Source failures and injected checks", "Results / Failure analysis",
        "Reasons for rejected filings on the left, detection counts on the right.",
        "The report’s admission examples and counts from the verification and contradiction tests.",
        "Intel lacked admissible currency evidence. Walmart's statement fonts lacked a usable Unicode mapping in "
        "this parser. Nike failed currency admission and lacked a separately reported operating-income row. "
        "Microsoft, Alphabet and Netflix were unavailable. The verifier and Critic were also tested on small "
        "injected cases. The Apple document run shows a different kind of evidence gap. It verified a passage "
        "describing market share qualitatively, and flagged the missing percentage. Verification checks wording "
        "and source location, while coverage depends on whether the passage answers the question.",
        results, "evaluation/mechanisms.py", "tests/fixtures/batch2_cases.json",
        "output/test_lab/dynamic-apple-final/run_summary.json")
    deck.table([["Filing", "Why admission failed"],
                ["Intel", "Reporting currency unestablished"],
                ["Walmart", "Unsupported statement text encoding"],
                ["Nike", "Currency unclear and no operating-income row"]],
               M, 1.84, [1.60, 5.12], .60, 13.3)
    text("Unavailable PDFs  Microsoft, Alphabet and Netflix", M, 4.53, 6.68, .77, 15, MUTED)
    checks = [[label, *[str(data["injected"][key][metric]) for metric in ("tp", "tn", "fp", "fn")]]
              for key, label in (("Verifier", "Verification"), ("Critic", "Contradictions"))]
    deck.table([["Injected test", "TP", "TN", "FP", "FN"], *checks],
               7.62, 1.84, [2.09, .75, .75, .75, .73], .60, 13.3, center=(1, 2, 3, 4))
    text("Precision and recall 1.0 on these small injected sets.", 7.62, 3.94, 5.07, .70, 15, MUTED)
    band("Apple FY2024, PDF p. 10  ·  The cited passage describes a minority smartphone share and gives no percentage.")

    add("One retry restores NVIDIA’s net margin", "Demonstration / Saved offline run",
        "Animated trace beside gate states and the recovered result.",
        "The looping GIF is embedded on the left. The report’s saved Test Lab counters and outcome are on the right.",
        "The first mock response omits net income, so net margin is unavailable. All 14 factual claims present "
        "were eligible, but the gate had an explicit upstream issue and blocked. Planner spent its only retry "
        "on net income and net margin. Document, Financial and Risk reran with checks. The final gate had 17 "
        "eligible factual claims, and the report recovered net margin at 48.8493%. The persistent scenario stayed partial.",
        "output/test_lab/verify-corrected/scenario.json", "output/test_lab/verify-corrected/evidence.json",
        "output/batch2/demo/results.json", "scripts/test_lab.py", dark=True)
    steps = [("Net income omitted", "First model response"), ("Health Gate blocks", "Required evidence missing"),
             ("Planner allocates retry", "Budget: 1 to 0"), ("Net income verified", "Financial Engine recomputes"),
             ("48.8493% net margin", "Gate passes · report succeeds")]
    deck.pic("nvidia_correction.gif", M, 2.03, 7.65, alt="Offline NVIDIA retry replay in five frames",
             image_text=tuple((f"STEP {i:02d} / 05", head, detail, "Omission Gate Planner Recheck Report")
                              for i, (head, detail) in enumerate(steps, 1)))
    deck.line(8.57, 1.72, 8.57, 5.93, "506B60")
    block("Before correction", "14/14 present claims eligible. Missing net income blocks the gate.",
          8.89, 1.80, 3.79, 1.43, dark=True)
    block("After one correction", "17/17 eligible. All four calculations present, including 48.8493% net margin.",
          8.89, 3.29, 3.79, 1.58, dark=True)
    text("10 mock calls · 0 live requests", 8.89, 5.22, 3.79, .83, 15, LIGHT, bold=True)
    band("If the mock omits net income again, the report stays partial after the retry.", dark=True)

    add("Apple FY2024 demo benchmark", "Results / Paired local inference",
        "Editable four-metric result table above the score and run counts.",
        "Oracle values next to the outputs of single-call DeepSeek-R1 and Full MAFIS.",
        "Both arms ran deepseek-r1:8b in Ollama with the same Apple question, filing, model settings and dated market source. "
        "The single model calculated the metrics. Full MAFIS used its deterministic engine and additional verification retrieval. "
        "A score requires the right value, fiscal period, unit and both input citations. Both arms cited the correct inputs for "
        "four of four metrics. The baseline reports two decimal places, and all four values miss the numerical tolerance. "
        "Narrative quality was unscored. Shared indexing was excluded from wall time, and run order, caches and warm-up can affect it. "
        "The table uses the more recent saved run. An earlier run on the same development case reproduced the scores. "
        "The Test Lab command is python -m scripts.test_lab apple-benchmark.",
        "evaluation/apple_benchmark.py::run_apple_benchmark", demo["source"], demo["repeat_source"], "tests/fixtures/apple_2024/annotations.json")
    text("Same local DeepSeek-R1, Apple filing and dated market evidence", M, 1.58, 12.05, .41, 15, MUTED)
    benchmark_rows = []
    for label, left, right in zip(metric_names, baseline["rows"], full["rows"], strict=True):
        assert left["operation"] == right["operation"] and left["expected"] == right["expected"]
        unit = "%" if left["unit"] == "percent" else "×"
        benchmark_rows.append([label, left["expected"] + unit, left["observed"] + unit, right["observed"] + unit])
    benchmark_rows.append(["Fully supported", "Value, unit, period + inputs", f"{baseline['fully_supported']}/4", f"{full['fully_supported']}/4"])
    deck.table([["Metric", "Independent reference", "Single DeepSeek-R1", "Full MAFIS"], *benchmark_rows],
               M, 2.10, [3.08, 3.12, 3.08, 2.77], .54, 14, center=(1, 2, 3), highlight=(5,))
    text(f"Input citations {baseline['citations_correct']}/4 in both arms   ·   Requests {baseline['calls']} vs {full['calls']}   ·   "
         f"Observed wall time {baseline['seconds']:.1f} s vs {full['seconds']:.1f} s", M, 5.60, 12.05, .41, 14.5, INK, bold=True)
    band("One development filing. Wall time excludes shared indexing. Narrative quality was unscored.")

    add("What changes when components are removed", "Results / Ablations and trade-offs",
        "Five-row ablation table with timing and interpretation.",
        "Editable timing and call-count table, plus changes to the path each condition can exercise.",
        "This table is from the separate mock evaluation. Every condition completed on seven admitted filings and retained six preparation failures. Over eight "
        "conditions that gives 56 completions and 48 failures. Removing verification changes which claims can "
        "support the report. Removing the engine changes who does the arithmetic. The timings include retrieval "
        "under concurrent validation load. In one saved Apple full run on Ollama, context compaction reduced "
        "the cumulative context from 85,178 to 3,828 bytes across eight model requests. The context counts exclude "
        "the rest of the request body. This is a run example. Controlled latency and peak memory remain unmeasured.",
        results, "evaluation/batch2.py::CONDITIONS", "evaluation/experimental.py",
        "output/test_lab/ollama-full-verify/scenario.json")
    ablations = [
        ("without_verification", "Verification", "Claims remain unchecked"),
        ("without_bull_bear", "Bull and Bear", "No paired interpretations"),
        ("without_critic", "Critic", "No mechanical conflict check"),
        ("without_reanalysis", "Re-analysis", "No targeted rerun"),
        ("without_engine", "Financial Engine", "Model arithmetic without artifacts"),
    ]
    deck.table([["Component removed", "Change in execution", "Mock calls", "Mean local s"]]
               + [[name, effect, str(arms[key][4]), f"{arms[key][5]:.3f}"] for key, name, effect in ablations],
               M, 1.78, [3.0, 5.22, 1.77, 2.06], .60, 14, center=(2, 3))
    text("Mock evaluation  ·  28/52 correct per condition, 56 completions and 48 preparation failures.",
         M, 5.55, 12.03, .42, 14.5, INK, bold=True)
    text("Apple local example  ·  Context shrank from 85,178 to 3,828 bytes across 8 requests.",
         M, 6.03, 12.03, .40, 14.5, RUST, bold=True)
    text("Mock timings include retrieval under load. Controlled latency and peak memory remain unmeasured.",
         M, 6.52, 12.03, .37, 13, MUTED)

    add("Paired evaluation on unseen filings", "Discussion / Limits and next steps",
        "Three limitation-and-action rows above an ethics band.",
        "Each gap from the report is paired with the next measurement.",
        "The Apple runs exercised both arms on one known development filing. The next evaluation needs matched local "
        "runs on unseen filings and repetitions to measure runtime variability. "
        "No human ratings have been imported. To test reliability, we'd run those pairs, "
        "have independent reviewers trace the claims, and measure timing and peak memory under controlled conditions. "
        "We also need to record failures by filing format and keep missing evidence visible. In live mode, the question "
        "and retrieved excerpts are sent to the model service. Ollama sends its requests to the local service.",
        demo["source"], results, "evaluation/batch2.py::import_ratings", "tests/fixtures/batch2_cases.json", "ollama_adapter.py", dark=True)
    for y, issue, action in [
        (1.67, "One development filing", "Repeat matched local trials on unseen filings. Measure latency variance and peak memory."),
        (3.07, "Zero imported reviewer ratings", "Grade numerical answers and source support independently against the filings."),
        (4.47, "Parser admission varies by filing", "Test new layouts and retain preparation failures in coverage by format."),
    ]:
        text(issue, M, y+.07, 5.03, .61, 18, WHITE, bold=True)
        text(action, 6.00, y+.06, 6.68, .85, 16, ORANGE)
        deck.line(M, y+1.11, W-M, y+1.11, "506B60")
    band("Expose evidence gaps, label risk as a hypothesis and keep cloud execution opt-in.", dark=True)
    return deck


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, default=ASSETS)
    parser.add_argument("--output", type=Path, default=HERE / "MAFIS_AI_Project_Benchmark.pptx")
    parser.add_argument("--blueprint", type=Path, default=HERE / "report_slide_blueprint.md")
    args = parser.parse_args()
    build(args.assets).save(args.output, args.blueprint)
