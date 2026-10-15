/**
 * SchedLang Studio - Research Workbench Controller
 * Clean, minimal, and deeply inspectable interface for SchedLang compiler research.
 */

// Global Application State
const appState = {
  currentRunId: null,
  currentRunRecord: null,
  currentSource: "",
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

  // Load examples & recent runs
  await loadExamples();
  await loadRecentRuns();

  // Load default policy example into editor
  await loadExample("aging_fix");
});

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
  }
}

// Make switchView globally accessible for inline onclick links
window.switchView = switchView;

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
      const gutter = document.getElementById("editorLineNumbers");
      if (gutter) {
        const lines = ex.code.split("\n").length;
        gutter.innerHTML = Array.from({ length: lines }, (_, i) => i + 1).join("\n");
      }
      await executeCompileAndRun();
    }
  }
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

  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: code, replay: true }),
    });

    const runRecord = await res.json();
    appState.currentRunId = runRecord.run_id;
    appState.currentRunRecord = runRecord;

    // 1. Update Compact Stages Bar with Real Telemetry
    renderStageTelemetry(runRecord.stages, runRecord.compilation);

    // 2. Update Inspector Drawer
    renderInspectorDrawer(runRecord);

    // 3. Update Verification Workspace
    renderVerificationView(runRecord);

    // 4. Update Workload Simulator Workspace
    renderSimulatorView(runRecord);

    // 5. Update eBPF C Display in Code Explorer
    renderEbpfSkeleton(runRecord.c_skeleton);

    // 6. Enable PDF Download Buttons
    const footerPdfBtn = document.getElementById("footerDownloadPdfBtn");
    const verifPdfBtn = document.getElementById("verifDownloadPdfBtn");
    if (footerPdfBtn) footerPdfBtn.disabled = false;
    if (verifPdfBtn) verifPdfBtn.disabled = false;

    if (statusText) {
      if (runRecord.compilation.ok) {
        const dur = (runRecord.total_compile_ms || 0).toFixed(2);
        statusText.innerHTML = `<strong>Compiled successfully</strong> in ${dur}ms &mdash; Run ID: <code>${runRecord.run_id}</code>`;
      } else {
        statusText.innerHTML = `<span class="text-red"><strong>Compilation failed:</strong> ${escapeHtml(runRecord.compilation.summary || "Errors detected")}</span>`;
      }
    }

  } catch (err) {
    console.error("Execution pipeline error:", err);
    if (statusText) statusText.textContent = "Error executing compilation.";
  } finally {
    if (compileBtn) compileBtn.disabled = false;
  }
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
    const chipId = `stg${stg.name.charAt(0).toUpperCase() + stg.name.slice(1)}`;
    setStageChip(chipId, stg.status, stg.duration_ms);
  });

  const badge = document.getElementById("compilerDurationBadge");
  if (badge) {
    badge.textContent = `${totalMs.toFixed(2)} ms`;
  }
}

