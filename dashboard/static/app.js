const $ = (id) => document.getElementById(id);
const statuses = {
  passed: "Passed", failed: "Failed", running: "Running", blocked: "Blocked",
  completed: "Completed", interrupted: "Interrupted", unanswered: "Unanswered",
};
const artifactNames = {
  "report.md": "Download report (.md)", "run_summary.json": "Run summary", "analysis_map.json": "Analysis map",
  "evidence.json": "Evidence & calculations", "scenario.json": "Scenario checks",
  "gemini_readiness.json": "Gemini diagnostics", "ollama_readiness.json": "Ollama diagnostics", "retrieval.json": "Retrieval scores",
  "results.json": "Evaluation results", "manifest.json": "Evaluation manifest",
  "benchmark.md": "Benchmark report", "benchmark.json": "Benchmark data",
  "apple_baseline.md": "Single-model report", "apple_mafis.md": "Full MAFIS report",
  "source_coverage.json": "Source coverage", "run.log": "Full log",
};
const metrics = {
  revenue_growth: "Revenue growth", operating_margin: "Operating margin",
  net_margin: "Net margin", current_ratio: "Current ratio",
};
const providerErrors = {
  invalid_credential: "Google rejected the credential",
  billing_restriction: "Google reported a billing restriction",
  model_or_project_access: "The project could not access this model",
  quota_exhaustion_or_rate_limit: "Google reported a quota or rate limit",
  schema_or_config: "Gemini configuration error",
  network_or_sdk_error: "Network or SDK error",
};
const timeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
let catalog;
let selectedRun;
let previousHistory = "";
let displayedRun;
let displayedStatus;
let memoryView;
let inspectedStage;
const workflowStages = {
  benchmark_prepare: ["Benchmark preparation", "Index the Apple filing and prepare the shared benchmark evidence."],
  baseline: ["Single-model baseline", "Send one request to DeepSeek-R1 for the Apple benchmark."],
  planner: ["Planner agent", "Choose the tasks needed to answer the question."],
  ingest: ["PDF ingestion", "Read the filing and prepare its source index."],
  document: ["Document agent", "Retrieve and select source evidence."],
  verification: ["Verification agent", "Check claims and citations against indexed evidence."],
  financial: ["Financial agent", "Select operations and check interpretations of the results."],
  engine: ["Deterministic engine", "Calculate the requested figures from source inputs."],
  market: ["Market agent", "Collect dated market context."],
  risk: ["Risk agent", "Assess risks from checked evidence."],
  health_gate: ["Verification Health Gate", "Decide whether the evidence supports further analysis."],
  bull: ["Bull agent", "Build a positive interpretation from checked evidence."],
  bear: ["Bear agent", "Build a cautionary interpretation from checked evidence."],
  critic: ["Critic agent", "Check for contradictions."],
  retry_check: ["Reanalysis check", "Review whether a targeted retry is needed."],
  retry: ["Targeted retry", "Rerun the affected steps using the existing evidence."],
  report: ["Report agent", "Assemble the answer, citations and report."],
};
const workflowTiles = {};
let busy = false;
let submitting = false;

function element(tag, value, className) {
  const node = document.createElement(tag);
  if (value !== undefined) node.textContent = value;
  if (className) node.className = className;
  return node;
}

function option(value, label) {
  const node = element("option", label);
  node.value = value;
  return node;
}

async function api(path, settings) {
  const response = await fetch(path, settings);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "The request failed.");
  return body;
}

function notice(message, scroll = true) {
  $("notice").textContent = message;
  $("notice").hidden = !message;
  if (message && scroll) $("notice").scrollIntoView({ block: "nearest" });
}

function disableLaunches() {
  for (const button of document.querySelectorAll("[data-check], #run-scenario")) {
    button.disabled = busy || submitting;
  }
}

