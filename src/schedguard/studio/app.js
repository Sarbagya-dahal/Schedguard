/**
 * SchedLang Studio - Research Workbench Controller
 * Clean, minimal, and deeply inspectable interface for SchedLang compiler research.
 */

// Global Application State
const appState = {
  currentRunId: null,
  currentRunRecord: null,
  currentSource: "",
  currentPolicyState: "Named preset",
  pendingAiPolicy: null,
  examples: {},
  tourStep: 1,
  activeView: "view-overview",
};

// Preset Natural Language Intent Prompts
const PRESET_INTENTS = {
  web_batch: "Prioritize interactive web tasks, give batch tasks a longer time quantum, and prevent batch starvation with a maximum waiting-time requirement of 400 milliseconds.",
  strict_bad: "Web tasks have strict priority over batch with 5ms quantum. Batch tasks run at priority 1 with 20ms quantum without aging.",
  three_tier: "Real-time audio processing at priority 0 with 2ms quantum, interactive web tasks at priority 1 with 5ms quantum and 100ms aging, and background batch at priority 2 with 500ms aging.",
};

// Demonstration Guide Step Definitions
const DEMO_STEPS = [
  {
    step: 1,
    title: "1. Research Overview & Verification Foundation",
    desc: "Welcome to SchedLang Studio. Notice the quiet, academic workspace. The project achieves formal safety by construction: AI proposals are untrusted until verified by deterministic SMT solving (Z3).",
    action: () => switchView("view-overview"),
  },
  {
    step: 2,
    title: "2. The Policy Editor",
    desc: "Switch to the Policy Editor. The code canvas is prominent and uncluttered. Pre-configured benchmark policies are selectable from the toolbar.",
    action: () => {
      switchView("view-editor");
      loadExample("aging_fix");
    },
  },
  {
    step: 3,
    title: "3. Untrusted AI Proposer",
    desc: "Open the AI Proposer drawer. Researchers can describe scheduling requirements in natural language. Notice the clear UNTRUSTED PROPOSAL notice: the AI never decides acceptance.",
    action: () => {
      switchView("view-editor");
      openAiDrawer();
    },
  },
  {
    step: 4,
    title: "4. Genuine Compilation & Stage Telemetry",
    desc: "Executing 'Compile & Run' invokes the real compiler. Look at the compact stage chips: Lexer -> Parser -> Safety -> IR, with exact microsecond-precision durations.",
    action: async () => {
      closeAiDrawer();
      await executeCompileAndRun();
    },
  },
  {
    step: 5,
    title: "5. Detailed Stage Inspector",
    desc: "Open the Stage Inspector to examine real intermediate representations: normalized class tables, AST nodes, and safety diagnostics (E001-E013).",
    action: () => {
      openInspectorDrawer();
    },
  },
  {
    step: 6,
    title: "6. Formal Verification Workspace (Z3)",
    desc: "Switch to Analysis & Verification. Inspect Z3 SMT proofs over all bounded workloads. Notice the explicit distinction between our scheduling verifier and the kernel BPF verifier.",
    action: () => {
      closeInspectorDrawer();
      switchView("view-verification");
    },
  },
  {
    step: 7,
    title: "7. Starvation Counterexample & Replay",
    desc: "Switch to 'strict_starves.sched' to see strict priority starvation refuted mathematically. The solver synthesizes an adversarial workload and replays it in the simulator.",
    action: async () => {
      switchView("view-editor");
      document.getElementById("editorExampleSelect").value = "strict_starves";
      await loadExample("strict_starves");
      switchView("view-verification");
    },
  },
  {
    step: 8,
    title: "8. Single-CPU Simulator & Gantt Timeline",
    desc: "In the Workload Simulator, inspect the discrete-event dispatch Gantt chart. Hover over slices to observe wait times, queue depths, and aging promotions.",
    action: async () => {
      switchView("view-simulator");
      await runSimulation();
    },
  },
  {
    step: 9,
    title: "9. Adaptive Parameter Tuning",
    desc: "The Adaptive Tuner sweeps candidate parameter ranges (e.g. batch.aging = 50ms..400ms), evaluates each configuration with Z3, and recommends the verified safe operating point.",
    action: async () => {
      switchView("view-tuning");
      await runAdaptiveTuner();
    },
  },
  {
    step: 10,
    title: "10. Academic PDF Report & Code Explorer",
    desc: "Download a formal publication-grade PDF report documenting the run snapshot. In the Code Explorer, inspect actual compiler source files and generated sched_ext C skeletons.",
    action: () => {
      switchView("view-code");
    },
  },
];

// Document Ready Initialization
document.addEventListener("DOMContentLoaded", async () => {
  initTheme();
  initSidebar();
  initEditor();
  initDrawers();
  initDemonstrationModal();
  initCodeExplorer();
  initPhase3Workbench();
  initPhase4Workbench();

  // Load examples & recent runs
  await loadExamples();
  await loadRecentRuns();
  await loadPhase3Metrics();

  // Load default policy example into editor
  await loadExample("aging_fix");
});

function initPhase4Workbench() {
  const preflightBtn = document.getElementById("phase4PreflightBtn");
  const emitBtn = document.getElementById("phase4EmitBtn");
  if (preflightBtn) preflightBtn.addEventListener("click", loadPhase4Preflight);
  if (emitBtn) emitBtn.addEventListener("click", emitPhase4Source);
}

async function loadPhase4Preflight() {
  const output = document.getElementById("phase4PreflightOutput");
  if (!output) return;
  output.textContent = "Checking…";
  try {
    const res = await fetch("/api/phase4/preflight");
    const data = await res.json();
    output.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    output.textContent = `Preflight failed: ${err.message}`;
  }
}

async function emitPhase4Source() {
  const source = document.getElementById("mainCodeEditor")?.value?.trim();
  const output = document.getElementById("phase4CodeOutput");
  const status = document.getElementById("phase4EmitStatus");
  const badge = document.getElementById("phase4CodeStatus");
  if (!source || !output) return;
  output.textContent = "Generating…";
  try {
    const res = await fetch("/api/codegen", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source }) });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `API returned ${res.status}`);
    output.textContent = data.c_code || "No source emitted.";
    if (status) status.textContent = `${data.status_label || "EMISSION_SUCCEEDED"}. Build and load are separate stages.`;
    if (badge) { badge.textContent = data.status_label || "EMISSION_SUCCEEDED"; badge.className = "badge badge-green"; }
  } catch (err) {
    output.textContent = `Emission failed: ${err.message}`;
    if (status) status.textContent = "Emission failed; no runtime action was attempted.";
    if (badge) { badge.textContent = "FAILED"; badge.className = "badge badge-red"; }
  }
}

// ============================================================================
// 1. Theme & Sidebar Management
// ============================================================================

function initTheme() {
  const savedTheme = localStorage.getItem("schedguard_theme") || "theme-light";
  document.body.className = savedTheme;
  updateThemeButtonUI(savedTheme);

  const toggleBtn = document.getElementById("themeToggleBtn");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      const isLight = document.body.classList.contains("theme-light");
      const newTheme = isLight ? "theme-dark" : "theme-light";
      document.body.className = newTheme;
      localStorage.setItem("schedguard_theme", newTheme);
      updateThemeButtonUI(newTheme);
    });
  }
}

function updateThemeButtonUI(theme) {
  const label = document.querySelector(".theme-label");
  const icon = document.querySelector(".theme-icon");
  if (!label || !icon) return;

  if (theme === "theme-dark") {
    label.textContent = "Light Theme";
    icon.textContent = "☼";
  } else {
    label.textContent = "Dark Theme";
    icon.textContent = "☾";
  }
}

function initSidebar() {
  const sidebar = document.getElementById("sidebar");
  const toggleBtn = document.getElementById("sidebarToggleBtn");
  if (toggleBtn && sidebar) {
    toggleBtn.addEventListener("click", () => {
      sidebar.classList.toggle("collapsed");
    });
  }

  // Keyboard shortcut Ctrl+B for sidebar toggle
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") {
      e.preventDefault();
      if (sidebar) sidebar.classList.toggle("collapsed");
    }
  });

  // Nav item click binding
  const navItems = document.querySelectorAll(".nav-item");
  navItems.forEach(item => {
    item.addEventListener("click", () => {
      const viewId = item.getAttribute("data-view");
      if (viewId) switchView(viewId);
    });
  });
}

