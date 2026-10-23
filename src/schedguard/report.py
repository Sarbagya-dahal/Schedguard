"""Run history management and academic PDF report generator for SchedLang Studio.
Preserves exact source snapshots, compiler stage durations, Z3 verification verdicts,
simulator outcomes, and produces publication-quality, downloadable PDF reports.
"""
import datetime, json, os, pathlib, uuid
from typing import Any
from fpdf import FPDF
from fpdf.enums import XPos, YPos

RUNS_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "experiments" / "results" / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

# In-memory session store
_RUNS_CACHE: dict[str, dict[str, Any]] = {}
BACKEND_STAGES = ("emission", "build", "preflight", "load", "telemetry", "predictor", "watchdog", "hot_swap")
BACKEND_STATUSES = {"NOT_RUN", "UNSUPPORTED", "FAILED", "PASSED", "EXPERIMENTAL"}


def aggregate_verdicts(
    verdicts: list[dict[str, Any]] | None,
    analysis_status: str | None = None,
    analysis_error: str | None = None,
) -> dict[str, Any]:
    """Return the single source of truth for run-level guarantee status.

    Compilation is deliberately excluded: this summarizes only declared
    guarantees and the analyzer's actual execution/results.
    """
    items = verdicts or []
    counts = {
        "verified": sum(v.get("status") == "VERIFIED" for v in items),
        "violated": sum(v.get("status") == "VIOLATED" for v in items),
        "unknown": sum(v.get("status") == "UNKNOWN" for v in items),
    }
    declared = len(items)
    if analysis_status == "ERROR" or analysis_error:
        status = "ERROR"
    elif declared == 0:
        status = "NO_GUARANTEES" if analysis_status == "COMPLETED" else "NOT_RUN"
    elif analysis_status == "NOT_RUN":
        status = "NOT_RUN"
    elif analysis_status is None:
        # Backward-compatible interpretation of persisted records written
        # before analysis_status existed: verdict rows mean analysis ran.
        analysis_status = "COMPLETED"
        status = "VIOLATED" if counts["violated"] else ("INCONCLUSIVE" if counts["unknown"] else "VERIFIED")
    elif counts["violated"]:
        status = "VIOLATED"
    elif counts["unknown"]:
        status = "INCONCLUSIVE"
    elif counts["verified"] == declared:
        status = "VERIFIED"
    else:
        status = "ERROR"
    summary = {
        "VERIFIED": f"{counts['verified']} verified",
        "VIOLATED": f"{counts['violated']} violated",
        "INCONCLUSIVE": f"{counts['verified']} verified, {counts['unknown']} unknown",
        "NO_GUARANTEES": "No guarantees declared",
        "NOT_RUN": "Guarantee analysis not run",
        "ERROR": "Guarantee analysis error",
    }[status]
    return {
        "status": status,
        "summary": summary,
        "declared": declared,
        "counts": counts,
        "analysis_status": analysis_status or "NOT_RUN",
        "error": analysis_error or "",
    }