function updateForm() {
  const custom = $("case").value === "custom";
  const workflow = $("workflow").value;
  const live = $("mode").value === "live";
  const ollama = $("mode").value === "ollama";
  const scenario = $("scenario");
  for (const choice of scenario.options) {
    const analysis = ["clean", "document"].includes(choice.value);
    choice.disabled = (live && !analysis) ||
      ((workflow !== "full" || ollama) && ["corrected", "persistent"].includes(choice.value)) ||
      (custom && !analysis);
  }
  if (scenario.selectedOptions[0]?.disabled) scenario.value = "clean";
  const lookup = scenario.value === "document";
  const mock = ["mock", "minilm"].includes($("mode").value);
  $("scenario-hint").textContent = catalog.scenarios[scenario.value][1] +
    (lookup && mock ? " Mock execution simulates an empty answer." : "");
  $("workflow").disabled = lookup;
  const item = catalog.samples.find((sample) => sample.id === $("case").value);
  const fixedQuestion = scenario.value === "unsupported";
  $("question").disabled = fixedQuestion;
  $("question").required = lookup;
  $("question").placeholder = fixedQuestion ? "Assess Q2 quarterly financial performance" :
    lookup ? "What does the report say about its suppliers?" :
      item?.question || "Assess annual financial health, revenue growth, profitability and liquidity";
  $("question-help").textContent = lookup ? "Enter a question about the selected PDF." :
    "Ask about the filing or a supported financial calculation. Leave blank to use the sample question.";
  $("custom-fields").hidden = !custom;
  for (const input of $("custom-fields").querySelectorAll("input")) {
    input.required = custom;
    input.disabled = !custom;
  }
  $("live-fields").hidden = !live;
  $("ollama-fields").hidden = !ollama;
  $("confirm-free").required = live;
  $("budget").required = live;
  $("budget").disabled = !live;
}

function createCard(container, title, description) {
  const card = element("article", undefined, "panel test-card");
  const actions = element("div", undefined, "actions");
  card.append(element("h3", title), element("p", description), actions);
  $(container).append(card);
  return actions;
}

function renderCatalog(data) {
  catalog = data;
  const count = data.samples.filter((sample) => sample.available).length;
  $("sample-count").textContent = `${count} ${count === 1 ? "annual report" : "annual reports"}`;
  $("sample-count").hidden = false;
  for (const sample of data.samples) {
    const choice = option(sample.id, sample.entity);
    choice.disabled = !sample.available;
    $("case").append(choice);
    const actions = createCard("sample-list", sample.entity, sample.title);
    const use = element("button", "Use document", "button secondary");
    use.type = "button";
    use.dataset.sample = sample.id;
    use.setAttribute("aria-label", `Use document: ${sample.entity}`);
    use.disabled = !sample.available;
    actions.append(use);
    if (sample.available) {
      const link = element("a", "Download PDF", "button secondary");
      link.href = `/samples/${sample.id}.pdf`;
      link.setAttribute("aria-label", `Download PDF: ${sample.entity}`);
      actions.append(link);
    }
  }
  $("case").append(option("custom", "Upload your own PDF"));
  for (const [id, label] of Object.entries(data.workflows)) $("workflow").append(option(id, label));
  $("workflow").value = "full";
  for (const [id, [label]] of Object.entries(data.scenarios)) $("scenario").append(option(id, label));
  updateForm();
}

function appendList(target, entries) {
  if (!entries.length) return;
  const list = element("ul");
  for (const text of entries) list.append(element("li", text));
  target.append(list);
}

function renderAnswer(answer) {
  const section = element("section", undefined, "question-answer");
  section.append(element("h3", "Answer to your question"));
  if (!answer) {
    section.append(element("p", "Run this question again to see an answer and its evidence here."));
    return section;
  }
  section.append(element("p", answer.question, "submitted-question"));
  if (answer.message) section.append(element("p", answer.message));
  if (answer.items.length) {
    const list = element("ul", undefined, "answer-items");
    for (const { label, value, period, entity, verification, sources } of answer.items) {
      const item = element("li");
      const result = element("p");
      result.append(element("strong", label), document.createTextNode(` — ${value}`));
      item.append(result);
      const context = [entity, period].filter(Boolean).join(" · ");
      if (context) item.append(element("p", context, "answer-evidence"));
      if (sources.length) {
        const support = verification === "verified" ? "Independently checked" : "Independent verification pending";
        item.append(element("p", `${sources.join(" · ")} · ${support}`, "answer-evidence"));
      }
      list.append(item);
    }
    section.append(list);
  }
  return section;
}