function switchView(viewId) {
  appState.activeView = viewId;

  // Update navigation items
  document.querySelectorAll(".nav-item").forEach(item => {
    if (item.getAttribute("data-view") === viewId) {
      item.classList.add("active");
    } else {
      item.classList.remove("active");
    }
  });

  // Switch view panels
  document.querySelectorAll(".view-panel").forEach(panel => {
    if (panel.id === viewId) {
      panel.classList.remove("hidden");
      panel.classList.add("active");
    } else {
      panel.classList.add("hidden");
      panel.classList.remove("active");
    }
  });

  // Dynamic view hooks
  if (viewId === "view-overview") {
    loadRecentRuns();
  } else if (viewId === "view-code") {
    ensureSourceFilesLoaded();
  } else if (viewId === "view-experiments") {
    loadPhase3Metrics();
  }
}

// Make switchView globally accessible for inline onclick links
window.switchView = switchView;

// ============================================================================
// Phase 3 workbench: real synthesis, classification/repair, and metrics APIs
// ============================================================================
function phase3Escape(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
}

function phase3Copy(text, button) {
  if (!text || text.startsWith("No ")) return;
  navigator.clipboard.writeText(text).then(() => { if (button) { const old = button.textContent; button.textContent = "Copied"; setTimeout(() => button.textContent = old, 900); } });
}

async function phase3ResponseJson(response) {
  const text = await response.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; }
  catch (_) { throw new Error(`Request failed (${response.status}); server returned a non-JSON response.`); }
  if (!response.ok) throw new Error(data.detail || data.message || data.error || `Request failed (${response.status}).`);
  return data;
}

function initPhase3Workbench() {
  document.getElementById("synthesisRunBtn")?.addEventListener("click", runPhase3Synthesis);
  document.getElementById("repairRunBtn")?.addEventListener("click", runPhase3Repair);
  document.getElementById("refreshMetricsBtn")?.addEventListener("click", loadPhase3Metrics);
  document.getElementById("synthesisCopyBtn")?.addEventListener("click", () => phase3Copy(document.getElementById("synthesisSource").textContent, document.getElementById("synthesisCopyBtn")));
  document.getElementById("repairCopyBtn")?.addEventListener("click", () => phase3Copy(document.getElementById("repairSourceOutput").textContent, document.getElementById("repairCopyBtn")));
  const editor = document.getElementById("mainCodeEditor");
  const repair = document.getElementById("repairSource");
  if (editor && repair) repair.value = editor.value;
}

async function runPhase3Synthesis() {
  const prompt = document.getElementById("synthesisPrompt")?.value.trim();
  const provider = document.getElementById("synthesisProvider")?.value || "stub";
  const status = document.getElementById("synthesisStatus");
  if (!prompt) { status.textContent = "Enter a scheduling intent first."; status.className = "phase3-status status-warning"; return; }
  status.textContent = "Generating and verifying…"; status.className = "phase3-status status-running";
  try {
    const res = await fetch("/api/synthesize", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({prompt, provider, repair:true})});
    const data = await res.json(); if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    const p = data.proposal || {};
    document.getElementById("synthesisSource").textContent = data.source || "No source generated.";
    const copy = document.getElementById("synthesisCopyBtn"); copy.disabled = !data.source;
    const intent = p.intent || {};
    const repair = data.repair;
    document.getElementById("synthesisDetails").innerHTML = `<div class="status-row"><span>Provider</span><strong>${phase3Escape(p.mode_label || p.provider || "Not recorded")}</strong></div><div class="status-row"><span>Proposal</span><strong>${phase3Escape(p.proposal_status || p.status || "NOT_RUN")}</strong></div><div class="status-row"><span>Compilation</span><strong>${phase3Escape(p.compilation_status || "NOT_RUN")}</strong></div><div class="status-row"><span>Consistency</span><strong>${phase3Escape(p.consistency_status || "NOT_RUN")}</strong></div><div class="status-row"><span>Extracted guarantees</span><strong>${phase3Escape((p.extracted_guarantees || []).join(", ") || "None")}</strong></div><div class="status-row"><span>Repair</span><strong>${repair ? (repair.success ? "VERIFIED" : "NOT_VERIFIED") : "NOT_RUN"}</strong></div><p>${phase3Escape(p.rationale || "")}</p><details><summary>Intent assumptions and limitations</summary><pre>${phase3Escape(JSON.stringify({assumptions:intent.assumptions || [], unsupported:intent.unsupported || []}, null, 2))}</pre></details>`;
    status.textContent = data.success ? "Verified policy reached." : (p.proposal_status === "UNSUPPORTED_INTENT" ? "Unsupported requirement; no policy claimed." : "No verified policy reached.");
    status.className = `phase3-status ${data.success ? "status-success" : "status-warning"}`;
  } catch (err) { status.textContent = `Synthesis failed: ${err.message}`; status.className = "phase3-status status-error"; }
}

async function runPhase3Repair() {
  const source = document.getElementById("repairSource")?.value.trim();
  const feedback = document.getElementById("repairFeedback")?.value || "heuristic";
  const status = document.getElementById("repairStatus");
  if (!source) { status.textContent = "Enter PolicyLang source first."; status.className = "phase3-status status-warning"; return; }
  status.textContent = "Classifying and repairing…"; status.className = "phase3-status status-running";
  try {
    // Keep the two CPU-bound Z3 workflows ordered. The verifier serializes
    // native Z3 calls as a safeguard, while this avoids needless contention.
    const classificationResponse = await fetch("/api/classify", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({source})});
    const classification = await phase3ResponseJson(classificationResponse);
    const repairResponse = await fetch("/api/repair", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({source, feedback})});
    const repair = await phase3ResponseJson(repairResponse);
    document.getElementById("repairClassifications").innerHTML = `<div class="status-row"><span>Overall</span><strong>${phase3Escape(classification.status)}</strong></div>` + ((classification.verdicts || []).map(v => `<div class="verdict-row"><strong class="verdict-${String(v.status).toLowerCase()}">${phase3Escape(v.status)}</strong><span>${phase3Escape(v.guarantee)}</span><small>${phase3Escape(v.replay || "")}</small></div>`).join("")) + ((classification.classifications || []).map(c => `<div class="cause-box"><strong>${phase3Escape(c.cause)}</strong><p>${phase3Escape(c.explanation)}</p><small>${phase3Escape(JSON.stringify(c.evidence || {}))}</small></div>`).join(""));
    document.getElementById("repairIterations").innerHTML = (repair.iterations || []).map(i => `<div class="verdict-row"><strong>${phase3Escape(i.status)}</strong><span>${phase3Escape(i.cause || "—")}</span><small>${phase3Escape(i.message || "")}</small></div>`).join("") || "No iterations recorded.";
    document.getElementById("repairSourceOutput").textContent = repair.source || "No repaired source.";
    document.getElementById("repairCopyBtn").disabled = !repair.source;
    status.textContent = repair.success ? "Verified repair reached." : "Repair did not reach verified status.";
    status.className = `phase3-status ${repair.success ? "status-success" : "status-warning"}`;
  } catch (err) { status.textContent = `Repair failed: ${err.message}`; status.className = "phase3-status status-error"; }
}

async function loadPhase3Metrics() {
  const status = document.getElementById("metricsStatus"); if (!status) return;
  try {
    const res = await fetch("/api/metrics"); const payload = await res.json();
    if (!res.ok || !payload.ok || !payload.data) { status.textContent = payload.message || "No recorded experiment results."; status.className = "phase3-status status-warning"; return; }
    const conditions = payload.data.conditions || {};
    const summary = document.getElementById("metricsSummary");
    const entries = Object.entries(conditions).filter(([,v]) => v && v.status === "EXECUTED");
    const first = entries[0]?.[1];
    summary.innerHTML = `<div class="metric-tile"><span>Policies</span><strong>${first?.samples ?? "Not recorded"}</strong></div><div class="metric-tile"><span>Provider</span><strong>${phase3Escape(payload.data.config?.provider || "Not recorded")}</strong></div><div class="metric-tile"><span>Success rate</span><strong>${first ? `${(first.success_rate*100).toFixed(2)}%` : "Not recorded"}</strong></div><div class="metric-tile"><span>Failure rate</span><strong>${first ? `${((1-first.success_rate)*100).toFixed(2)}%` : "Not recorded"}</strong></div>`;
    document.getElementById("metricsBody").innerHTML = Object.entries(conditions).map(([name,v]) => { if (!v || v.status !== "EXECUTED") return `<tr><td>${phase3Escape(name)}</td><td>NOT_RUN</td><td colspan="5">${phase3Escape(v?.reason || "Not recorded")}</td></tr>`; const success=v.success_rate; return `<tr><td>${phase3Escape(name)}</td><td>${phase3Escape(v.status)}</td><td>${v.samples ?? "Not recorded"}</td><td>${(success*100).toFixed(2)}%</td><td>${((1-success)*100).toFixed(2)}%</td><td>${v.mean_iterations ?? "Not recorded"}</td><td>${v.cause_accuracy == null ? "Not recorded" : `${(v.cause_accuracy*100).toFixed(2)}%`}</td></tr>`; }).join("");
    status.textContent = `Loaded recorded ${payload.phase} results.`; status.className = "phase3-status status-success";
  } catch (err) { status.textContent = `Metrics unavailable: ${err.message}`; status.className = "phase3-status status-error"; }
}

