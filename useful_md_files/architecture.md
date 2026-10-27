# MAFIS — Architecture Reference v1.1

> Authoritative architecture reference for implementation. Read this together with `design.md` and `memory.md` before changing agent behavior, orchestration, or shared state.

## System Summary

MAFIS produces evidence-backed financial intelligence reports through a team of specialized agents coordinated by LangGraph. Agents use one structured, append-only Shared Memory / Evidence Store rather than passing raw natural-language messages directly. Financial numbers are produced by deterministic Python calculations, not by free-form LLM arithmetic. Verification, opposing viewpoints, structured critique, and a single capped targeted re-analysis loop are used to improve reliability.

The architecture is intentionally task-oriented rather than simply increasing the number of agents. Literature reviewed for MAFIS shows that multi-agent collaboration is useful for some complex financial tasks but can add noise on simpler tasks. Therefore, each agent has a specific reason to exist and the system must evaluate whether each added mechanism actually improves reliability.

## Diagram

See `mafis_architecture_preview.png` for the current visual flow. The diagram should remain consistent with the data-flow rules below. The Report Generation Agent's internal ``Evidence / Analysis Map`` stage and structured re-analysis metadata need not be separate boxes in the high-level diagram.

## Components

| Component | Responsibility | Depends on |
|---|---|---|
| Planner Agent | Understand the request, build the task/dependency graph, choose required agents, and determine targeted re-analysis scope | — |
| Document Agent | Extract source-grounded facts and raw financial primitives from uploaded documents with page/section citations | RAG |
| RAG / Knowledge Layer | Chunk, embed, index, and retrieve evidence; expose task-aware retrieval profiles through one shared retrieval tool | — |
| Financial Agent | Decide what financial calculations are needed, request them from the deterministic engine, and interpret the exact results | Document Agent, Shared Memory, Engine, RAG |
| Deterministic Financial Engine | Execute exact ratios, growth calculations, valuation calculations, and sanity checks | Financial Agent |
| Market Agent | Research market, industry, macro, news, and company catalysts; provide descriptive market context | RAG / external sources |
| Risk Agent | Combine financial and market evidence to identify financial, operational, market, regulatory, macro, governance, and competitive risks | Financial Agent, Market Agent, RAG |
| Shared Memory / Evidence Store | Central append-only, versioned workspace for claims, evidence, calculations, verification status, contradictions, and run metadata | All agents |
| Verification Agent | Independently check claims against fresh evidence retrieval and deterministic results; assign support/verification status | Shared Memory, RAG, Engine outputs |
| Verification Health Gate | Check aggregate evidence quality before expensive downstream reasoning | Verification output |
| Bull Agent | Construct the strongest positive case using verified claims only; may flag missing evidence | Verified Shared Memory |
| Bear Agent | Construct the strongest negative/counter case using verified claims only; may flag missing evidence | Verified Shared Memory |
| Critic Agent | Run structured contradiction checks first, then use an LLM to explain flagged conflicts and identify missing support; recommend re-analysis scope | Bull, Bear, Shared Memory |
| Targeted Re-analysis | Re-run only the implicated downstream chain when a real issue is detected; bounded by a shared retry budget | Planner |
| Report Generation Agent | Build an internal evidence/analysis map and then synthesize the final report from supported claims only | Final Shared Memory state |

## Agent Responsibilities — Simple View

1. **Planner:** Decides what work needs to be done and in what order.
2. **Document Agent:** Reads the supplied financial documents and extracts facts/numbers with citations.
3. **Financial Agent:** Decides which financial metrics or valuation calculations are needed and asks the calculator to do them.
4. **Market Agent:** Finds relevant market, industry, macro, news, and company developments.
5. **Risk Agent:** Combines the financial and market findings to identify and explain risks.
6. **Verification Agent:** Independently checks whether claims and calculations are actually supported.
7. **Bull Agent:** Builds the strongest positive case using only verified evidence.
8. **Bear Agent:** Builds the strongest negative case using only verified evidence.
9. **Critic Agent:** Looks for real contradictions, unsupported conclusions, missing evidence, or broken logic.
10. **Report Generation Agent:** Organizes the verified evidence into a coherent final financial intelligence report.

## Data Flow