function renderDetails(job) {
  const details = $("run-details");
  details.replaceChildren();
  const scenario = job.results["scenario.json"];
  const summary = job.results["run_summary.json"];
  const gemini = job.results["gemini_readiness.json"];
  const ollama = job.results["ollama_readiness.json"];
  const benchmark = job.results["benchmark.json"];
  if (benchmark) {
    const { baseline, mafis } = benchmark.arms;
    details.append(element("p", benchmark.verdict));
    details.append(element("p", `Apple FY2024 · ${benchmark.model}`));
    const table = element("table", undefined, "benchmark-table");
    const header = element("tr");
    for (const title of ["Measure", "Single model", "Full MAFIS"]) {
      const column = element("th", title);
      column.scope = "col";
      header.append(column);
    }
    table.createTHead().append(header);
    const body = table.createTBody();
    const score = (arm, key) => arm.status === "failed" ? "Unavailable" : `${arm[key]}/4`;
    for (const [label, left, right] of [
      ["Correct results", score(baseline, "correct"), score(mafis, "correct")],
      ["Correct input citations", score(baseline, "citations_correct"), score(mafis, "citations_correct")],
      ["Fully supported results", score(baseline, "fully_supported"), score(mafis, "fully_supported")],
      ["Ollama requests", baseline.calls, mafis.calls],
      ["Wall time", `${baseline.seconds.toFixed(1)} s`, `${mafis.seconds.toFixed(1)} s`],
    ]) {
      const row = body.insertRow();
      const heading = element("th", label);
      heading.scope = "row";
      row.append(heading, element("td", left), element("td", right));
    }
    details.append(table);
  }
  if (scenario) {
    const answer = summary?.answer || scenario.answer;
    if (scenario.document_lookup) details.append(element("p", "Document Q&A"));
    details.append(renderAnswer(answer));
    if (scenario.ollama) {
      const { requests, original_context_bytes: original, compact_context_bytes: compact } = scenario.ollama;
      details.append(element("p", `${scenario.model_execution} · ${requests} local requests`));
      if (original > 0) {
        const reduction = Math.round(100 * (1 - compact / original));
        details.append(element("p", `Model context: ${compact.toLocaleString()} bytes (${reduction}% smaller)`));
      }
    } else {
      details.append(element("p", `${scenario.model_execution} · ${scenario.generation_requests} Gemini generation attempts`));
    }
    if (summary) {
      details.append(element("p", `Report ${scenario.report_status} · ${summary.claim_count} claims · ${summary.calculation_count} calculations`));
      if (summary.health_gate) details.append(element("p", `Health Gate decision: ${summary.health_gate.decision}`));
    }
    const values = Object.entries(scenario.calculations).map(([name, value]) =>
      `${metrics[name] || name} ${value}${name === "current_ratio" ? "×" : "%"}`);
    if (!answer && values.length) details.append(element("p", values.join(" · ")));
    appendList(details, Object.entries(scenario.checks).map(([label, passed]) => `${passed ? "✓" : "✗"} ${label}`));
    if (scenario.retry_nodes.length) details.append(element("p", `Retried: ${scenario.retry_nodes.join(" → ")}`));
    if (summary?.issues.length) {
      const issues = element("details");
      issues.append(element("summary", `Run issues (${summary.issues.length})`));
      appendList(issues, summary.issues.map((issue) => issue.message));
      details.append(issues);
    }
  }
  if (ollama && !scenario && !benchmark) details.append(element("p", ollama.message));
  if (gemini) {
    const text = gemini.blocker === "missing_credential" ? "Configure the Gemini key in .env to check access. Zero requests sent." :
      `${gemini.metadata_requests} metadata requests · zero Gemini generation requests`;
    details.append(element("p", text));
    if (gemini.blocker && gemini.blocker !== "missing_credential") {
      details.append(element("p", providerErrors[gemini.blocker] || "Gemini metadata check could not start."));
    }
    appendList(details, gemini.models.map((model) =>
      `${model.model_id} — ${model.available ? "Accessible" : providerErrors[model.classification] || "Unavailable"}`));
    details.append(element("p", "Check project quota and billing in Google AI Studio."));
  }
  details.hidden = !details.childElementCount;
}

function renderRun(job) {
  if (job.id !== displayedRun || job.status !== displayedStatus) {
    $("run-label").textContent = job.label;
    $("run-status").textContent = statuses[job.status];
    $("run-status").className = `tag ${job.status}`;
  }
  $("log-empty").hidden = true;
  const log = $("log");
  const stickToBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 24;
  const content = (job.log_clipped ? "Showing the latest output. Download the full log below.\n\n" : "") +
    (job.log || (job.status === "running" ? "Starting test runner…" : "No terminal output recorded."));
  log.hidden = false;
  if (log.textContent !== content) {
    log.textContent = content;
    if (stickToBottom && displayedRun === job.id && job.status === "running") log.scrollTop = log.scrollHeight;
    if (displayedRun !== job.id) log.scrollTop = 0;
  }
  if (job.id === displayedRun && job.status === displayedStatus && job.status !== "running") return;
  displayedRun = job.id;
  displayedStatus = job.status;
  renderDetails(job);
  const links = $("artifacts");
  links.replaceChildren();
  if (job.status !== "running") {
    for (const name of job.artifacts) {
      const link = element("a", artifactNames[name] || name);
      link.href = `/api/runs/${job.id}/${name}`;
      links.append(link);
    }
  }
  links.hidden = !links.childElementCount;
}