// ============================================================================
// 2. Editor & Compilation Telemetry
// ============================================================================

function initEditor() {
  const editor = document.getElementById("mainCodeEditor");
  const gutter = document.getElementById("editorLineNumbers");

  function updateLineNumbers() {
    if (!editor || !gutter) return;
    const lines = editor.value.split("\n").length;
    gutter.innerHTML = Array.from({ length: lines }, (_, i) => i + 1).join("\n");
  }

  if (editor) {
    editor.addEventListener("input", () => {
      appState.currentSource = editor.value;
      setEditorPolicyState("Custom policy — unsaved", true);
      updateLineNumbers();
    });

    // Keyboard shortcut Ctrl+Enter to compile
    editor.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        executeCompileAndRun();
      }
    });

    updateLineNumbers();
  }

  // Toolbar button listeners
  const compileBtn = document.getElementById("editorCompileBtn");
  if (compileBtn) compileBtn.addEventListener("click", executeCompileAndRun);

  const formatBtn = document.getElementById("editorFormatBtn");
  if (formatBtn) {
    formatBtn.addEventListener("click", () => {
      if (editor) {
        editor.value = editor.value.replace(/\t/g, "  ");
        updateLineNumbers();
      }
    });
  }

  const resetBtn = document.getElementById("editorResetBtn");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      const select = document.getElementById("editorExampleSelect");
      if (select) loadExample(select.value);
    });
  }

  const exampleSelect = document.getElementById("editorExampleSelect");
  if (exampleSelect) {
    exampleSelect.addEventListener("change", (e) => {
      loadExample(e.target.value);
    });
  }

  // PDF Download buttons
  const footerPdfBtn = document.getElementById("footerDownloadPdfBtn");
  if (footerPdfBtn) footerPdfBtn.addEventListener("click", downloadCurrentPdf);

  const verifPdfBtn = document.getElementById("verifDownloadPdfBtn");
  if (verifPdfBtn) verifPdfBtn.addEventListener("click", downloadCurrentPdf);

  // Verification Recheck button
  const recheckBtn = document.getElementById("recheckVerifBtn");
  if (recheckBtn) recheckBtn.addEventListener("click", executeCompileAndRun);

  // Overview history refresh button
  const refreshRunsBtn = document.getElementById("refreshRunsBtn");
  if (refreshRunsBtn) refreshRunsBtn.addEventListener("click", loadRecentRuns);
}

async function loadExamples() {
  try {
    const res = await fetch("/api/examples");
    const data = await res.json();
    appState.examples = {};
    (data.examples || []).forEach(ex => {
      appState.examples[ex.name] = ex;
    });
  } catch (err) {
    console.error("Failed to load examples", err);
  }
}

async function loadExample(name) {
  if (appState.examples[name]) {
    const ex = appState.examples[name];
    const editor = document.getElementById("mainCodeEditor");
    if (editor) {
      editor.value = ex.code;
      appState.currentSource = ex.code;
      setEditorPolicyState(`Named preset — ${ex.filename}`, false, name);
      const gutter = document.getElementById("editorLineNumbers");
      if (gutter) {
        const lines = ex.code.split("\n").length;
        gutter.innerHTML = Array.from({ length: lines }, (_, i) => i + 1).join("\n");
      }
      await executeCompileAndRun();
    }
  }
}

function setEditorPolicyState(label, clearPreset = false, presetName = null) {
  appState.currentPolicyState = label;
  const select = document.getElementById("editorExampleSelect");
  if (select) {
    if (presetName !== null) select.value = presetName;
    else if (clearPreset) select.selectedIndex = -1;
  }
  const state = document.getElementById("editorPolicyState");
  if (state) state.textContent = label;
}

// Execute Full Pipeline Run (/api/run)
async function executeCompileAndRun() {
  const editor = document.getElementById("mainCodeEditor");
  if (!editor) return;
  const code = editor.value.trim();
  if (!code) return;

  const statusText = document.getElementById("editorStatusText");
  const compileBtn = document.getElementById("editorCompileBtn");

  if (statusText) statusText.textContent = "Compiling & executing Z3 analysis...";
  if (compileBtn) compileBtn.disabled = true;

  // Reset stage chips to pending
  setStageChip("stgLexer", "pending");
  setStageChip("stgParser", "pending");
  setStageChip("stgSafety", "pending");
  setStageChip("stgIR", "pending");

  let runRecord;
  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: code, replay: true }),
    });
    if (!res.ok) throw new Error(`API returned ${res.status}`);
    runRecord = await res.json();
  } catch (err) {
    // This is a request/API failure, not a compiler failure. A compiler failure
    // is represented by compile.ok=false in an otherwise valid run record.
    console.error("Run request failed:", err);
    if (statusText) statusText.textContent = "Unable to execute compilation request.";
    if (compileBtn) compileBtn.disabled = false;
    return;
  }

  try {
    renderRunRecord(runRecord);

    if (statusText) {
      const compilation = runRecord.compile || {};
      if (compilation.ok) {
        const dur = (compilation.total_duration_ms || 0).toFixed(2);
        statusText.innerHTML = `<strong>Compiled successfully</strong> in ${dur}ms &mdash; Run ID: <code>${runRecord.run_id}</code>`;
      } else {
        statusText.innerHTML = `<span class="text-red"><strong>Compilation failed:</strong> ${escapeHtml(compilation.summary || "Errors detected")}</span>`;
      }
    }
  } catch (err) {
    // The run is real and may still be downloadable; only its presentation failed.
    console.error("Run result rendering failed:", err);
    if (statusText) statusText.textContent = "Run completed, but results could not be rendered.";
  } finally {
    if (compileBtn) compileBtn.disabled = false;
  }
}

const STAGE_CHIP_IDS = {
  "Lexical Analysis": "stgLexer",
  "Parsing & AST": "stgParser",
  "Safety Pass": "stgSafety",
  "IR Lowering": "stgIR",
};

function renderRunRecord(runRecord) {
  appState.currentRunId = runRecord.run_id;
  appState.currentRunRecord = runRecord;
  renderStageTelemetry(runRecord.compile?.stages, runRecord.compile);
  renderInspectorDrawer(runRecord);
  renderVerificationView(runRecord);
  renderSimulatorView(runRecord);
  renderEbpfSkeleton(runRecord.codegen?.c_code);

  const footerPdfBtn = document.getElementById("footerDownloadPdfBtn");
  const verifPdfBtn = document.getElementById("verifDownloadPdfBtn");
  if (footerPdfBtn) footerPdfBtn.disabled = false;
  if (verifPdfBtn) verifPdfBtn.disabled = false;
}

function setStageChip(chipId, status, durationMs = null) {
  const chip = document.getElementById(chipId);
  if (!chip) return;

  chip.className = `stage-chip ${status}`;
  if (durationMs !== null) {
    chip.title = `${chip.textContent}: ${status.toUpperCase()} in ${durationMs.toFixed(2)}ms`;
  }
}

function renderStageTelemetry(stages, compilation) {
  let totalMs = 0;
  (stages || []).forEach(stg => {
    totalMs += stg.duration_ms || 0;
    const chipId = STAGE_CHIP_IDS[stg.name];
    if (!chipId) return;
    const status = (stg.status || "pending").toLowerCase();
    setStageChip(chipId, status === "skipped" ? "pending" : status, stg.duration_ms);
  });

  const badge = document.getElementById("compilerDurationBadge");
  if (badge) {
    badge.textContent = `${(compilation?.total_duration_ms ?? totalMs).toFixed(2)} ms`;
  }
}