1. Planner receives the user query and optional documents, builds a dependency graph, and dispatches only the agents needed for the task.
2. Document Agent uses RAG to extract source-grounded facts and raw primitives and writes them to Shared Memory.
3. Financial Agent reads the relevant structured primitives from Shared Memory and sends structured calculation requests to the deterministic engine. The engine validates inputs, calculates, validates outputs, and returns exact results. Financial Agent interprets the result and writes a derived claim with a calculation reference.
4. Market Agent performs market/industry/news research through the shared retrieval layer and writes structured findings to Shared Memory.
5. Risk Agent consumes Financial and Market findings and may retrieve additional source evidence directly when needed. It writes structured risk claims with references to the evidence and/or upstream calculations that support them.
6. Verification Agent independently re-queries RAG for source-backed claims and checks derived numeric claims against deterministic calculation results. It writes verification status and support level as a new version of the claim.
7. Verification Health Gate checks aggregate verification quality. If systemic evidence failure is detected, it sends a structured re-analysis request to the Planner instead of spending compute on Bull/Bear/Critic.
8. After the gate passes, Bull and Bear read only verified claims. They may identify evidence gaps, but they may not present newly retrieved or unverified evidence as fact.
9. If Bull or Bear identifies a meaningful evidence gap, the Planner may request targeted retrieval/re-analysis. Any newly retrieved evidence must pass Verification before it becomes eligible for Bull/Bear assertions.
10. Critic first checks structured fields mechanically for contradiction types such as numerical, temporal, unit, source, logical, causal, and risk-interpretation conflicts. An LLM then explains flagged conflicts and determines whether targeted re-analysis is warranted.
11. If a real problem is detected and the shared retry budget is available, Planner re-runs only the implicated agent(s) and their necessary downstream dependents. The affected claims are versioned rather than overwritten, then re-verified and re-criticized.
12. If the retry budget is exhausted and a problem remains, the issue is marked unresolved and is surfaced explicitly in the final report.
13. Report Generation builds an internal Evidence / Analysis Map linking report sections to claim IDs, evidence, calculations, support levels, and unresolved issues. It then writes the final report without re-deriving facts from free text.

## Important Architectural Rules

- RAG is one shared retrieval layer, not a collection of agent-private knowledge bases.
- Financial Agent does not re-extract values from raw PDFs when Document Agent has already produced the relevant primitive.
- Raw numeric primitives may exist in memory when they are directly extracted from a cited source, but derived/final numeric claims must trace to the Deterministic Financial Engine.
- Agents do not pass raw free-form outputs directly to other agents; structured state is the communication interface.
- Bull and Bear may assert only verified claims. They may request more evidence, but newly retrieved evidence must be verified before it can support a new assertion.
- Critic does not silently rewrite claims. It records findings and routes targeted re-analysis through Planner.
- Re-analysis uses one shared retry budget across all triggers. The initial default is one retry; this is an engineering control, not a claim that one is theoretically optimal.

## Tech Stack

- Orchestration: LangGraph
- Backend: Python + FastAPI
- Document parsing: `pdfplumber` / `unstructured` + Tesseract OCR fallback
- RAG: embeddings + Chroma or FAISS
- Financial computation: Python, Pandas, NumPy, custom deterministic modules
- External data: SEC EDGAR XBRL API by default for supported US filings, plus a tested news/market source when needed
- Storage: LangGraph state for MVP; persistent database only if required for cross-session use

## Suggested Module Layout

```text
mafis/
  agents/
    planner.py
    document_agent.py
    financial_agent.py
    market_agent.py
    risk_agent.py
    verification_agent.py
    bull_agent.py
    bear_agent.py
    critic_agent.py
    report_agent.py
  engine/
    financial_engine.py
  rag/
    retriever.py
    ingest.py
  memory/
    shared_memory.py
  graph.py
  config.py
```

## Evaluation Instrumentation

Instrument the system from the beginning for:

- Numerical correctness
- Unsupported claim rate
- Citation coverage
- Evidence retrieval hit rate / recall@k
- Verification precision/recall on injected errors
- Contradiction detection rate
- Confidence/support calibration
- Analytical coverage/depth
- End-to-end latency
- Token/API cost
- Human-rated report quality

The main experiment remains a same-model single-LLM baseline versus full MAFIS, followed by component ablations.
