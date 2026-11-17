const $ = (id) => document.getElementById(id);
const statuses = {
  passed: "Passed", failed: "Failed", running: "Running", blocked: "Blocked",
  completed: "Completed", interrupted: "Interrupted",
};
const artifactNames = {
  "report.md": "Report", "run_summary.json": "Run summary", "analysis_map.json": "Analysis map",
  "evidence.json": "Evidence & calculations", "scenario.json": "Scenario checks",
  "gemini_readiness.json": "Gemini diagnostics", "retrieval.json": "Retrieval scores",
  "results.json": "Evaluation results", "manifest.json": "Evaluation manifest",
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

function notice(message) {
  $("notice").textContent = message;
  $("notice").hidden = !message;
  if (message) $("notice").scrollIntoView({ block: "nearest" });
}

function disableLaunches() {
  for (const button of document.querySelectorAll("[data-suite], [data-check], #run-scenario")) {
    button.disabled = busy || submitting;
  }
}

function updateForm() {
  const custom = $("case").value === "custom";
  const workflow = $("workflow").value;
  const live = $("mode").value === "live";
  const scenario = $("scenario");
  for (const choice of scenario.options) {
    choice.disabled = (live && choice.value !== "clean") ||
      (workflow !== "full" && ["corrected", "persistent"].includes(choice.value)) ||
      (custom && choice.value !== "clean");
  }
  if (scenario.selectedOptions[0]?.disabled) scenario.value = "clean";
  $("scenario-hint").textContent = catalog.scenarios[scenario.value][1];
  const item = catalog.samples.find((sample) => sample.id === $("case").value);
  const fixedQuestion = scenario.value === "unsupported";
  $("question").disabled = fixedQuestion;
  $("question").placeholder = fixedQuestion ? "Assess Q2 quarterly financial performance" :
    item?.question || "Assess annual financial health, revenue growth, profitability and liquidity";
  $("custom-fields").hidden = !custom;
  for (const input of $("custom-fields").querySelectorAll("input")) {
    input.required = custom;
    input.disabled = !custom;
  }
  $("live-fields").hidden = !live;
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

function runButton(text, data, value, context) {
  const button = element("button", text, "button secondary");
  button.type = "button";
  button.dataset[data] = value;
  if (context) button.setAttribute("aria-label", `${text}: ${context}`);
  return button;
}

function renderCatalog(data) {
  catalog = data;
  $("sample-count").textContent = data.samples.filter((sample) => sample.available).length;
  for (const sample of data.samples) {
    const choice = option(sample.id, sample.entity);
    choice.disabled = !sample.available;
    $("case").append(choice);
    const actions = createCard("sample-list", sample.entity, sample.title);
    const use = runButton("Use document", "sample", sample.id, sample.entity);
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
  for (const [id, [label, description]] of Object.entries(data.suites)) {
    createCard("suite-list", label, description).append(runButton("Run suite", "suite", id, label));
  }
  for (const [id, [label, description]] of Object.entries(data.checks)) {
    createCard("evaluation-list", label, description).append(runButton("Run check", "check", id, label));
  }
  updateForm();
}

function appendList(target, entries) {
  if (!entries.length) return;
  const list = element("ul");
  for (const text of entries) list.append(element("li", text));
  target.append(list);
}

function renderDetails(job) {
  const details = $("run-details");
  details.replaceChildren();
  const scenario = job.results["scenario.json"];
  const summary = job.results["run_summary.json"];
  const gemini = job.results["gemini_readiness.json"];
  if (scenario) {
    details.append(element("p", `${scenario.model_execution} · ${scenario.generation_requests} Gemini generation attempts`));
    if (summary) {
      details.append(element("p", `Report ${scenario.report_status} · ${summary.claim_count} claims · ${summary.calculation_count} calculations`));
      if (summary.health_gate) details.append(element("p", `Health Gate decision: ${summary.health_gate.decision}`));
    }
    const values = Object.entries(scenario.calculations).map(([name, value]) =>
      `${metrics[name] || name} ${value}${name === "current_ratio" ? "×" : "%"}`);
    if (values.length) details.append(element("p", values.join(" · ")));
    appendList(details, Object.entries(scenario.checks).map(([label, passed]) => `${passed ? "✓" : "✗"} ${label}`));
    if (scenario.retry_nodes.length) details.append(element("p", `Retried: ${scenario.retry_nodes.join(" → ")}`));
    if (summary?.issues.length) {
      const issues = element("details");
      issues.append(element("summary", `Run issues (${summary.issues.length})`));
      appendList(issues, summary.issues.map((issue) => issue.message));
      details.append(issues);
    }
  }
  if (gemini) {
    const text = gemini.blocker === "missing_credential" ? "No key configured. Zero requests sent." :
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

async function loadRun(id) {
  const job = await api(`/api/runs/${id}`);
  if (selectedRun === id) renderRun(job);
}

async function refresh() {
  const { jobs, key_configured: hasKey } = await api("/api/runs");
  busy = jobs.some((job) => job.status === "running");
  disableLaunches();
  $("key-status").textContent = hasKey ? "Key configured" : "No key configured";
  $("key-heading").textContent = hasKey ? "Credential found. Run the access check." : "No Gemini key configured";
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
  showResults(scroll);
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
  try {
    if (!submitting) await refresh();
  } catch {
    $("key-status").textContent = "Dashboard connection lost";
  } finally {
    setTimeout(poll, busy ? 850 : 4000);
  }
}

async function init() {
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
    const button = event.target.closest("button[data-suite], button[data-check], button[data-sample], button[data-run]");
    if (!button) return;
    if (button.dataset.suite) submit(() => ({ kind: "suite", group: button.dataset.suite }), !button.closest("header"));
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