function renderInspectorDrawer(runRecord) {
  const state = document.getElementById("inspectorRunState");
  const current = document.getElementById("mainCodeEditor")?.value?.trim() || appState.currentSource || "";
  const snapshot = runRecord.source_code || "";
  const stale = Boolean(snapshot && current && snapshot !== current);
  if (state) {
    state.className = `inspector-run-state${stale ? " stale" : ""}`;
    state.textContent = stale
      ? "Stale result: the editor source changed after this compile. Recompile to inspect current AST and IR."
      : `Run ${runRecord.run_id || "current"} · source snapshot ${snapshot ? "aligned" : "unavailable"}`;
  }
  // 1. Stages List with durations and errors
  const list = document.getElementById("inspectorStagesList");
  if (list) {
    list.innerHTML = "";
    (runRecord.compile?.stages || []).forEach(stg => {
      const item = document.createElement("div");
      item.className = "stage-detail-item";
      const normalizedStatus = (stg.status || "").toLowerCase();
      const statusBadgeClass = normalizedStatus === "completed" ? "badge-green" : (normalizedStatus === "failed" ? "badge-red" : "badge-neutral");
      
      let errorHtml = "";
      if (stg.error) {
        errorHtml = `<div class="stage-error-msg">${escapeHtml(stg.error)}</div>`;
      }

      item.innerHTML = `
        <div class="stage-top-row">
          <span class="stage-name-bold">${stg.name.toUpperCase()} STAGE</span>
          <span class="badge ${statusBadgeClass}">${normalizedStatus.toUpperCase()} (${(stg.duration_ms || 0).toFixed(2)} ms)</span>
        </div>
        ${errorHtml}
      `;
      list.appendChild(item);
    });
  }

  // 2. Normalized IR tab: show actual lowered fields, not an AST-shaped dump.
  const irView = document.getElementById("inspectorIrView");
  if (irView) {
    const ir = runRecord.compile?.ir;
    if (stale) {
      irView.innerHTML = '<div class="empty-state">The editor source changed after this run. Recompile before inspecting normalized IR.</div>';
    } else if (!ir) {
      irView.innerHTML = '<div class="empty-state">No lowered IR was produced because compilation did not reach IR lowering.</div>';
    } else {
      const classes = (ir.classes || []).map(c => `<tr><td>${c.idx}</td><td>${escapeHtml(c.name)}</td><td>${c.prio}</td><td>${c.quantum_ms} ms</td><td>${c.aging_ms ?? 0} ms</td><td>${escapeHtml(c.kind || "-")}</td></tr>`).join("");
      const guarantees = (ir.guarantees || []).map(g => `<li><code>${escapeHtml(g.pretty || g.kind)}</code> → ${escapeHtml(g.cls_name || "?")} = ${g.value}</li>`).join("") || "<li>None declared</li>";
      const adaptations = (ir.adaptations || []).map(a => `<li><code>${escapeHtml(a.cls_name || "?")}.${escapeHtml(a.param)}</code> ∈ [${a.min_val}, ${a.max_val}]</li>`).join("") || "<li>None declared</li>";
      irView.innerHTML = `<div class="ir-caption">Lowered fixed-size representation consumed by analysis and code generation.</div>
        <div class="ir-meta"><strong>${escapeHtml(ir.name)}</strong> · max_tasks=${ir.max_tasks}</div>
        <table class="data-table compact-table"><thead><tr><th>ID</th><th>Class</th><th>Priority</th><th>Quantum</th><th>Aging</th><th>Kind</th></tr></thead><tbody>${classes}</tbody></table>
        <div class="ir-section"><strong>Guarantees</strong><ul>${guarantees}</ul></div>
        <div class="ir-section"><strong>Adaptations</strong><ul>${adaptations}</ul></div>
        <details class="ir-raw"><summary>Raw serialized IR</summary><pre>${escapeHtml(JSON.stringify(ir, null, 2))}</pre></details>`;
    }
  }

  // 3. AST tab: render the parser's AST, never a reconstruction from IR.
  const astTree = document.getElementById("inspectorAstTree");
  const astCode = document.getElementById("inspectorAstCode");
  if (astTree) {
    astTree.innerHTML = stale
      ? '<div class="empty-state">The editor source changed after this run. Recompile before inspecting the AST.</div>'
      : (runRecord.compile?.ast ? renderAstTree(runRecord.compile.ast) : '<div class="empty-state">No AST was produced because parsing did not complete.</div>');
  }
  if (astCode) {
    astCode.textContent = runRecord.compile?.ast
      ? JSON.stringify(runRecord.compile.ast, null, 2)
      : "No AST was produced because parsing did not complete.";
  }

  // 4. Diagnostics tab
  const diagsList = document.getElementById("inspectorDiagsList");
  if (diagsList) {
    diagsList.innerHTML = "";
    const compile = runRecord.compile;
    const diags = compile?.diagnostics || [];
    if (stale) {
      diagsList.innerHTML = '<div class="diag-warning"><strong>Compilation result is stale.</strong> Recompile the current source to obtain diagnostics for this editor snapshot.</div>';
    } else if (!compile) {
      diagsList.innerHTML = '<div class="empty-state">Diagnostics are not available yet. Compile the current policy to inspect compiler results.</div>';
    } else if (compile.ok && diags.length === 0) {
      const analysis = runRecord.check?.analysis_status === "COMPLETED"
        ? "Guarantee analysis ran separately; its verdicts are shown in the Verification workspace."
        : "Guarantee analysis has not run.";
      diagsList.innerHTML = `<div class="diag-success"><strong>Compilation succeeded.</strong><br>Compilation succeeded. No compiler or semantic diagnostics were issued.<br><span>${analysis}</span></div>`;
    } else {
      if (!compile.ok) diagsList.innerHTML = '<div class="diag-failure"><strong>Compilation failed.</strong> The following compiler diagnostics prevented a valid lowered policy:</div>';
      diags.forEach(d => {
        const item = document.createElement("div");
        item.className = `diag-item ${d.stage || "compiler"}`;
        item.textContent = `[${d.code}] ${d.stage || "compiler"} · Line ${d.line || 0}${d.col ? `, Column ${d.col}` : ""}: ${d.message}`;
        diagsList.appendChild(item);
      });
      if (!diags.length) diagsList.innerHTML += '<div class="empty-state">Compilation failed without structured diagnostics.</div>';
    }
  }
}

function renderAstTree(value, label = "PolicyAST") {
  if (value === null || value === undefined) return "";
  if (typeof value !== "object") return `<span class="ast-value">${escapeHtml(String(value))}</span>`;
  const children = Object.entries(value).map(([key, child]) => {
    if (Array.isArray(child)) return `<details class="ast-node" open><summary>${escapeHtml(key)} <span class="ast-count">${child.length}</span></summary>${child.map((item, i) => `<div class="ast-array-item"><span class="ast-key">${i}</span>${renderAstTree(item, key)}</div>`).join("")}</details>`;
    if (child && typeof child === "object") return `<details class="ast-node" open><summary>${escapeHtml(key)}</summary>${renderAstTree(child, key)}</details>`;
    return `<div class="ast-attribute"><span class="ast-key">${escapeHtml(key)}</span><span>${renderAstTree(child, key)}</span></div>`;
  }).join("");
  return `<div class="ast-object"><div class="ast-label">${escapeHtml(label)}</div>${children}</div>`;
}

// Download PDF Report
function downloadCurrentPdf() {
  if (!appState.currentRunId) {
    alert("Please compile and run a policy before downloading the report.");
    return;
  }
  window.open(`/api/run/${appState.currentRunId}/pdf`, "_blank");
}

// ============================================================================
// 3. Drawers: AI Assistance & Inspector
// ============================================================================

function initDrawers() {
  // AI Drawer toggles
  const toggleAiBtn = document.getElementById("toggleAiPanelBtn");
  const closeAiBtn = document.getElementById("closeAiDrawerBtn");
  if (toggleAiBtn) toggleAiBtn.addEventListener("click", toggleAiDrawer);
  if (closeAiBtn) closeAiBtn.addEventListener("click", closeAiDrawer);

  // Inspector Drawer toggles
  const toggleInspectorBtn = document.getElementById("toggleInspectorBtn");
  const closeInspectorBtn = document.getElementById("closeInspectorBtn");
  if (toggleInspectorBtn) toggleInspectorBtn.addEventListener("click", toggleInspectorDrawer);
  if (closeInspectorBtn) closeInspectorBtn.addEventListener("click", closeInspectorDrawer);

  // Inspector Subtabs
  const subtabBtns = document.querySelectorAll(".subtab-btn");
  subtabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      subtabBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const targetSubtab = btn.getAttribute("data-subtab");
      document.querySelectorAll(".subtab-content").forEach(content => {
        if (content.id === targetSubtab) {
          content.classList.remove("hidden");
          content.classList.add("active");
        } else {
          content.classList.add("hidden");
          content.classList.remove("active");
        }
      });
    });
  });

  // AI Generation Button
  const aiGenerateBtn = document.getElementById("aiGenerateBtn");
  if (aiGenerateBtn) aiGenerateBtn.addEventListener("click", handleAiGeneratePolicy);

  // AI Insert into Editor Button
  const aiApplyBtn = document.getElementById("aiApplyToEditorBtn");
  if (aiApplyBtn) {
    aiApplyBtn.addEventListener("click", () => {
      if (appState.pendingAiPolicy) {
        const editor = document.getElementById("mainCodeEditor");
        if (editor) {
          editor.value = appState.pendingAiPolicy;
          appState.currentSource = appState.pendingAiPolicy;
          setEditorPolicyState("AI-generated policy — unsaved", true);
          const gutter = document.getElementById("editorLineNumbers");
          if (gutter) {
            const lines = appState.pendingAiPolicy.split("\n").length;
            gutter.innerHTML = Array.from({ length: lines }, (_, i) => i + 1).join("\n");
          }
          closeAiDrawer();
          executeCompileAndRun();
        }
      }
    });
  }
}