function renderHistory(jobs) {
  const signature = JSON.stringify(jobs);
  if (signature === previousHistory) return;
  previousHistory = signature;
  const list = $("history-list");
  list.replaceChildren();
  if (!jobs.length) list.append(element("p", "No runs recorded yet."));
  for (const job of jobs) {
    const button = element("button");
    button.type = "button";
    button.dataset.run = job.id;
    const time = element("time", timeFormat.format(new Date(job.started_at)));
    time.dateTime = job.started_at;
    button.append(element("span", job.label, "history-label"), time, element("span", statuses[job.status], `tag ${job.status}`));
    list.append(button);
  }
}

const memoryLabels = {
  claim: "Claim", source: "Source", calculation: "Calculation", verification: "Verification",
  health_gate: "Health Gate", retry: "Retry decision", contradiction: "Contradiction",
};

function initWorkflow() {
  for (const [key, [label]] of Object.entries(workflowStages)) {
    const item = element("li");
    const tile = element("button", undefined, "workflow-stage");
    const dot = element("span", undefined, "stage-dot");
    const content = element("span");
    const status = element("small", "Waiting");
    dot.setAttribute("aria-hidden", "true");
    tile.type = "button";
    tile.setAttribute("aria-pressed", "false");
    tile.addEventListener("click", () => {
      inspectedStage = inspectedStage === key ? undefined : key;
      renderWorkflow(memoryView);
    });
    content.append(element("strong", label), status);
    tile.append(dot, content);
    item.append(tile);
    $("workflow-stages").append(item);
    workflowTiles[key] = { item, tile, status };
  }
  renderWorkflow();
}

function recordStages(view, events) {
  for (const { stage, status, duration_ms: duration = 0 } of events) {
    if (!Object.hasOwn(workflowStages, stage)) continue;
    const record = view.stages[stage] ??= { count: 0, duration: 0, status: "waiting" };
    record.status = status;
    if (status === "running") {
      view.active.push(stage);
    } else {
      const activeIndex = view.active.lastIndexOf(stage);
      if (activeIndex >= 0) view.active.splice(activeIndex, 1);
      record.count += 1;
      record.duration += duration;
      view.lastStage = stage;
    }
  }
}

function renderWorkflow(view) {
  const running = view?.status === "running";
  const active = running ? view.active.at(-1) : undefined;
  const completed = Boolean(view?.lastStage);
  const message = active ? `Active · ${workflowStages[active][0]}` :
    running ? "Waiting for the next stage…" : completed ? `Last stage · ${workflowStages[view.lastStage][0]}` :
      view ? "No workflow stages were recorded for this run." : "Start a run to follow its stages.";
  if ($("workflow-current").textContent !== message) $("workflow-current").textContent = message;
  for (const [key, { item, tile, status }] of Object.entries(workflowTiles)) {
    item.hidden = ["benchmark_prepare", "baseline"].includes(key) && view?.kind !== "apple-benchmark";
    const record = view?.stages[key];
    let phase = "waiting", label = "Waiting";
    if (active === key) [phase, label] = ["active", "Active"];
    else if (record?.status === "running") {
      [phase, label] = running ? ["waiting", "In progress"] : ["failed", "Interrupted"];
    } else if (record?.status === "failed") [phase, label] = ["failed", "Failed"];
    else if (record?.status === "done") {
      [phase, label] = key === "health_gate" && view.gate === "blocked" ? ["failed", "Blocked"] :
        ["done", record.count > 1 ? `Done ×${record.count}` : "Done"];
    } else if (!running && completed) [phase, label] = ["skipped", "Skipped"];
    tile.dataset.status = phase;
    const pressed = inspectedStage === key && !item.hidden;
    tile.setAttribute("aria-pressed", String(pressed));
    if (status.textContent !== label) status.textContent = label;
  }
  const selected = workflowTiles[inspectedStage];
  const detail = $("workflow-detail");
  detail.hidden = !selected || selected.item.hidden;
  if (!detail.hidden) {
    const record = view?.stages[inspectedStage];
    const time = record?.count ? ` Recorded time ${record.duration < 1000 ? `${Math.round(record.duration)} ms` : `${(record.duration / 1000).toFixed(1)} s`}.` : "";
    detail.textContent = `${workflowStages[inspectedStage][1]}${time}`;
  }
}