def _backend_status(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("status")
    normalized = str(value or "NOT_RUN").upper()
    return normalized if normalized in BACKEND_STATUSES else "NOT_RUN"


def normalize_backend_evidence(run: dict[str, Any]) -> dict[str, str]:
    """Normalize old and new run snapshots without inferring runtime success.

    Emission belongs to the code-generation result; every later stage needs
    explicit persisted evidence.  Older snapshots therefore remain `NOT_RUN`.
    """
    codegen = run.get("codegen") or {}
    recorded = run.get("backend_evidence") or {}
    runtime = codegen.get("runtime_evidence") or {}
    evidence = {stage: _backend_status(recorded.get(stage, runtime.get(stage))) for stage in BACKEND_STAGES}
    if codegen.get("c_code") or codegen.get("status") or codegen.get("status_label"):
        evidence["emission"] = _backend_status(codegen.get("status"))
    return evidence


def _load_persisted_runs():
    global _RUNS_CACHE
    if not RUNS_DIR.exists():
        return
    for p in sorted(RUNS_DIR.glob("run_*.json"), key=os.path.getmtime, reverse=True)[:50]:
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
                _RUNS_CACHE[data["run_id"]] = data
        except Exception:
            pass


_load_persisted_runs()


def create_run_record(
    source_code: str,
    policy_name: str,
    compile_data: dict[str, Any],
    check_data: dict[str, Any] | None = None,
    analyze_data: dict[str, Any] | None = None,
    sim_data: dict[str, Any] | None = None,
    codegen_data: dict[str, Any] | None = None,
    tuner_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Creates, persists, and indexes an immutable snapshot of an experimental run."""
    now = datetime.datetime.now()
    run_id = f"run_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    record = {
        "run_id": run_id,
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "policy_name": policy_name,
        "source_code": source_code,
        "compile": compile_data,
        "check": check_data or {"verdicts": [], "all_verified": False, "has_violation": False,
                                 "has_unknown": False, "analysis_status": "NOT_RUN"},
        "analyze": analyze_data or {"facts": {}},
        "simulate": sim_data or {},
        "codegen": codegen_data or {},
        "tuner": tuner_data or {},
        "model_scope": {
            "workload_assumptions": "Single CPU; static CPU-bound tasks (always runnable, non-preemptive quanta); task count bounded by max_tasks per class.",
            "verifier_type": "Custom SMT scheduler analyzer implemented via Z3 over linear integer arithmetic.",
            "kernel_distinction": "This formal analyzer verifies scheduling-level properties (starvation, CPU share bounds) under our formal model. It is NOT the Linux in-kernel BPF verifier (which checks register safety/memory safety). Real-kernel sched_ext loading and execution have not been attempted and remain Phase 4 objectives."
        }
    }
    record["backend_evidence"] = normalize_backend_evidence(record)
    if "analysis_status" not in record["check"]:
        record["check"]["analysis_status"] = "COMPLETED" if compile_data.get("ok") else "NOT_RUN"
    record["check"]["aggregate"] = aggregate_verdicts(
        record["check"].get("verdicts", []),
        record["check"].get("analysis_status"),
        record["check"].get("analysis_error"),
    )

    _RUNS_CACHE[run_id] = record

    try:
        file_path = RUNS_DIR / f"{run_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)
    except Exception as e:
        print(f"Warning: could not persist run to disk: {e}")

    return record


def get_run(run_id: str) -> dict[str, Any] | None:
    if run_id in _RUNS_CACHE:
        return _RUNS_CACHE[run_id]
    file_path = RUNS_DIR / f"{run_id}.json"
    if file_path.exists():
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
                _RUNS_CACHE[run_id] = data
                return data
        except Exception:
            pass
    return None


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    runs = list(_RUNS_CACHE.values())
    runs.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return [
        {
            "run_id": r["run_id"],
            "timestamp": r["timestamp"],
            "policy_name": r["policy_name"],
            "compile_ok": r["compile"].get("ok", False),
            "all_verified": r["check"].get("all_verified", False),
            "has_violation": r["check"].get("has_violation", False),
            "guarantees_count": len(r["check"].get("verdicts", [])),
            "sim_decisions": r["simulate"].get("decisions", 0),
            "verification": aggregate_verdicts(
                r["check"].get("verdicts", []),
                r["check"].get("analysis_status"),
                r["check"].get("analysis_error"),
            ),
        }
        for r in runs[:limit]
    ]


class SchedLangPDF(FPDF):
    def __init__(self, run_id: str, policy_name: str, timestamp: str):
        super().__init__(format="A4", unit="mm")
        self.run_id = run_id
        self.policy_name = policy_name
        self.timestamp = timestamp
        self.set_auto_page_break(auto=True, margin=15)

    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(100, 116, 139)
        self.cell(0, 7, f"SchedLang Research Run Report | Policy: {self.policy_name} | ID: {self.run_id}", border="B", align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(3)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(148, 163, 184)
        self.cell(0, 7, f"Page {self.page_no()}/{{nb}} -- An AI-Driven DSL Compiler for Adaptive eBPF Scheduling", border="T", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def section_heading(self, title: str):
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(30, 41, 59)
        self.ln(3)
        self.cell(0, 6, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(226, 232, 240)
        self.line(self.get_x(), self.get_y(), self.get_x() + 190, self.get_y())
        self.ln(2)


def generate_run_pdf(run: dict[str, Any]) -> bytes:
    """Renders an immutable run record into an academic, publication-quality PDF."""
    pdf = SchedLangPDF(run["run_id"], run["policy_name"], run["timestamp"])
    pdf.set_compression(False)
    pdf.alias_nb_pages()
    pdf.add_page()

    # Title Banner
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 8, "SchedLang Compiler & Verification Report", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(71, 85, 105)
    pdf.cell(0, 5, f"Policy: {run['policy_name']}  |  Timestamp: {run['timestamp']}  |  Run ID: {run['run_id']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)

    # Executive Summary & Academic Model Scope
    pdf.set_fill_color(248, 250, 252)
    pdf.set_draw_color(203, 213, 225)
    pdf.rect(pdf.get_x(), pdf.get_y(), 190, 26, style="DF")
    pdf.set_xy(pdf.get_x() + 3, pdf.get_y() + 2)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(30, 41, 59)
    pdf.cell(0, 4, "Research Scope & Technical Disclosure:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 7.5)
    pdf.set_text_color(71, 85, 105)
    pdf.multi_cell(184, 3.8, (
        "1. Formal Model: Proves scheduling guarantees over all static CPU-bound workloads up to max_tasks on a single CPU.\n"
        "2. Custom SMT Analyzer: Verified using Z3 over linear integer arithmetic; counterexamples replayed in discrete simulator.\n"
        "3. Kernel Distinction: NOT the Linux in-kernel eBPF verifier. Real-kernel sched_ext loading and multi-core evaluation are Phase 4 objectives."
    ))
    pdf.set_y(pdf.get_y() + 3)

    # 1. Source Snapshot
    pdf.section_heading("1. PolicyLang DSL Source Snapshot")
    pdf.set_font("Courier", "", 8)
    pdf.set_fill_color(241, 245, 249)
    source_lines = run.get("source_code", "").strip().splitlines()
    for line in source_lines[:28]:
        trunc = line[:90]
        pdf.cell(190, 4.0, f"  {trunc}", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

    # 2. Compiler Stages
    pdf.section_heading("2. Compiler Pipeline Stage Durations")
    stages = run.get("compile", {}).get("stages", [])
    if stages:
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_fill_color(226, 232, 240)
        pdf.set_text_color(30, 41, 59)
        pdf.cell(45, 5.5, "Compiler Stage", 1, align="L", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(25, 5.5, "Status", 1, align="C", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(25, 5.5, "Duration (ms)", 1, align="R", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(95, 5.5, "Details", 1, align="L", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.set_font("Helvetica", "", 7.5)
        for st in stages:
            pdf.cell(45, 5, st.get("name", ""), 1, align="L", new_x=XPos.RIGHT, new_y=YPos.TOP)
            status = st.get("status", "")
            pdf.set_text_color(22, 101, 52 if status == "COMPLETED" else (185, 28, 28 if status == "FAILED" else 100))
            pdf.cell(25, 5, status, 1, align="C", new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.set_text_color(51, 65, 85)
            pdf.cell(25, 5, f"{st.get('duration_ms', 0):.2f}", 1, align="R", new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(95, 5, st.get("details", "")[:65], 1, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    else:
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(0, 5, "No stage telemetry recorded.", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # 3. IR Table
    ir_classes = run.get("compile", {}).get("ir", {}).get("classes", [])
    if ir_classes:
        pdf.section_heading("3. Fixed-Size Intermediate Representation (Class Table)")
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_fill_color(226, 232, 240)
        pdf.cell(20, 5.5, "Class ID", 1, align="C", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(40, 5.5, "Class Name", 1, align="L", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(30, 5.5, "Priority Tier", 1, align="C", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(35, 5.5, "Quantum (ms)", 1, align="R", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(35, 5.5, "Aging Threshold", 1, align="R", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(30, 5.5, "Kind Tag", 1, align="C", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.set_font("Helvetica", "", 7.5)
        for c in ir_classes:
            pdf.cell(20, 5, str(c.get("idx", 0)), 1, align="C", new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(40, 5, c.get("name", ""), 1, align="L", new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(30, 5, f"Tier {c.get('prio', 0)}", 1, align="C", new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(35, 5, f"{c.get('quantum_ms', 0)} ms", 1, align="R", new_x=XPos.RIGHT, new_y=YPos.TOP)
            aging_val = c.get("aging_ms")
            pdf.cell(35, 5, f"{aging_val} ms" if aging_val else "None", 1, align="R", new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(30, 5, c.get("kind") or "-", 1, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # 4. Formal Guarantee Verification (Z3)
    check = run.get("check", {})
    verdicts = check.get("verdicts", [])
    aggregate = check.get("aggregate") or aggregate_verdicts(
        verdicts,
        check.get("analysis_status") or ("COMPLETED" if run.get("compile", {}).get("ok") else "NOT_RUN"),
        check.get("analysis_error"),
    )
    pdf.section_heading("4. Formal Guarantee Verification (Z3 SMT Solver)")
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(30, 41, 59)
    pdf.cell(0, 5, f"Overall outcome: {aggregate['status']} - {aggregate['summary']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if aggregate.get("error"):
        pdf.set_font("Helvetica", "", 7.5)
        pdf.multi_cell(190, 4, f"Analyzer error: {aggregate['error']}")
    if verdicts:
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_fill_color(226, 232, 240)
        pdf.cell(65, 5.5, "Guarantee Specification", 1, align="L", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(25, 5.5, "Verdict", 1, align="C", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(25, 5.5, "Solver (ms)", 1, align="R", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(75, 5.5, "Replay & Counterexample Evidence", 1, align="L", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.set_font("Helvetica", "", 7.5)
        for v in verdicts:
            pdf.cell(65, 5, v.get("guarantee", ""), 1, align="L", new_x=XPos.RIGHT, new_y=YPos.TOP)
            status = v.get("status", "")
            if status == "VERIFIED":
                pdf.set_text_color(22, 101, 52)
            elif status == "VIOLATED":
                pdf.set_text_color(185, 28, 28)
            else:
                pdf.set_text_color(180, 83, 9)
            pdf.cell(25, 5, status, 1, align="C", new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.set_text_color(51, 65, 85)
            pdf.cell(25, 5, f"{v.get('elapsed_ms', 0):.2f}", 1, align="R", new_x=XPos.RIGHT, new_y=YPos.TOP)
            evidence = v.get("evidence", "")
            if evidence == "confirmed_replay":
                evidence_label = "Confirmed replay: "
            elif evidence == "solver_candidate":
                evidence_label = "Solver candidate (not confirmed): "
            elif evidence == "not_reproduced":
                evidence_label = "Not reproduced: "
            else:
                evidence_label = ""
            cex_str = f"Candidate: {v.get('counterexample')} | " if v.get("counterexample") else ""
            rep_str = (evidence_label + cex_str + v.get("replay", ""))[:55]
            pdf.cell(75, 5, rep_str, 1, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # 5. Simulator Outcome
    sim = run.get("simulate", {})
    if sim and "per_class" in sim:
        pdf.section_heading("5. CPU Scheduler Discrete-Event Simulation Observations")
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(0, 4.5, f"Simulation Horizon: {sim.get('horizon_ms', 0)} ms  |  Total Dispatches: {sim.get('decisions', 0)}  |  CPU Idle: {sim.get('idle_ms', 0)} ms", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.set_font("Helvetica", "B", 8)
        pdf.set_fill_color(226, 232, 240)
        pdf.cell(40, 5.5, "Class", 1, align="L", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(35, 5.5, "CPU Time (ms)", 1, align="R", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(35, 5.5, "CPU Share (%)", 1, align="R", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(40, 5.5, "Observed Max Wait", 1, align="R", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(40, 5.5, "Dispatches", 1, align="R", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.set_font("Helvetica", "", 7.5)
        for name, st in sim.get("per_class", {}).items():
            pdf.cell(40, 5, name, 1, align="L", new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(35, 5, f"{st.get('cpu_ms', 0)}", 1, align="R", new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(35, 5, f"{st.get('share_pct', 0.0):.1f}%", 1, align="R", new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(40, 5, f"{st.get('max_wait_ms', 0)} ms", 1, align="R", new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(40, 5, f"{st.get('dispatches', 0)}", 1, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # 6. sched_ext evidence: source emission, build, and runtime stages are distinct.
    pdf.section_heading("6. eBPF C Backend (sched_ext) Status")
    pdf.set_font("Helvetica", "", 8)
    backend = normalize_backend_evidence(run)
    pdf.cell(0, 4.5, f"Emission: {backend['emission']}  |  Build: {backend['build']}  |  Preflight: {backend['preflight']}  |  Load: {backend['load']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 4.5, f"Telemetry: {backend['telemetry']}  |  Predictor: {backend['predictor']}  |  Watchdog: {backend['watchdog']}  |  Hot swap: {backend['hot_swap']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "I", 7.5)
    limitations = (run.get("codegen") or {}).get("limitations") or [
        "No backend evidence was recorded for this run. Source generation, target compilation, and kernel runtime are separate stages.",
        "Formal verifier results use the documented single-CPU static CPU-bound model; simulator and telemetry provenance are distinct.",
    ]
    pdf.multi_cell(190, 4.0, "\n".join(f"- {item}" for item in limitations))

    return bytes(pdf.output())