function toggleAiDrawer() {
  const drawer = document.getElementById("aiDrawer");
  if (drawer) {
    drawer.classList.toggle("hidden");
    if (!drawer.classList.contains("hidden")) {
      closeInspectorDrawer();
    }
  }
}

function openAiDrawer() {
  const drawer = document.getElementById("aiDrawer");
  if (drawer) {
    drawer.classList.remove("hidden");
    closeInspectorDrawer();
  }
}

function closeAiDrawer() {
  const drawer = document.getElementById("aiDrawer");
  if (drawer) drawer.classList.add("hidden");
}

function toggleInspectorDrawer() {
  const drawer = document.getElementById("inspectorDrawer");
  if (drawer) {
    drawer.classList.toggle("hidden");
    if (!drawer.classList.contains("hidden")) {
      closeAiDrawer();
    }
  }
}

function openInspectorDrawer() {
  const drawer = document.getElementById("inspectorDrawer");
  if (drawer) {
    drawer.classList.remove("hidden");
    closeAiDrawer();
  }
}

function closeInspectorDrawer() {
  const drawer = document.getElementById("inspectorDrawer");
  if (drawer) drawer.classList.add("hidden");
}

async function handleAiGeneratePolicy() {
  const promptText = document.getElementById("aiPromptTextarea")?.value?.trim();
  if (!promptText) return;
  appState.pendingAiPolicy = null;
  const applyBtn = document.getElementById("aiApplyToEditorBtn");
  if (applyBtn) applyBtn.disabled = true;

  const btn = document.getElementById("aiGenerateBtn");
  if (btn) {
    btn.textContent = "Synthesizing...";
    btn.disabled = true;
  }

  const providerRadio = document.querySelector('input[name="aiProviderRadio"]:checked');
  const provider = providerRadio ? providerRadio.value : "rules";

  try {
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: promptText, provider: provider }),
    });

    if (!res.ok) throw new Error(`API returned ${res.status}`);
    const data = await res.json();
    const usable = (data.proposal_status === "PROPOSAL_GENERATED" || data.status === "PROPOSAL_GENERATED" || data.status === "UNTRUSTED_PROPOSAL") &&
      data.consistency_status === "MATCH" && Boolean(data.source_code);
    appState.pendingAiPolicy = usable ? data.source_code : null;

    const resultBox = document.getElementById("aiProposalResult");
    const badge = document.getElementById("aiResultEngineBadge");
    const rationale = document.getElementById("aiResultRationale");

    if (resultBox && badge && rationale) {
      badge.textContent = `${data.mode_label || "Rule Engine"} · ${data.status || "UNKNOWN"}`;
      rationale.textContent = data.rationale || "No rationale provided.";
      resultBox.classList.remove("hidden");
    }
    if (applyBtn) applyBtn.disabled = !usable;

  } catch (err) {
    console.error("AI generation failed", err);
    alert("AI proposal generation failed: " + err.message);
  } finally {
    if (btn) {
      btn.textContent = "Generate SchedLang Proposal";
      btn.disabled = false;
    }
  }
}

// ============================================================================
// 4. Analysis & Verification Workspace
// ============================================================================

function renderVerificationView(runRecord) {
  const banner = document.getElementById("overallVerdictBanner");
  const badge = document.getElementById("verdictBadgeText");
  const title = document.getElementById("verdictBannerTitle");
  const desc = document.getElementById("verdictBannerDesc");
  const cardsContainer = document.getElementById("verificationCardsContainer");
  const factsBody = document.getElementById("provableFactsBody");

  if (!banner || !badge || !title || !desc || !cardsContainer || !factsBody) return;

  const verif = runRecord.check || {};
  const verdicts = verif.verdicts || [];
  const aggregate = verif.aggregate || { status: verdicts.length ? "NOT_RUN" : "NO_GUARANTEES", summary: "" };
  const overall = aggregate.status;
  const displayOverall = { NO_GUARANTEES: "NO GUARANTEES", NOT_RUN: "NOT RUN", INCONCLUSIVE: "INCONCLUSIVE" }[overall] || overall;

  // 1. Overall Banner
  banner.className = `verdict-banner-card ${overall.toLowerCase()}`;
  badge.textContent = displayOverall;

  if (!runRecord.compile?.ok) {
    title.textContent = "Compilation Issue";
    desc.textContent = runRecord.compile?.summary || "Fix errors to run formal verification.";
  } else if (overall === "VERIFIED") {
    title.textContent = "All Formal Guarantees Mathematically Proven Safe";
    desc.textContent = "Z3 SMT solver proved starvation freedom and/or minimum share bounds over all bounded static workloads.";
  } else if (overall === "VIOLATED") {
    title.textContent = "Formal Guarantee Violation Refuted by Z3";
    desc.textContent = "The solver synthesized a concrete counterexample workload causing starvation, confirmed via discrete simulator replay.";
  } else if (overall === "INCONCLUSIVE") {
    title.textContent = "Verifier Inconclusive";
    desc.textContent = aggregate.summary || "One or more guarantees are UNKNOWN; no conclusive violation was established.";
  } else if (overall === "NO_GUARANTEES") {
    title.textContent = "No Guarantees Declared";
    desc.textContent = "The policy compiled successfully but does not declare a formal guarantee to analyze.";
  } else if (overall === "NOT_RUN") {
    title.textContent = "Guarantee Analysis Not Run";
    desc.textContent = "Guarantees are declared, but no analyzer result is recorded for this run.";
  } else if (overall === "ERROR") {
    title.textContent = "Guarantee Analysis Error";
    desc.textContent = aggregate.error || "The guarantee analyzer could not complete.";
  } else {
    title.textContent = "Verification Status Unavailable";
    desc.textContent = aggregate.summary || "No verification outcome was recorded.";
  }

  // 2. Individual Guarantee Cards
  cardsContainer.innerHTML = "";
  if (verdicts.length === 0) {
    cardsContainer.innerHTML = aggregate.status === "NO_GUARANTEES"
      ? '<div class="empty-state-box">Policy declares no formal guarantees. Add <code>guarantee no_starvation</code> or <code>guarantee min_share</code> in the editor.</div>'
      : '<div class="empty-state-box">Guarantee results are not available for this run.</div>';
  } else {
    verdicts.forEach(v => {
      const card = document.createElement("div");
      const statusLower = (v.status || "unknown").toLowerCase();
      card.className = `guarantee-card ${statusLower}`;

      const statusBadgeClass = v.status === "VERIFIED" ? "badge-green" : (v.status === "VIOLATED" ? "badge-red" : "badge-amber");

      let counterexampleHtml = "";
      if (v.counterexample) {
        const counts = Object.entries(v.counterexample).map(([c, n]) => `${c}: ${n}`).join(", ");
        const evidenceLabel = v.evidence === "confirmed_replay" ? "Confirmed replay workload:" : "Solver candidate workload (not confirmed):";
        counterexampleHtml = `
          <div class="counterexample-card">
            <strong>${evidenceLabel}</strong> { ${counts} }
          </div>
        `;
      }

      let replayHtml = "";
      if (v.replay) {
        const prefix = v.evidence === "confirmed_replay" ? "Confirmed simulator replay:" : "Replay diagnostic:";
        replayHtml = `<div class="replay-evidence"><strong>${prefix}</strong> ${escapeHtml(v.replay)}</div>`;
      }

      card.innerHTML = `
        <div class="card-header-clean flex-between">
          <div>
            <span class="guarantee-name">${escapeHtml(v.guarantee)}</span>
            <span class="guarantee-meta">Class: <strong>${escapeHtml(v.class_name || "")}</strong> | Solver: Z3 linear integer arithmetic</span>
          </div>
          <div>
            <span class="badge ${statusBadgeClass}">${v.status}</span>
            <span class="latency-text">${(v.elapsed_ms || 0).toFixed(1)} ms</span>
          </div>
        </div>
        ${counterexampleHtml}
        ${replayHtml}
      `;
      cardsContainer.appendChild(card);
    });
  }

  // 3. Provable Facts Table
  factsBody.innerHTML = "";
  const facts = runRecord.analyze?.facts || {};
  if (Object.keys(facts).length === 0) {
    factsBody.innerHTML = '<tr><td colspan="6" class="empty-cell">No class facts available.</td></tr>';
  } else {
    for (const [name, f] of Object.entries(facts)) {
      const tr = document.createElement("tr");
      const waitStr = f.tightest_wait_ms === null ? '<strong class="text-red">UNBOUNDED (INF)</strong>' : `<strong>${f.tightest_wait_ms} ms</strong>`;
      const agingStr = f.aging_ms ? `${f.aging_ms} ms` : "None (0)";

      tr.innerHTML = `
        <td><strong>${escapeHtml(name)}</strong></td>
        <td>Tier ${f.prio}</td>
        <td>${f.quantum_ms} ms</td>
        <td>${agingStr}</td>
        <td>${waitStr}</td>
        <td><strong>${f.guaranteed_min_share_pct}%</strong></td>
      `;
      factsBody.appendChild(tr);
    }
  }
}