function memoryEntry({ kind, record, run_id }, showRunId) {
  let title, metadata;
  switch (kind) {
    case "claim":
      title = record.metric ? (metrics[record.metric] || record.metric.replaceAll("_", " ")) : record.claim;
      if (record.value != null && record.metric) {
        title += ` · ${record.value}`;
        if (record.currency) title += ` ${record.currency}`;
        if (record.scale > 1) title += ` × ${record.scale.toLocaleString()}`;
        if (!record.currency && record.unit) title += ` ${record.unit}`;
      }
      metadata = [record.agent, `v${record.version}`, record.period?.label, record.verification_status];
      break;
    case "source":
      title = record.title;
      metadata = [record.entity, record.source_type.replaceAll("_", " ")];
      break;
    case "calculation":
      title = `${metrics[record.operation] || record.operation} · ${record.display_value}${record.output_unit === "ratio" ? "×" : "%"}`;
      metadata = ["FinancialAgent", record.output_period?.label];
      break;
    case "verification":
      title = record.outcome;
      metadata = [record.resulting_ref.claim_id, `v${record.resulting_ref.version}`];
      break;
    case "contradiction":
      title = record.description;
      metadata = ["Critic", record.status, `v${record.version}`];
      break;
    case "retry":
      title = record.outcome;
      metadata = [record.reason];
      break;
    case "health_gate":
      title = record.result.decision;
      metadata = record.issues.map((issue) => issue.message);
      break;
  }
  const evidence = record.evidence || record.fresh_evidence || [];
  const pages = [...new Set(evidence.map((item) => item.page).filter(Boolean))];
  if (pages.length) metadata.push(`PDF p. ${pages.join(", ")}`);
  if (showRunId) metadata.push(`Memory ${run_id.slice(0, 8)}`);
  const row = element("details", undefined, "memory-entry");
  const summary = element("summary");
  summary.append(element("strong", memoryLabels[kind]), document.createTextNode(title ? ` · ${title}` : ""),
    element("span", metadata.filter(Boolean).join(" · "), "memory-meta"));
  row.append(summary, element("pre", JSON.stringify({ run_id, ...record }, null, 2)));
  return row;
}

async function refreshMemory(job) {
  if (memoryView?.id !== job.id) {
    memoryView = { id: job.id, kind: job.kind, status: job.status, cursor: 0, count: 0, stages: {}, active: [] };
    $("memory-feed").replaceChildren();
    $("memory-feed").hidden = true;
    $("memory-empty").hidden = false;
    $("memory-empty").textContent = "Loading Shared Memory…";
    $("memory-status").textContent = "Loading";
    $("memory-status").className = "tag neutral";
    renderWorkflow(memoryView);
  }
  const view = memoryView;
  if (view.finished || view.loading) return;
  view.loading = true;
  const feed = $("memory-feed");
  const status = $("memory-status");
  const empty = $("memory-empty");
  try {
    let page;
    do {
      page = await api(`/api/runs/${job.id}/memory?after=${view.cursor}`);
      if (view !== memoryView || selectedRun !== job.id) return;
      view.status = page.status;
      view.cursor = page.cursor;
      recordStages(view, page.stages || []);
      for (const entry of page.entries) {
        if (entry.kind === "health_gate") view.gate = entry.record.result.decision;
      }
      renderWorkflow(view);
      if (!page.source) {
        status.textContent = "No records";
        empty.textContent = "This run did not use Shared Memory.";
        view.finished = true;
        return;
      }
      if (page.entries.length) {
        const rows = document.createDocumentFragment();
        for (const entry of page.entries.slice().reverse()) {
          rows.append(memoryEntry(entry, job.kind === "evaluation" || job.kind === "coverage"));
        }
        const top = feed.scrollTop;
        const height = feed.scrollHeight;
        feed.prepend(rows);
        if (top > 4) feed.scrollTop = top + feed.scrollHeight - height;
        view.count += page.entries.length;
      }
      const active = page.status === "running";
      const label = active ? "Live" : page.source === "snapshot" ? "Saved snapshot" : "Recorded";
      const text = `${label} · ${view.count} ${view.count === 1 ? "entry" : "entries"}`;
      if (status.textContent !== text) status.textContent = text;
      status.className = `tag ${active ? "running" : "neutral"}`;
      feed.hidden = !view.count;
      empty.hidden = Boolean(view.count);
      empty.textContent = active ? "Waiting for the workflow to write to Shared Memory…" : "No Shared Memory entries were recorded.";
      view.finished = !active && !page.has_more;
    } while (page.has_more);
  } catch {
    if (view === memoryView && selectedRun === job.id) {
      status.textContent = "Updates unavailable · retrying";
      status.className = "tag neutral";
    }
  } finally {
    view.loading = false;
  }
}