function renderInspectorDrawer(runRecord) {
  // 1. Stages List with durations and errors
  const list = document.getElementById("inspectorStagesList");
  if (list) {
    list.innerHTML = "";
    (runRecord.stages || []).forEach(stg => {
      const item = document.createElement("div");
      item.className = "stage-detail-item";
      const statusBadgeClass = stg.status === "completed" ? "badge-green" : (stg.status === "failed" ? "badge-red" : "badge-neutral");
      
      let errorHtml = "";
      if (stg.error) {
        errorHtml = `<div class="stage-error-msg">${escapeHtml(stg.error)}</div>`;
      }

      item.innerHTML = `
        <div class="stage-top-row">
          <span class="stage-name-bold">${stg.name.toUpperCase()} STAGE</span>
          <span class="badge ${statusBadgeClass}">${stg.status.toUpperCase()} (${(stg.duration_ms || 0).toFixed(2)} ms)</span>
        </div>
        ${errorHtml}
      `;
      list.appendChild(item);
    });
  }

  // 2. Normalized IR tab
  const irCode = document.getElementById("inspectorIrCode");
  if (irCode) {
    irCode.textContent = runRecord.compilation?.ir?.dump || "No IR generated.";
  }

  // 3. AST JSON tab
  const astCode = document.getElementById("inspectorAstCode");
  if (astCode) {
    astCode.textContent = JSON.stringify(runRecord.compilation?.ast || {}, null, 2);
  }

  // 4. Diagnostics tab
  const diagsList = document.getElementById("inspectorDiagsList");
  if (diagsList) {
    diagsList.innerHTML = "";
    const diags = runRecord.compilation?.diagnostics || [];
    if (diags.length === 0) {
      diagsList.innerHTML = '<div class="empty-state">No semantic or safety diagnostics issued.</div>';
    } else {
      diags.forEach(d => {
        const item = document.createElement("div");
        item.className = "diag-item";
        item.textContent = `[${d.code}] Line ${d.line || 0}: ${d.message}`;
        diagsList.appendChild(item);
      });
    }
  }
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

    const data = await res.json();
    appState.pendingAiPolicy = data.source_code;

    const resultBox = document.getElementById("aiProposalResult");
    const badge = document.getElementById("aiResultEngineBadge");
    const rationale = document.getElementById("aiResultRationale");

    if (resultBox && badge && rationale) {
      badge.textContent = data.mode_label || "Rule Engine";
      rationale.textContent = data.rationale || "No rationale provided.";
      resultBox.classList.remove("hidden");
    }

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

  const verif = runRecord.verification || {};
  const overall = verif.overall_verdict || "NOT RUN";

  // 1. Overall Banner
  banner.className = `verdict-banner-card ${overall.toLowerCase()}`;
  badge.textContent = overall;

  if (overall === "VERIFIED") {
    title.textContent = "All Formal Guarantees Mathematically Proven Safe";
    desc.textContent = "Z3 SMT solver proved starvation freedom and/or minimum share bounds over all bounded static workloads.";
  } else if (overall === "VIOLATED") {
    title.textContent = "Formal Guarantee Violation Refuted by Z3";
    desc.textContent = "The solver synthesized a concrete counterexample workload causing starvation, confirmed via discrete simulator replay.";
  } else if (overall === "UNKNOWN") {
    title.textContent = "Verifier Inconclusive";
    desc.textContent = "SMT solver exceeded search horizon or property could not be established within bounds.";
  } else {
    title.textContent = "Compilation Issue";
    desc.textContent = runRecord.compilation?.summary || "Fix errors to run formal verification.";
  }

  // 2. Individual Guarantee Cards
  cardsContainer.innerHTML = "";
  const verdicts = verif.verdicts || [];

  if (verdicts.length === 0) {
    cardsContainer.innerHTML = '<div class="empty-state-box">Policy declares no formal guarantees. Add <code>guarantee no_starvation</code> or <code>guarantee min_share</code> in the editor.</div>';
  } else {
    verdicts.forEach(v => {
      const card = document.createElement("div");
      const statusLower = (v.status || "unknown").toLowerCase();
      card.className = `guarantee-card ${statusLower}`;

      const statusBadgeClass = v.status === "VERIFIED" ? "badge-green" : (v.status === "VIOLATED" ? "badge-red" : "badge-amber");

      let counterexampleHtml = "";
      if (v.counterexample) {
        const counts = Object.entries(v.counterexample).map(([c, n]) => `${c}: ${n}`).join(", ");
        counterexampleHtml = `
          <div class="counterexample-card">
            <strong>Adversarial Counterexample Workload:</strong> { ${counts} }
          </div>
        `;
      }

      let replayHtml = "";
      if (v.replay) {
        replayHtml = `<div class="replay-evidence"><strong>Simulator Replay Evidence:</strong> ${escapeHtml(v.replay)}</div>`;
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
  const facts = runRecord.facts || {};
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
  const sim = runRecord.simulation || {};
  renderGanttChart(sim.timeline, "simGanttTimeline");
  renderSimMetricsTable(sim.per_class, "simMetricsBody");
}

function renderGanttChart(timeline, containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = "";

  if (!timeline || timeline.length === 0) {
    container.innerHTML = '<div class="empty-state">No timeline events recorded. Run simulation to observe execution.</div>';
    return;
  }

  const tooltip = document.getElementById("simTooltip");

  timeline.slice(0, 150).forEach(ev => {
    const slice = document.createElement("div");
    const clsName = (ev.class_name || "default").toLowerCase();
    const isBoosted = Boolean(ev.boosted);

    slice.className = `gantt-slice ${clsName} ${isBoosted ? "boosted" : ""}`;
    const widthPx = Math.max(22, Math.min(110, (ev.duration_ms || 10) * 3.2));
    slice.style.width = `${widthPx}px`;

    slice.innerHTML = `
      ${isBoosted ? '<span class="boost-star" title="Promoted via aging threshold!">★</span>' : ""}
      <span>${escapeHtml(ev.class_name)}</span>
      <span style="font-size: 8px; opacity: 0.8;">#${ev.task_id}</span>
    `;

    if (tooltip) {
      slice.addEventListener("mouseenter", (e) => {
        tooltip.classList.remove("hidden");
        tooltip.innerHTML = `
          <strong>${escapeHtml(ev.class_name)}</strong> (Task #${ev.task_id})<br>
          Execution: ${ev.start_ms}ms &rarr; ${ev.end_ms}ms (${ev.duration_ms}ms)<br>
          Observed Wait: <strong>${ev.wait_ms} ms</strong><br>
          Priority Tier: ${ev.prio} ${isBoosted ? "<strong>(BOOSTED via Aging)</strong>" : ""}<br>
          Queue Depths: ${JSON.stringify(ev.queue_sizes || {})}
        `;
      });

      slice.addEventListener("mousemove", (e) => {
        tooltip.style.left = `${e.clientX + 14}px`;
        tooltip.style.top = `${e.clientY + 14}px`;
      });

      slice.addEventListener("mouseleave", () => {
        tooltip.classList.add("hidden");
      });
    }

    container.appendChild(slice);
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
  let workload = null;
  if (preset === "heavy_web") {
    workload = { tasks: [{ class: "web", count: 8 }, { class: "batch", count: 2 }] };
  } else if (preset === "single_batch") {
    workload = { tasks: [{ class: "web", count: 2 }, { class: "batch", count: 1 }] };
  } else {
    workload = { tasks: [{ class: "web", count: 4 }, { class: "batch", count: 4 }] };
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
    renderGanttChart(data.timeline, "simGanttTimeline");
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
        horizon_ms: 10000,
      }),
    });

    const data = await res.json();
    renderGanttChart(data.policy_a.timeline, "compTimelineA");
    renderGanttChart(data.policy_b.timeline, "compTimelineB");

    const aBatch = data.policy_a.per_class?.batch;
    const bBatch = data.policy_b.per_class?.batch;

    if (aBatch) {
      document.getElementById("compABatchShare").textContent = `${aBatch.share_pct}% (STARVED)`;
      document.getElementById("compABatchWait").textContent = `${aBatch.max_wait_ms} ms (Indefinite)`;
    }

    if (bBatch) {
      document.getElementById("compBBatchShare").textContent = `${bBatch.share_pct}% (Protected)`;
      document.getElementById("compBBatchWait").textContent = `${bBatch.max_wait_ms} ms (Bounded)`;
    }
  } catch (err) {
    console.error("Comparison error", err);
  }
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
      tbody.innerHTML = '<tr><td colspan="7" class="empty-cell">No runs executed yet in this session. Open the Policy Editor to compile your first policy.</td></tr>';
      return;
    }

    runs.forEach(r => {
      const tr = document.createElement("tr");
      const verifVerdict = r.verification?.overall_verdict || "NONE";
      const compOk = r.compilation?.ok;

      const compBadge = compOk ? '<span class="badge badge-green">OK</span>' : '<span class="badge badge-red">FAILED</span>';
      const verifBadgeClass = verifVerdict === "VERIFIED" ? "badge-green" : (verifVerdict === "VIOLATED" ? "badge-red" : "badge-neutral");

      const ts = r.timestamp ? new Date(r.timestamp).toLocaleTimeString() : "&mdash;";

      tr.innerHTML = `
        <td><code class="run-id-tag">${escapeHtml(r.run_id)}</code></td>
        <td>${ts}</td>
        <td><strong>${escapeHtml(r.policy_name)}</strong></td>
        <td>${compBadge}</td>
        <td><span class="badge ${verifBadgeClass}">${escapeHtml(verifVerdict)}</span></td>
        <td>${r.compilation?.ir?.guarantees?.length || 0} declared</td>
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
    const runRecord = await res.json();
    appState.currentRunId = runRecord.run_id;
    appState.currentRunRecord = runRecord;

    // Load source into editor
    const editor = document.getElementById("mainCodeEditor");
    if (editor) {
      editor.value = runRecord.source_snapshot || "";
      appState.currentSource = runRecord.source_snapshot || "";
      const gutter = document.getElementById("editorLineNumbers");
      if (gutter) {
        const lines = (runRecord.source_snapshot || "").split("\n").length;
        gutter.innerHTML = Array.from({ length: lines }, (_, i) => i + 1).join("\n");
      }
    }

    renderStageTelemetry(runRecord.stages, runRecord.compilation);
    renderInspectorDrawer(runRecord);
    renderVerificationView(runRecord);
    renderSimulatorView(runRecord);
    renderEbpfSkeleton(runRecord.c_skeleton);

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