// ============================================================================
// 5. Workload Simulator Workspace
// ============================================================================

function renderSimulatorView(runRecord) {
  const sim = runRecord.simulate || {};
  renderGanttChart(sim.timeline, "simGanttTimeline", {
    horizonMs: sim.horizon_ms,
    configuredHorizonMs: sim.configured_horizon_ms,
    overview: sim.overview,
    traceTotalEvents: sim.trace_total_events,
    knownClasses: Object.keys(sim.per_class || {}),
    traceTruncated: sim.trace_truncated,
    traceLimit: sim.trace_limit,
    taskCounts: sim.task_counts,
  });
  renderDispatchDetails(sim.timeline, sim.trace_truncated);
  renderSimMetricsTable(sim.per_class, "simMetricsBody");
}

function renderGanttChart(timeline, containerId, options = {}) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = "";

  const events = timeline || [];
  const overview = options.overview?.buckets || [];
  const classes = options.knownClasses || [...new Set(events.map(ev => ev.class_name))];
  if (events.length === 0 && classes.length === 0) {
    container.innerHTML = '<div class="empty-state">No dispatch events recorded in the available trace.</div>';
    return;
  }

  const horizon = Math.max(1, options.configuredHorizonMs || options.horizonMs || options.overview?.end_ms || Math.max(...events.map(ev => ev.end_ms || 0), 1));
  const axis = document.createElement("div");
  axis.className = "timeline-axis";
  [0, 25, 50, 75, 100].forEach(percent => {
    const tick = document.createElement("span");
    tick.className = "timeline-tick";
    tick.style.left = `${percent}%`;
    tick.textContent = `${Math.round(horizon * percent / 100)} ms`;
    axis.appendChild(tick);
  });
  container.appendChild(axis);
  const row = document.createElement("div");
  row.className = "timeline-cpu-row";
  const label = document.createElement("div");
  label.className = "timeline-lane-label";
  label.textContent = "CPU";
  const track = document.createElement("div");
  track.className = "timeline-lane-track timeline-cpu-track";
  const tooltip = document.getElementById("simTooltip");
  const segments = [];
  if (!options.traceTruncated && events.length) {
    events.forEach(ev => {
      const previous = segments[segments.length - 1];
      if (previous && previous.class_name === ev.class_name && previous.end_ms === ev.start_ms) {
        previous.end_ms = ev.end_ms;
        previous.duration_ms += ev.duration_ms || 0;
        previous.events.push(ev);
      } else segments.push({ ...ev, events: [ev] });
    });
  } else {
    // The overview buckets preserve full-horizon CPU totals but not dispatch order.
    // Render them as explicitly aggregated segments rather than pretending they are exact events.
    overview.forEach(bucket => {
      const span = Math.max(0, bucket.end_ms - bucket.start_ms);
      let cursor = bucket.start_ms;
      Object.entries(bucket.cpu_ms || {}).forEach(([className, cpuMs]) => {
        const duration = Number(cpuMs) || 0;
        if (!duration) return;
        segments.push({ class_name: className, start_ms: cursor, end_ms: cursor + duration, duration_ms: duration, aggregated: true, events: [] });
        cursor += duration;
      });
      if (cursor < bucket.end_ms && span && !Object.values(bucket.cpu_ms || {}).some(Boolean)) {
        segments.push({ class_name: "idle", start_ms: bucket.start_ms, end_ms: bucket.end_ms, duration_ms: span, aggregated: true, events: [] });
      }
    });
  }
  segments.forEach(segment => {
    const block = document.createElement("div");
    const clsName = (segment.class_name || "default").toLowerCase();
    block.className = `timeline-block ${clsName} ${segment.boosted ? "boosted" : ""}`;
    block.style.left = `${Math.max(0, segment.start_ms / horizon * 100)}%`;
    block.style.width = `${Math.max(0, (segment.end_ms - segment.start_ms) / horizon * 100)}%`;
    block.setAttribute("aria-label", `${segment.class_name}, ${segment.start_ms} to ${segment.end_ms} milliseconds`);
    const detail = segment.aggregated ? `${segment.class_name}: aggregated CPU service from ${segment.start_ms}ms to ${segment.end_ms}ms` : `${segment.class_name}: ${segment.start_ms}ms to ${segment.end_ms}ms (${segment.duration_ms}ms)${segment.events.length > 1 ? `, ${segment.events.length} dispatches` : ""}`;
    block.title = detail;
    if (tooltip && !segment.aggregated) {
      block.addEventListener("mouseenter", () => {
        const ev = segment.events[0];
        tooltip.classList.remove("hidden");
        tooltip.innerHTML = `<strong>${escapeHtml(segment.class_name)}</strong><br>Execution: ${segment.start_ms}ms &rarr; ${segment.end_ms}ms (${segment.duration_ms}ms)<br>${ev.task_id === undefined ? "" : `Task: #${ev.task_id}<br>`}Observed wait: ${ev.wait_ms ?? "not recorded"}ms${ev.prio === undefined ? "" : `<br>Priority: ${ev.prio}`}${ev.boosted ? "<br><strong>Aging promotion</strong>" : ""}`;
      });
      block.addEventListener("mousemove", e => { tooltip.style.left = `${e.clientX + 14}px`; tooltip.style.top = `${e.clientY + 14}px`; });
      block.addEventListener("mouseleave", () => tooltip.classList.add("hidden"));
    }
    track.appendChild(block);
  });
  row.append(label, track);
  container.appendChild(row);
  const disclosure = document.getElementById("simTimelineDisclosure");
  if (disclosure) disclosure.textContent = options.traceTruncated
    ? `CPU track covers the complete ${horizon} ms horizon. Colored intervals are time-bucket aggregates; detail inspection contains ${events.length} of ${options.traceTotalEvents || events.length} dispatches.`
    : `CPU track covers the complete ${horizon} ms horizon (${events.length} dispatches, grouped only when consecutive).`;
}

function renderDispatchDetails(timeline, truncated) {
  const body = document.getElementById("simDispatchBody");
  if (!body) return;
  body.innerHTML = "";
  if (!timeline || timeline.length === 0) {
    body.innerHTML = '<tr><td colspan="6" class="empty-cell">No dispatch events recorded.</td></tr>';
    return;
  }
  timeline.forEach(ev => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${ev.start_ms}&ndash;${ev.end_ms} ms</td><td>${escapeHtml(ev.class_name)}</td><td>#${ev.task_id}</td><td>${ev.duration_ms} ms</td><td>${ev.wait_ms} ms</td><td>${escapeHtml(JSON.stringify(ev.queue_sizes || {}))}</td>`;
    body.appendChild(tr);
  });
}