async function loadRun(id) {
  const job = await api(`/api/runs/${id}`);
  if (selectedRun === id) {
    renderRun(job);
    await refreshMemory(job);
  }
}

async function refresh() {
  const { jobs } = await api("/api/runs");
  busy = jobs.some((job) => job.status === "running");
  disableLaunches();
  renderHistory(jobs);
  if (!selectedRun) selectedRun = jobs[0]?.id;
  if (selectedRun) await loadRun(selectedRun);
}

function showResults(force = false) {
  if (force || window.matchMedia("(max-width: 700px)").matches) {
    $("results-title").scrollIntoView({ block: "start" });
  }
}

async function startRun(payload, scroll = false) {
  const job = await api("/api/runs", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  selectedRun = job.id;
  await refresh();
  if (["sample", "apple-benchmark"].includes(payload.kind) && window.matchMedia("(max-width: 1040px)").matches) {
    $("workflow-panel").scrollIntoView({ block: "start" });
  } else {
    showResults(scroll);
  }
}

async function submit(buildPayload, scroll) {
  if (submitting || busy) return;
  notice("");
  submitting = true;
  disableLaunches();
  try {
    await startRun(await buildPayload(), scroll);
  } catch (error) {
    notice(error.message);
  } finally {
    submitting = false;
    disableLaunches();
  }
}

function readPDF(file) {
  if (file.size > 25 * 1024 * 1024) throw new Error("Upload a PDF of up to 25 MiB.");
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(",", 2)[1]);
    reader.onerror = () => reject(new Error("The PDF could not be read."));
    reader.readAsDataURL(file);
  });
}

async function scenarioPayload() {
  const payload = { kind: "sample", case: $("case").value, workflow: $("workflow").value,
    scenario: $("scenario").value, mode: $("mode").value, question: $("question").value.trim() };
  if (payload.case === "custom") {
    payload.title = $("title").value;
    payload.entity = $("entity").value;
    payload.source_url = $("source-url").value;
    payload.pdf = await readPDF($("pdf").files[0]);
  }
  if (payload.mode === "live") {
    payload.free_tier_confirmed = $("confirm-free").checked;
    payload.request_budget = $("budget").valueAsNumber;
  }
  return payload;
}

function updateNavigation() {
  const hash = location.hash || "#overview";
  for (const link of document.querySelectorAll(".sidebar nav a")) {
    if (link.hash === hash) link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  }
}

async function poll() {
  const connectionMessage = "Dashboard connection lost. Retrying…";
  try {
    if (!submitting) {
      await refresh();
      if ($("notice").textContent === connectionMessage) notice("");
    }
  } catch {
    if ($("notice").hidden) notice(connectionMessage, false);
  } finally {
    setTimeout(poll, busy ? 850 : 4000);
  }
}

async function init() {
  initWorkflow();
  try {
    renderCatalog(await api("/api/catalog"));
  } catch (error) {
    notice(error.message);
    return;
  }
  for (const id of ["case", "workflow", "scenario", "mode"]) $(id).addEventListener("change", updateForm);
  $("scenario-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submit(scenarioPayload, false);
  });
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-check], button[data-sample], button[data-run]");
    if (!button) return;
    if (button.dataset.check) submit(() => ({ kind: button.dataset.check }), true);
    if (button.dataset.sample) {
      $("case").value = button.dataset.sample;
      $("question").value = "";
      updateForm();
      $("case").focus();
      $("scenario-title").scrollIntoView({ block: "start" });
    }
    if (button.dataset.run) {
      selectedRun = button.dataset.run;
      try {
        await loadRun(selectedRun);
        showResults(true);
      } catch (error) {
        notice(error.message);
      }
    }
  });
  updateNavigation();
  window.addEventListener("hashchange", updateNavigation);
  poll();
}

init();