function renderSimMetricsTable(perClass, tbodyId) {
  const tbody = document.getElementById(tbodyId);
  if (!tbody) return;
  tbody.innerHTML = "";

  if (!perClass || Object.keys(perClass).length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-cell">No telemetry recorded.</td></tr>';
    return;
  }

  for (const [name, stats] of Object.entries(perClass)) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${escapeHtml(name)}</strong></td>
      <td>${stats.cpu_ms} ms</td>
      <td><strong>${stats.share_pct}%</strong></td>
      <td><strong>${stats.max_wait_ms} ms</strong></td>
      <td>${stats.dispatches}</td>
    `;
    tbody.appendChild(tr);
  }
}

// Simulator execution button listeners
document.addEventListener("DOMContentLoaded", () => {
  const simRunBtn = document.getElementById("simRunBtn");
  if (simRunBtn) {
    simRunBtn.addEventListener("click", runSimulation);
  }

  const compareBtn = document.getElementById("simCompareBtn");
  if (compareBtn) {
    compareBtn.addEventListener("click", runDifferentialComparison);
  }
});

async function runSimulation() {
  const editor = document.getElementById("mainCodeEditor");
  if (!editor) return;
  const code = editor.value.trim();
  if (!code) return;

  const preset = document.getElementById("simWorkloadSelect")?.value || "web_batch";
  const availableClasses = (appState.currentRunRecord?.compile?.ir?.classes || []).map(c => c.name);
  let workload = null;
  const requested = preset === "heavy_web"
    ? { web: 8, batch: 2 }
    : (preset === "single_batch" ? { web: 2, batch: 1 } : { web: 4, batch: 4 });
  if (availableClasses.length > 0) {
    const tasks = availableClasses.map(name => ({ class: name, count: requested[name] || 2 }));
    workload = { tasks };
  }

  try {
    const res = await fetch("/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source: code,
        workload: workload,
        horizon_ms: 10000,
        record_trace: true,
        max_trace_events: 1000,
      }),
    });
    const data = await res.json();
    renderGanttChart(data.timeline, "simGanttTimeline", {
      horizonMs: data.horizon_ms,
      configuredHorizonMs: data.configured_horizon_ms,
      overview: data.overview,
      traceTotalEvents: data.trace_total_events,
      knownClasses: Object.keys(data.per_class || {}),
      traceTruncated: data.trace_truncated,
      traceLimit: data.trace_limit,
      taskCounts: data.task_counts,
    });
    renderDispatchDetails(data.timeline, data.trace_truncated);
    renderSimMetricsTable(data.per_class, "simMetricsBody");
  } catch (err) {
    console.error("Simulation request error", err);
  }
}

async function runDifferentialComparison() {
  const strictCode = appState.examples["strict_starves"]?.code || "";
  const agingCode = appState.examples["aging_fix"]?.code || "";
  if (!strictCode || !agingCode) return;

  try {
    const res = await fetch("/api/compare_sim", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        policy_a: strictCode,
        policy_b: agingCode,
        workload: { tasks: [{ class: "web", count: 4 }, { class: "batch", count: 4 }] },
        horizon_ms: 10000,
      }),
    });

    const data = await res.json();
    renderGanttChart(data.policy_a.timeline, "compTimelineA", {
      horizonMs: data.policy_a.horizon_ms || 10000,
      configuredHorizonMs: data.policy_a.configured_horizon_ms,
      overview: data.policy_a.overview,
      traceTotalEvents: data.policy_a.trace_total_events,
      knownClasses: Object.keys(data.policy_a.per_class || {}),
      traceTruncated: data.policy_a.trace_truncated,
      traceLimit: data.policy_a.trace_limit,
      taskCounts: data.policy_a.task_counts,
    });
    renderGanttChart(data.policy_b.timeline, "compTimelineB", {
      horizonMs: data.policy_b.horizon_ms || 10000,
      configuredHorizonMs: data.policy_b.configured_horizon_ms,
      overview: data.policy_b.overview,
      traceTotalEvents: data.policy_b.trace_total_events,
      knownClasses: Object.keys(data.policy_b.per_class || {}),
      traceTruncated: data.policy_b.trace_truncated,
      traceLimit: data.policy_b.trace_limit,
      taskCounts: data.policy_b.task_counts,
    });

    const aBatch = data.policy_a.per_class?.batch;
    const bBatch = data.policy_b.per_class?.batch;

    const aNoService = aBatch && aBatch.cpu_ms === 0 && (data.policy_a.task_counts?.batch || 0) > 0;
    const bHasService = bBatch && bBatch.cpu_ms > 0;
    const caption = document.getElementById("comparisonCaption");
    if (caption) caption.textContent = aNoService && bHasService
      ? "With the same runnable workload, strict priority delivered no batch CPU service in this horizon; aging delivered measurable batch service."
      : "The identical workload produced different observed CPU service; inspect the metrics and trace evidence before drawing a starvation conclusion.";
    const badgeA = document.getElementById("compBadgeA");
    const badgeB = document.getElementById("compBadgeB");
    if (badgeA) badgeA.textContent = aNoService ? "Batch received no CPU" : "Observed batch service";
    if (badgeB) badgeB.textContent = bHasService ? "Batch received CPU" : "No batch service observed";

    if (aBatch) {
      document.getElementById("compABatchShare").textContent = `${aBatch.share_pct}% (STARVED)`;
      document.getElementById("compABatchWait").textContent = `${aBatch.max_wait_ms} ms (Indefinite)`;
    }

    if (bBatch) {
      document.getElementById("compBBatchShare").textContent = `${bBatch.share_pct}% (Protected)`;
      document.getElementById("compBBatchWait").textContent = `${bBatch.max_wait_ms} ms (Bounded)`;
    }
    renderComparisonSummary(data.policy_a, "compSummaryA");
    renderComparisonSummary(data.policy_b, "compSummaryB");
  } catch (err) {
    console.error("Comparison error", err);
  }
}

function renderComparisonSummary(policy, elementId) {
  const target = document.getElementById(elementId);
  if (!target) return;
  const rows = Object.entries(policy.per_class || {}).map(([name, stats]) =>
    `${escapeHtml(name)}: ${stats.cpu_ms}ms CPU · ${stats.share_pct}% share · max wait ${stats.max_wait_ms}ms · ${stats.dispatches} dispatches`
  );
  const workload = (policy.workload || []).map(t => `${t.count} ${t.class}`).join(" + ") || "unspecified workload";
  target.textContent = `Workload: ${workload} · Horizon: ${policy.configured_horizon_ms || policy.horizon_ms}ms — ${rows.join(" | ")}`;
}

// ============================================================================
// 6. Adaptive Tuning Workspace
// ============================================================================

document.addEventListener("DOMContentLoaded", () => {
  const tuneBtn = document.getElementById("tuneRunBtn");
  if (tuneBtn) {
    tuneBtn.addEventListener("click", runAdaptiveTuner);
  }
});

async function runAdaptiveTuner() {
  const editor = document.getElementById("mainCodeEditor");
  if (!editor) return;
  const code = editor.value.trim();
  if (!code) return;

  const btn = document.getElementById("tuneRunBtn");
  if (btn) {
    btn.textContent = "Sweeping Candidates...";
    btn.disabled = true;
  }

  const paramSelect = document.getElementById("tuneParamSelect")?.value || "batch.aging";
  const [targetClass, param] = paramSelect.split(".");
  const minVal = parseInt(document.getElementById("tuneMinInput")?.value || "50", 10);
  const maxVal = parseInt(document.getElementById("tuneMaxInput")?.value || "400", 10);
  const steps = parseInt(document.getElementById("tuneStepsInput")?.value || "6", 10);

  try {
    const res = await fetch("/api/adapt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source: code,
        target_class: targetClass,
        param: param,
        range_min: minVal,
        range_max: maxVal,
        num_steps: steps,
      }),
    });

    const tune = await res.json();
    renderTunerResults(tune);

  } catch (err) {
    console.error("Tuner error", err);
  } finally {
    if (btn) {
      btn.textContent = "Run Adaptive Search";
      btn.disabled = false;
    }
  }
}

function renderTunerResults(tune) {
  const box = document.getElementById("tuneResultBox");
  const pill = document.getElementById("tuneResultPill");
  const title = document.getElementById("tuneResultTitle");
  const desc = document.getElementById("tuneResultDesc");
  const tbody = document.getElementById("tuneCandidatesBody");

  if (!box || !pill || !title || !desc || !tbody) return;

  if (tune.selected_value !== null) {
    box.className = "tuner-recommendation-card accepted";
    pill.textContent = `Selected: ${tune.selected_value} ms`;
    title.textContent = `Safe Frontier Found (${tune.selected_value} ms)`;
    desc.innerHTML = `<strong>Criterion:</strong> ${escapeHtml(tune.selection_reason)}<br><span style="opacity: 0.85;">${escapeHtml(tune.recommendation_summary)}</span>`;
  } else {
    box.className = "tuner-recommendation-card rejected";
    pill.textContent = "No Safe Frontier";
    title.textContent = "All Candidate Values Violate Guarantees";
    desc.textContent = tune.selection_reason || "Every evaluated configuration resulted in starvation or violated declared bounds.";
  }

  tbody.innerHTML = "";
  (tune.candidates || []).forEach(c => {
    const tr = document.createElement("tr");
    const isAccepted = c.status === "ACCEPTED";
    const badgeClass = isAccepted ? "badge-green" : "badge-red";
    const waitStr = c.tightest_wait_ms !== null ? `${c.tightest_wait_ms} ms` : "UNBOUNDED (INF)";

    tr.innerHTML = `
      <td><strong>${c.value} ms</strong></td>
      <td><span class="badge ${badgeClass}">${c.status}</span></td>
      <td>${waitStr}</td>
      <td><strong>${c.min_share_pct}%</strong></td>
      <td style="font-size: 11px; color: var(--color-text-secondary);">${escapeHtml(c.reason)}</td>
    `;
    tbody.appendChild(tr);
  });
}

// ============================================================================
// 7. Code Explorer Workspace
// ============================================================================

function initCodeExplorer() {
  const codeTabBtns = document.querySelectorAll(".code-tab-btn");
  codeTabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      codeTabBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const targetTab = btn.getAttribute("data-codetab");
      document.querySelectorAll(".code-tab-view").forEach(view => {
        if (view.id === targetTab) {
          view.classList.remove("hidden");
          view.classList.add("active");
        } else {
          view.classList.add("hidden");
          view.classList.remove("active");
        }
      });
    });
  });

  const fileDropdown = document.getElementById("sourceFileDropdown");
  if (fileDropdown) {
    fileDropdown.addEventListener("change", (e) => {
      loadSourceFileContent(e.target.value);
    });
  }

  const copyCBtn = document.getElementById("copyCSourceBtn");
  if (copyCBtn) {
    copyCBtn.addEventListener("click", () => {
      const code = document.getElementById("ebpfCDisplay")?.textContent || "";
      navigator.clipboard.writeText(code);
      copyCBtn.textContent = "Copied to Clipboard!";
      setTimeout(() => { copyCBtn.textContent = "Copy C Code"; }, 1600);
    });
  }
}

let sourceFilesLoaded = false;
async function ensureSourceFilesLoaded() {
  if (sourceFilesLoaded) return;
  try {
    const res = await fetch("/api/source_files");
    const data = await res.json();
    const dropdown = document.getElementById("sourceFileDropdown");
    if (!dropdown) return;
    dropdown.innerHTML = "";

    (data.files || []).forEach(f => {
      const opt = document.createElement("option");
      opt.value = f.path;
      opt.textContent = `${f.title} (${f.path})`;
      dropdown.appendChild(opt);
    });

    if (data.files && data.files.length > 0) {
      await loadSourceFileContent(data.files[0].path);
    }
    sourceFilesLoaded = true;
  } catch (err) {
    console.error("Failed to load source files list", err);
  }
}

async function loadSourceFileContent(path) {
  try {
    const res = await fetch(`/api/source_file?path=${encodeURIComponent(path)}`);
    const data = await res.json();

    const meta = document.getElementById("sourceFileLines");
    if (meta) meta.textContent = `${data.line_count} lines (${data.byte_size} bytes)`;

    const display = document.getElementById("sourceCodeDisplay");
    if (display) {
      const lines = (data.content || "").split("\n");
      const numbered = lines.map((l, i) => `${String(i + 1).padStart(4, " ")} | ${l}`).join("\n");
      display.textContent = numbered;
    }
  } catch (err) {
    console.error("Failed to fetch source file content", err);
  }
}

function renderEbpfSkeleton(cCode) {
  const display = document.getElementById("ebpfCDisplay");
  if (display) {
    display.textContent = cCode || "// Compile a policy in the Policy Editor to emit eBPF C skeleton...";
  }
}

// ============================================================================
// 8. Recent Runs Table (Overview Page)
// ============================================================================

async function loadRecentRuns() {
  try {
    const res = await fetch("/api/runs");
    const data = await res.json();
    const tbody = document.getElementById("recentRunsBody");
    if (!tbody) return;

    tbody.innerHTML = "";
    const runs = data.runs || [];

    if (runs.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="empty-cell">No saved runs found.</td></tr>';
      return;
    }

    runs.forEach(r => {
      const tr = document.createElement("tr");
      const verification = r.verification || {};
      const verifVerdict = verification.status || "NOT RUN";
      const compOk = r.compile_ok;

      const compBadge = compOk ? '<span class="badge badge-green">OK</span>' : '<span class="badge badge-red">FAILED</span>';
      const verifBadgeClass = verifVerdict === "VERIFIED" ? "badge-green" : (verifVerdict === "VIOLATED" ? "badge-red" : (verifVerdict === "INCONCLUSIVE" ? "badge-amber" : "badge-neutral"));

      const ts = r.timestamp ? new Date(r.timestamp).toLocaleTimeString() : "&mdash;";

      tr.innerHTML = `
        <td><code class="run-id-tag">${escapeHtml(r.run_id)}</code></td>
        <td>${ts}</td>
        <td><strong>${escapeHtml(r.policy_name)}</strong></td>
        <td>${compBadge}</td>
        <td><span class="badge ${verifBadgeClass}">${escapeHtml(verifVerdict)}</span><small>${escapeHtml(verification.summary || "")}</small></td>
        <td>${r.guarantees_count || 0} declared</td>
        <td>
          <button class="btn btn-ghost btn-sm" onclick="loadHistoricalRun('${r.run_id}')">View</button>
          <a class="btn btn-ghost btn-sm" href="/api/run/${r.run_id}/pdf" target="_blank" title="Download publication-grade academic PDF report">PDF</a>
        </td>
      `;
      tbody.appendChild(tr);
    });

  } catch (err) {
    console.error("Failed to load runs history", err);
  }
}

// Global loadHistoricalRun
window.loadHistoricalRun = async function(runId) {
  try {
    const res = await fetch(`/api/run/${runId}`);
    if (!res.ok) throw new Error(`API returned ${res.status}`);
    const runRecord = await res.json();

    // Load source into editor
    const editor = document.getElementById("mainCodeEditor");
    if (editor) {
      editor.value = runRecord.source_code || "";
      appState.currentSource = runRecord.source_code || "";
      setEditorPolicyState("Custom policy — loaded run", true);
      const gutter = document.getElementById("editorLineNumbers");
      if (gutter) {
        const lines = (runRecord.source_code || "").split("\n").length;
        gutter.innerHTML = Array.from({ length: lines }, (_, i) => i + 1).join("\n");
      }
    }

    renderRunRecord(runRecord);

    switchView("view-editor");
  } catch (err) {
    console.error("Failed to load historical run", err);
  }
};

// ============================================================================
// 9. Demonstration Walkthrough Modal (Quiet, non-intrusive)
// ============================================================================

function initDemonstrationModal() {
  const modal = document.getElementById("demoModal");
  const openBtn = document.getElementById("helpTourBtn");
  const closeBtn = document.getElementById("closeDemoModalBtn");
  const prevBtn = document.getElementById("demoPrevBtn");
  const nextBtn = document.getElementById("demoNextBtn");

  if (openBtn && modal) {
    openBtn.addEventListener("click", () => {
      appState.tourStep = 1;
      modal.classList.remove("hidden");
      renderDemoStep(1);
    });
  }

  if (closeBtn && modal) {
    closeBtn.addEventListener("click", () => {
      modal.classList.add("hidden");
    });
  }

  if (prevBtn) {
    prevBtn.addEventListener("click", () => {
      if (appState.tourStep > 1) {
        appState.tourStep--;
        renderDemoStep(appState.tourStep);
      }
    });
  }

  if (nextBtn) {
    nextBtn.addEventListener("click", () => {
      if (appState.tourStep < DEMO_STEPS.length) {
        appState.tourStep++;
        renderDemoStep(appState.tourStep);
      } else {
        if (modal) modal.classList.add("hidden");
      }
    });
  }
}

function renderDemoStep(idx) {
  const step = DEMO_STEPS[idx - 1];
  if (!step) return;

  const idxEl = document.getElementById("demoStepIndex");
  const titleEl = document.getElementById("demoStepTitle");
  const descEl = document.getElementById("demoStepDesc");
  const prevBtn = document.getElementById("demoPrevBtn");
  const nextBtn = document.getElementById("demoNextBtn");

  if (idxEl) idxEl.textContent = idx;
  if (titleEl) titleEl.textContent = step.title;
  if (descEl) descEl.textContent = step.desc;

  if (prevBtn) prevBtn.disabled = (idx === 1);
  if (nextBtn) {
    nextBtn.textContent = (idx === DEMO_STEPS.length) ? "Finish Walkthrough" : "Next Step →";
  }

  if (typeof step.action === "function") {
    step.action();
  }
}

// Utility: HTML Escaping
function escapeHtml(str) {
  if (typeof str !== "string") return String(str || "");
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
