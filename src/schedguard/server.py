"""FastAPI REST server for SchedLang Studio.
Exposes compilation, formal guarantee analysis, simulation with timeline tracing,
adaptive parameter tuning, eBPF C codegen, and source exploration.
"""
import glob, json, logging, os, pathlib, uuid
from typing import Any, Optional
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .compiler import compile_source, compile_instrumented
from .dsl import DSLError, parse
from .dsl.ast_nodes import PolicyAST
from .ir import IRPolicy
from .verify.properties import check_all, analyze
from .sim import simulate, Workload
from .sim.workload import TaskSpec
from .inference import infer
from .inference.providers import ProviderFailure, get_provider, sanitize_provider_message
from .inference.policy_gen import propose_policy
from .synth.agent import synthesize_policy
from .repair.classify import classify_violation
from .repair.loop import repair_policy
from .adapt import tune_policy
from .codegen import emit_ebpf_c
from .codegen.build import build_ebpf, check_toolchain
from .runtime import LifecycleState, preflight, watchdog_check
from .report import create_run_record, get_run, list_runs, generate_run_pdf, aggregate_verdicts

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent.parent
STUDIO_DIR = pathlib.Path(__file__).resolve().parent / "studio"

app = FastAPI(
    title="SchedLang Studio API",
    description="REST backend for AI-Driven eBPF Scheduling Compiler research studio",
    version="1.0.0",
)
logger = logging.getLogger(__name__)


def cors_origins(raw_origins: Optional[str] = None) -> list[str]:
    """Return explicitly configured cross-origin callers for this local Studio.

    The browser UI is served by this application, so it needs no CORS policy by
    default. A deployment that deliberately splits UI and API origins must opt
    in with a comma-separated ``SCHEDGUARD_ALLOWED_ORIGINS`` value.
    """
    raw = os.environ.get("SCHEDGUARD_ALLOWED_ORIGINS", "") if raw_origins is None else raw_origins
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


_cors_origins = cors_origins()
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )


@app.exception_handler(Exception)
async def unhandled_api_error(request, exc):
    """Keep browser responses JSON while retaining the real traceback in logs."""
    logger.exception("Unhandled API error for %s %s", request.method, request.url.path)
    return Response(
        content=json.dumps({"ok": False, "error": "Internal server error", "message": "The operation failed; see server logs."}),
        status_code=500,
        media_type="application/json",
    )


def provider_error_response(operation: str, provider: str, exc: ProviderFailure) -> JSONResponse:
    """Translate provider failures without collapsing configuration and upstream causes into HTTP 500."""
    correlation_id = uuid.uuid4().hex
    logger.warning("Provider failure %s operation=%s provider=%s category=%s upstream_status=%s retryable=%s: %s",
                   correlation_id, operation, provider, exc.category, exc.upstream_status, exc.retryable,
                   sanitize_provider_message(exc))
    if exc.category == "configuration":
        status_code = 400
    elif exc.retryable:
        status_code = 503
    else:
        status_code = 502
    return JSONResponse(status_code=status_code, content={
        "ok": False,
        "error": {
            "operation": operation,
            "provider": provider,
            "category": exc.category,
            "upstream_status": exc.upstream_status,
            "retryable": exc.retryable,
            "message": sanitize_provider_message(exc),
            "correlation_id": correlation_id,
        },
    })


def proposal_provider_failure(proposal: dict[str, Any]) -> ProviderFailure:
    """Translate an already-sanitized proposal result to the shared HTTP contract."""
    details = proposal.get("provider_error_details") or {}
    return ProviderFailure(
        str(details.get("category") or "request"),
        str(proposal.get("provider_error") or "Provider request failed"),
        upstream_status=details.get("upstream_status"),
        retryable=bool(details.get("retryable")),
    )


# ---------------------------------------------------------
# Request / Response Schemas
# ---------------------------------------------------------
class SourceRequest(BaseModel):
    source: str = Field(..., description="SchedLang DSL source text")


class CheckRequest(BaseModel):
    source: str
    replay: bool = True


class SimulateRequest(BaseModel):
    source: str
    workload: Optional[dict[str, Any]] = None
    horizon_ms: int = 15000
    record_trace: bool = True
    max_trace_events: int = 1200


class CompareSimRequest(BaseModel):
    policy_a: str
    policy_b: str
    workload: Optional[dict[str, Any]] = None
    horizon_ms: int = 15000


class InferRequest(BaseModel):
    source: str
    intent: Optional[dict[str, Any]] = None
    provider: str = "stub"


class GenerateRequest(BaseModel):
    prompt: str
    provider: str = "rules"


class SynthesisRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=12000)
    provider: str = "stub"
    repair: bool = True
    clarification_answer: Optional[str] = Field(default=None, max_length=100)


class RepairRequest(BaseModel):
    source: str = Field(..., min_length=1, max_length=100000)
    feedback: str = "template"


class MetricsRequest(BaseModel):
    include_runs: bool = True


class AdaptRequest(BaseModel):
    source: str
    target_class: Optional[str] = None
    param: Optional[str] = None
    range_min: Optional[int] = None
    range_max: Optional[int] = None
    num_steps: int = 8


class BuildRequest(BaseModel):
    source: str
    output: str = "build/schedguard.bpf.o"
    vmlinux_header: Optional[str] = None
    scx_header: Optional[str] = None


# ---------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------
def _ir_to_dict(ir: IRPolicy) -> dict[str, Any]:
    return {
        "name": ir.name,
        "max_tasks": ir.max_tasks,
        "classes": [
            {
                "idx": c.idx,
                "name": c.name,
                "prio": c.prio,
                "quantum_ms": c.quantum_ms,
                "aging_ms": c.aging_ms,
                "kind": c.kind,
            }
            for c in ir.classes
        ],
        "guarantees": [
            {
                "kind": g.kind,
                "cls_idx": g.cls_idx,
                "cls_name": g.cls_name,
                "value": g.value,
                "pretty": g.pretty(),
            }
            for g in ir.guarantees
        ],
        "adaptations": [
            {
                "cls_idx": a.cls_idx,
                "cls_name": a.cls_name,
                "param": a.param,
                "min_val": a.min_val,
                "max_val": a.max_val,
                "pretty": a.pretty(),
            }
            for a in ir.adaptations
        ],
        "dump": ir.dump(),
    }


def _ast_to_dict(ast: PolicyAST) -> dict[str, Any]:
    return {
        "node_type": "PolicyAST",
        "name": ast.name,
        "max_tasks": ast.max_tasks,
        "classes": [
            {
                "node_type": "ClassDecl",
                "name": c.name,
                "line": c.line,
                "prio": c.prio,
                "quantum_ms": c.quantum_ms,
                "aging_ms": c.aging_ms,
                "kind": c.kind,
            }
            for c in ast.classes
        ],
        "guarantees": [
            {
                "node_type": "GuaranteeDecl",
                "kind": g.kind,
                "cls": g.cls,
                "value": g.value,
                "line": g.line,
            }
            for g in ast.guarantees
        ],
        "adaptations": [
            {
                "node_type": "AdaptDecl",
                "cls": a.cls,
                "param": a.param,
                "min_val": a.min_val,
                "max_val": a.max_val,
                "line": a.line,
            }
            for a in getattr(ast, "adaptations", [])
        ],
    }


def _diagnostics_to_dict(res) -> list[dict[str, Any]]:
    if res.syntax_error:
        return [{"code": "SYNTAX", "message": res.syntax_error, "line": res.syntax_line, "col": res.syntax_col, "stage": "parsing"}]
    return [{"code": d.code, "message": d.message, "line": d.line, "col": 0, "stage": "safety"} for d in res.diagnostics]


def _parse_workload(raw: Optional[dict[str, Any]], ir: IRPolicy) -> Workload:
    if raw and "tasks" in raw:
        tasks = []
        for t in raw["tasks"]:
            tasks.append(
                TaskSpec(
                    cls=t["class"],
                    count=int(t["count"]),
                    work_ms=int(t["work_ms"]) if t.get("work_ms") is not None else None,
                    arrival_ms=int(t.get("arrival_ms", 0)),
                )
            )
        return Workload(tuple(tasks))

    # Default workload: balanced 2 tasks per class
    counts = {c.name: 3 if c.prio == 0 else 2 for c in ir.classes}
    return Workload.from_counts(counts)


def _sim_to_dict(sim_res, wl: Workload) -> dict[str, Any]:
    """Serialize telemetry without implying that a bounded trace is complete."""
    return {
        "horizon_ms": sim_res.horizon_ms,  # retained: elapsed execution endpoint
        "configured_horizon_ms": sim_res.configured_horizon_ms,
        "end_ms": sim_res.end_ms,
        "idle_ms": sim_res.idle_ms,
        "decisions": sim_res.decisions,
        "trace_events": len(sim_res.timeline),
        "trace_total_events": sim_res.decisions,
        "trace_truncated": sim_res.trace_truncated,
        "trace_limit": sim_res.trace_limit,
        "trace_window": {
            "start_ms": sim_res.timeline[0]["start_ms"] if sim_res.timeline else None,
            "end_ms": sim_res.timeline[-1]["end_ms"] if sim_res.timeline else None,
            "events": len(sim_res.timeline),
            "complete": not sim_res.trace_truncated,
        },
        "overview": {
            "start_ms": 0,
            "end_ms": sim_res.configured_horizon_ms,
            "buckets": sim_res.overview_buckets,
            "complete": True,
        },
        "task_counts": sim_res.task_counts,
        "per_class": {
            name: {
                "cpu_ms": st.cpu_ms,
                "max_wait_ms": st.max_wait_ms,
                "dispatches": st.dispatches,
                "share_pct": round(st.share_pct, 2),
            }
            for name, st in sim_res.per_class.items()
        },
        "timeline": sim_res.timeline,
        "workload": [
            {"class": t.cls, "count": t.count, "work_ms": t.work_ms, "arrival_ms": t.arrival_ms}
            for t in wl.tasks
        ],
    }


# ---------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------
@app.post("/api/compile")
def api_compile(req: SourceRequest):
    """Compiles SchedLang source through Lexer -> Parser -> Safety Pass -> IR with real stage timings."""
    res = compile_instrumented(req.source)
    stages = [
        {
            "name": s.name,
            "status": s.status,
            "duration_ms": s.duration_ms,
            "details": s.details,
            "output_summary": s.output_summary,
        }
        for s in res.stages
    ]

    if res.syntax_error:
        return {
            "ok": False,
            "stage": "syntax_error",
            "error": res.syntax_error,
            "line": res.syntax_line,
            "col": res.syntax_col,
            "diagnostics": _diagnostics_to_dict(res),
            "diagnostic_status": "FAILED",
            "ir": None,
            "ast": None,
            "stages": stages,
            "total_duration_ms": res.total_duration_ms,
            "tokens_count": res.tokens_count,
            "summary": f"Syntax Error: {res.syntax_error}",
        }

    diags = _diagnostics_to_dict(res)

    if not res.ok or res.ir is None:
        return {
            "ok": False,
            "stage": "safety_pass",
            "diagnostics": diags,
            "diagnostic_status": "FAILED",
            "ir": None,
            "ast": _ast_to_dict(res.ast) if res.ast else None,
            "stages": stages,
            "total_duration_ms": res.total_duration_ms,
            "tokens_count": res.tokens_count,
            "summary": f"Rejected by safety pass: {len(diags)} diagnostic violation(s)",
        }

    return {
        "ok": True,
        "stage": "complete",
        "diagnostics": [],
        "diagnostic_status": "SUCCESS",
        "ir": _ir_to_dict(res.ir),
        "ast": _ast_to_dict(res.ast) if res.ast else None,
        "stages": stages,
        "total_duration_ms": res.total_duration_ms,
        "tokens_count": res.tokens_count,
        "summary": f"Successfully compiled policy '{res.ir.name}' ({len(res.ir.classes)} classes, {len(res.ir.guarantees)} guarantees in {res.total_duration_ms:.2f}ms)",
    }


@app.post("/api/run")
def api_run(req: SourceRequest):
    """Executes a full research run with real stage telemetry, Z3 proofs, and simulation, saving an immutable run snapshot."""
    cres = compile_instrumented(req.source)
    stages = [
        {
            "name": s.name,
            "status": s.status,
            "duration_ms": s.duration_ms,
            "details": s.details,
            "output_summary": s.output_summary,
        }
        for s in cres.stages
    ]

    compile_data = {
        "ok": cres.ok,
        "total_duration_ms": cres.total_duration_ms,
        "stages": stages,
        "diagnostics": _diagnostics_to_dict(cres),
        "diagnostic_status": "FAILED" if not cres.ok else "SUCCESS",
        "ir": _ir_to_dict(cres.ir) if cres.ir else None,
        "ast": _ast_to_dict(cres.ast) if cres.ast else None,
        "tokens_count": cres.tokens_count,
        "summary": f"Compiled in {cres.total_duration_ms:.2f}ms" if cres.ok else "Compilation failed",
    }

    check_data = {"verdicts": [], "all_verified": False, "has_violation": False,
                  "has_unknown": False, "analysis_status": "NOT_RUN"}
    analyze_data = {"facts": {}}
    sim_data = {}
    codegen_data = {}
    policy_name = cres.ir.name if cres.ir else "unnamed_policy"

    if cres.ok and cres.ir:
        # Z3 Guarantee Verification
        try:
            verdicts = check_all(cres.ir, replay=True)
            v_dicts = [v.to_dict() for v in verdicts]
            check_data = {
                "verdicts": v_dicts,
                "all_verified": bool(verdicts and all(v.status == "VERIFIED" for v in verdicts)),
                "has_violation": any(v.status == "VIOLATED" for v in verdicts),
                "has_unknown": any(v.status == "UNKNOWN" for v in verdicts),
                "analysis_status": "COMPLETED",
            }
        except Exception as exc:
            check_data = {"verdicts": [], "all_verified": False, "has_violation": False,
                          "has_unknown": False, "analysis_status": "ERROR",
                          "analysis_error": str(exc)}
            verdicts = []
        check_data["aggregate"] = aggregate_verdicts(
            check_data["verdicts"], check_data.get("analysis_status"), check_data.get("analysis_error")
        )

        # Analyzer facts
        analyze_data = {"facts": analyze(cres.ir)}

        # Simulation with trace
        wl = _parse_workload(None, cres.ir)
        sim_res = simulate(cres.ir, wl, horizon_ms=10000, record_trace=True, max_trace_events=800)
        sim_data = _sim_to_dict(sim_res, wl)

        # eBPF C codegen snapshot. Unsupported runtime semantics are recorded
        # in the run instead of turning an otherwise valid formal run into a
        # misleading success or an unhandled server error.
        try:
            codegen_data = emit_ebpf_c(cres.ir).to_dict()
        except ValueError as exc:
            codegen_data = {"status": "UNSUPPORTED", "status_label": "UNSUPPORTED",
                            "c_code": "", "limitations": [str(exc)],
                            "unsupported_semantics": [str(exc)]}

    record = create_run_record(
        source_code=req.source,
        policy_name=policy_name,
        compile_data=compile_data,
        check_data=check_data,
        analyze_data=analyze_data,
        sim_data=sim_data,
        codegen_data=codegen_data,
    )
    return record


@app.get("/api/runs")
def api_runs(limit: int = 20):
    """Returns recent experimental runs for the Research Overview table."""
    return {"runs": list_runs(limit=limit)}


@app.get("/api/run/{run_id}")
def api_get_run(run_id: str):
    """Returns the immutable snapshot of a specific historical run."""
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    check = run.setdefault("check", {})
    check.setdefault("aggregate", aggregate_verdicts(
        check.get("verdicts", []),
        check.get("analysis_status") or ("COMPLETED" if run.get("compile", {}).get("ok") else "NOT_RUN"),
        check.get("analysis_error"),
    ))
    return run


@app.get("/api/run/{run_id}/pdf")
def api_run_pdf(run_id: str):
    """Generates and downloads a valid academic PDF report for the specified run."""
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    try:
        pdf_bytes = generate_run_pdf(run)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {e}")

    filename = f"schedlang_{run['policy_name']}_{run_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "application/pdf",
        },
    )


@app.post("/api/check")
def api_check(req: CheckRequest):
    """Formally verifies policy guarantees using Z3 with simulator replay."""
    res = compile_source(req.source)
    if not res.ok or res.ir is None:
        raise HTTPException(status_code=400, detail="Cannot verify policy: compilation/safety errors exist")

    verdicts = check_all(res.ir, replay=req.replay)
    v_dicts = [v.to_dict() for v in verdicts]

    all_verified = bool(verdicts and all(v.status == "VERIFIED" for v in verdicts))
    has_violation = any(v.status == "VIOLATED" for v in verdicts)
    has_unknown = any(v.status == "UNKNOWN" for v in verdicts)

    aggregate = aggregate_verdicts(
        [v.to_dict() for v in verdicts],
        "COMPLETED" if verdicts else ("COMPLETED" if res.ok else "NOT_RUN"),
    )
    return {
        "ok": True,
        "policy_name": res.ir.name,
        "verdicts": v_dicts,
        "all_verified": all_verified,
        "has_violation": has_violation,
        "has_unknown": has_unknown,
        "verification": aggregate,
        "guarantee_count": len(verdicts),
    }


@app.post("/api/analyze")
def api_analyze(req: SourceRequest):
    """Computes closed-form tightest worst-case wait bound and guaranteed min share."""
    res = compile_source(req.source)
    if not res.ok or res.ir is None:
        raise HTTPException(status_code=400, detail="Cannot analyze policy: compilation errors exist")

    facts = analyze(res.ir)
    return {
        "ok": True,
        "policy_name": res.ir.name,
        "facts": facts,
    }


@app.post("/api/simulate")
def api_simulate(req: SimulateRequest):
    """Runs single-CPU discrete-event simulation and returns metrics + execution timeline."""
    res = compile_source(req.source)
    if not res.ok or res.ir is None:
        raise HTTPException(status_code=400, detail="Cannot simulate policy: compilation errors exist")

    try:
        wl = _parse_workload(req.workload, res.ir)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid workload specification: {e}")

    sim_res = simulate(
        res.ir,
        wl,
        horizon_ms=req.horizon_ms,
        record_trace=req.record_trace,
        max_trace_events=req.max_trace_events,
    )

    return {
        "ok": True,
        "policy_name": res.ir.name,
        **_sim_to_dict(sim_res, wl),
    }


@app.post("/api/compare_sim")
def api_compare_sim(req: CompareSimRequest):
    """Runs two policies on identical workload for direct comparative analysis."""
    r_a = compile_source(req.policy_a)
    r_b = compile_source(req.policy_b)
    if not r_a.ok or not r_b.ok or r_a.ir is None or r_b.ir is None:
        raise HTTPException(status_code=400, detail="One or both policies failed to compile")

    wl = _parse_workload(req.workload, r_a.ir)
    sim_a = simulate(r_a.ir, wl, horizon_ms=req.horizon_ms, record_trace=True, max_trace_events=600)
    sim_b = simulate(r_b.ir, wl, horizon_ms=req.horizon_ms, record_trace=True, max_trace_events=600)

    return {
        "ok": True,
        "policy_a": {
            "name": r_a.ir.name,
            **_sim_to_dict(sim_a, wl),
        },
        "policy_b": {
            "name": r_b.ir.name,
            **_sim_to_dict(sim_b, wl),
        },
    }


@app.post("/api/infer")
def api_infer(req: InferRequest):
    """Feature 1 pipeline: Propose formal guarantees -> schema gate -> Z3 verification."""
    res = compile_source(req.source)
    if not res.ok or res.ir is None:
        raise HTTPException(status_code=400, detail="Cannot infer guarantees: compilation errors exist")

    intent = req.intent
    if not intent:
        intent_path = ROOT_DIR / "intents" / "web_batch.json"
        if intent_path.exists():
            with open(intent_path, encoding="utf-8") as f:
                intent = json.load(f)
        else:
            intent = {"goal": "Ensure interactive responsiveness and prevent batch starvation"}

    try:
        provider = get_provider(req.provider)
    except ProviderFailure as exc:
        return provider_error_response("infer_guarantees", req.provider, exc)
    rep = infer(res.ir, intent, provider)
    return rep.to_dict()


@app.post("/api/generate")
def api_generate(req: GenerateRequest):
    """Translates plain-English scheduling intent into candidate SchedLang DSL policy."""
    res = propose_policy(req.prompt, provider_name=req.provider)
    if res.status == "PROVIDER_ERROR":
        return provider_error_response("generate_policy", req.provider, proposal_provider_failure(res.to_dict()))
    return res.to_dict()


@app.post("/api/synthesize")
def api_synthesize(req: SynthesisRequest):
    """Run the real proposal -> validation -> bounded repair workflow."""
    if req.provider not in {"stub", "rules", "anthropic", "openrouter"}:
        raise HTTPException(status_code=400, detail="provider must be stub, rules, anthropic, or openrouter")
    try:
        result = synthesize_policy(req.prompt, provider_name=req.provider, repair=req.repair,
                                   clarification_answer=req.clarification_answer)
        payload = result.to_dict()
        if payload["proposal"].get("status") == "PROVIDER_ERROR":
            return provider_error_response("synthesize_policy", req.provider,
                                           proposal_provider_failure(payload["proposal"]))
        return payload
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/classify")
def api_classify(req: SourceRequest):
    """Compile, verify, and classify only formally violated guarantees."""
    try:
        res = compile_source(req.source)
    except DSLError as exc:
        raise HTTPException(status_code=400, detail=f"Policy syntax error: {exc}") from exc
    if not res.ok or res.ir is None:
        raise HTTPException(status_code=400, detail="Policy failed compilation or safety validation")
    verdicts = check_all(res.ir)
    classifications = [classify_violation(res.ir, v).to_dict()
                       for v in verdicts if v.status == "VIOLATED"]
    return {"ok": True, "policy_name": res.ir.name,
            "verdicts": [v.to_dict() for v in verdicts],
            "classifications": classifications,
            "status": "NOT_RUN" if not verdicts else ("VIOLATED" if classifications else
                     ("UNKNOWN" if any(v.status == "UNKNOWN" for v in verdicts) else "VERIFIED"))}


@app.post("/api/repair")
def api_repair(req: RepairRequest):
    """Run the bounded repair loop; final success is verifier-authoritative."""
    if req.feedback not in {"raw", "template", "ai", "heuristic"}:
        raise HTTPException(status_code=400, detail="unsupported feedback method")
    try:
        return repair_policy(req.source, feedback=req.feedback).to_dict()
    except DSLError as exc:
        raise HTTPException(status_code=400, detail=f"Policy syntax error: {exc}") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/adapt")
def api_adapt(req: AdaptRequest):
    """Adaptive parameter tuner exploring parameter space and verifying candidates."""
    res = compile_source(req.source)
    if not res.ok or res.ir is None:
        raise HTTPException(status_code=400, detail="Cannot run tuner: compilation errors exist")

    tune_res = tune_policy(
        res.ir,
        target_class=req.target_class,
        param=req.param,
        min_val=req.range_min,
        max_val=req.range_max,
        num_steps=req.num_steps,
    )
    return tune_res.to_dict()


@app.post("/api/codegen")
def api_codegen(req: SourceRequest):
    """Emit sched_ext C; emission does not claim compilation or loading."""
    res = compile_source(req.source)
    if not res.ok or res.ir is None:
        raise HTTPException(status_code=400, detail="Cannot generate C: compilation errors exist")

    try:
        cg_res = emit_ebpf_c(res.ir)
    except ValueError as exc:
        reason = str(exc)
        return JSONResponse(status_code=400, content={
            "c_code": "",
            "policy_name": res.ir.name,
            "is_complete": False,
            "status": "UNSUPPORTED",
            "status_label": "UNSUPPORTED",
            "unsupported_semantics": [reason],
            "limitations": [reason],
            "detail": reason,
        })
    return cg_res.to_dict()


@app.get("/api/phase4/preflight")
def api_phase4_preflight(vmlinux_header: Optional[str] = None, scx_header: Optional[str] = None):
    """Read-only host/toolchain inspection; never loads a scheduler."""
    return {"runtime": preflight().to_dict(), "toolchain": check_toolchain(vmlinux_header, scx_header).to_dict()}


@app.post("/api/phase4/build")
def api_phase4_build(req: BuildRequest):
    """Build generated source only when a caller supplies a real Linux toolchain."""
    root = ROOT_DIR.resolve()
    source_path = (root / "build" / "generated.schedguard.c").resolve()
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(req.source, encoding="utf-8")
    output = (root / req.output).resolve()
    try:
        output.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="build output must remain inside repository") from exc
    return build_ebpf(source_path, output, req.vmlinux_header, req.scx_header).to_dict()


@app.get("/api/phase4/lifecycle")
def api_phase4_lifecycle():
    """Return safe default lifecycle state and current read-only preflight."""
    state = LifecycleState()
    return {"state": state.to_dict(), "preflight": preflight().to_dict(),
            "load_policy": "NOT_RUN: explicit Linux VM authorization required"}


@app.get("/api/examples")
def api_examples():
    """Return bundled examples plus allowlisted, workflow-focused demo cases."""
    examples_dir = ROOT_DIR / "examples"
    demo_dir = pathlib.Path(__file__).resolve().parent / "demo_policies"
    examples = []
    descriptions = {
        "aging_fix": "Priority + aging bounds batch wait time and prevents starvation.",
        "strict_starves": "Strict priority without aging: continuously runnable web starves batch.",
        "balanced": "Same-tier classes: shares follow quanta round-robin without starvation.",
        "three_tier": "Three tiers with real-time, web, and slow ML aging.",
        "invalid_ranges": "Intentionally malformed ranges rejected by compiler safety pass.",
        "repairable_tight_wait": "Tight but feasible repair: 230 ms initial bound is reduced to 200 ms by aging 20 ms.",
        "sched_ext_multiclass_aging": "Opt-in multi-class sched_ext emission with kind-based task mapping and bounded aging promotion.",
    }

    for p in sorted(examples_dir.glob("*.sched")):
        name = p.stem
        with open(p, encoding="utf-8") as f:
            code = f.read()
        demo_id = {
            "aging_fix": "verified-aging-baseline",
            "repairable_tight_wait": "repairable-tight-wait",
            "sched_ext_multiclass_aging": "sched-ext-multiclass-aging",
        }.get(name)
        examples.append({
            "name": name,
            "filename": p.name,
            "description": descriptions.get(name, "Example scheduling policy"),
            "code": code,
            "demo_id": demo_id,
            "demo_kind": "baseline" if demo_id else "reference",
        })

    demo_specs = [
        ("repairable-starvation", "repairable_starvation.sched", "Repairable starvation: initial VIOLATED, deterministic aging repair reaches VERIFIED.", "repair"),
        ("no-guarantees", "no_guarantees.sched", "Valid policy with no declarations: expected NO_GUARANTEES, never false VERIFIED.", "negative"),
        ("sched-ext-smoke-supported", "sched_ext_smoke_supported.sched", "Smallest supported sched_ext source-emission smoke test.", "sched_ext"),
        ("sched-ext-unsupported-policy", "sched_ext_unsupported_policy.sched", "Expected UNSUPPORTED sched_ext multi-class policy; no fallback C is emitted.", "negative"),
    ]
    for demo_id, filename, description, demo_kind in demo_specs:
        path = demo_dir / filename
        if not path.is_file():
            continue
        examples.append({
            "name": path.stem,
            "filename": filename,
            "description": description,
            "code": path.read_text(encoding="utf-8"),
            "demo_id": demo_id,
            "demo_kind": demo_kind,
        })

    # Default workload
    workload_path = ROOT_DIR / "workloads" / "web_batch.json"
    workload = {}
    if workload_path.exists():
        with open(workload_path, encoding="utf-8") as f:
            workload = json.load(f)

    return {
        "examples": examples,
        "default_workload": workload,
    }


@app.get("/api/source_files")
def api_source_files():
    """Lists repository implementation files for the Source-Code Explorer."""
    curated = [
        {"path": "src/schedguard/dsl/lexer.py", "title": "DSL Lexer (Regex Tokens)", "component": "Compiler Frontend", "lines": 58},
        {"path": "src/schedguard/dsl/parser.py", "title": "LL(1) Recursive Descent Parser", "component": "Compiler Frontend", "lines": 125},
        {"path": "src/schedguard/verify/safety.py", "title": "Safety & Bounds Pass (E001-E013)", "component": "Semantic Validation", "lines": 58},
        {"path": "src/schedguard/ir/lower.py", "title": "Syntax-Directed IR Lowering", "component": "Intermediate Representation", "lines": 18},
        {"path": "src/schedguard/ir/ir.py", "title": "Fixed-Size IR Data Structures", "component": "Intermediate Representation", "lines": 64},
        {"path": "src/schedguard/verify/model.py", "title": "Closed-Form Wait Bound (NUM & SMT)", "component": "Formal Guarantee Verifier", "lines": 80},
        {"path": "src/schedguard/verify/properties.py", "title": "Z3 Property Verifier & Replay", "component": "Formal Guarantee Verifier", "lines": 111},
        {"path": "src/schedguard/sim/simulator.py", "title": "Single-CPU Discrete-Event Simulator", "component": "Simulator & Replay", "lines": 116},
        {"path": "src/schedguard/inference/schema.py", "title": "Property Library & Schema Gate", "component": "AI Proposal Gate", "lines": 81},
        {"path": "src/schedguard/inference/pipeline.py", "title": "AI Propose -> Gate -> Verify Loop", "component": "AI Proposal Gate", "lines": 49},
        {"path": "src/schedguard/adapt.py", "title": "Adaptive Parameter Tuner", "component": "Adaptive Tuner", "lines": 160},
        {"path": "src/schedguard/codegen/backend.py", "title": "Audited sched_ext C Emitter", "component": "Backend Codegen", "lines": 180},
    ]
    return {"files": curated}


@app.get("/api/source_file")
def api_source_file(path: str = Query(..., description="Relative path within repository")):
    """Returns real source code from the repository with metadata and line numbers."""
    # Security check: resolve and prevent traversal outside root
    target = (ROOT_DIR / path).resolve()
    try:
        target.relative_to(ROOT_DIR)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied: path outside workspace root")

    # Disallow reading secrets, hidden files or virtual environments
    if target.name.startswith(".") or "secret" in target.name.lower() or "env" in target.name.lower():
        raise HTTPException(status_code=403, detail="Access denied: restricted file")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"File '{path}' not found")

    with open(target, encoding="utf-8") as f:
        content = f.read()

    return {
        "path": path,
        "filename": target.name,
        "content": content,
        "line_count": len(content.splitlines()),
        "byte_size": target.stat().st_size,
    }


@app.get("/api/metrics")
def api_metrics():
    """Return actual experiment results, preferring the Phase 3 benchmark."""
    paths = [
        ("phase3", ROOT_DIR / "experiments" / "results" / "phase3_metrics.json"),
        ("phase2", ROOT_DIR / "experiments" / "results" / "phase2_metrics.json"),
        ("phase1", ROOT_DIR / "experiments" / "results" / "phase1_metrics.json"),
    ]
    for phase, metrics_path in paths:
        if metrics_path.exists():
            try:
                with open(metrics_path, encoding="utf-8") as f:
                    return {"ok": True, "phase": phase, "data": json.load(f)}
            except (OSError, json.JSONDecodeError) as exc:
                raise HTTPException(status_code=500, detail=f"Malformed {phase} metrics file") from exc
    return {"ok": False, "phase": None, "data": None,
            "message": "No experiment results are available. Run the documented metrics experiment."}


@app.get("/api/progress")
def api_progress():
    """Returns implementation status without treating unrun kernel work as complete."""
    return {
        "overall_completion_pct": None,
        "status_statement": "Core research features are implemented; Linux sched_ext runtime evidence is not run.",
        "phases": [
            {
                "phase": 1,
                "title": "Foundation + Feature 1",
                "weight_pct": 25,
                "status": "COMPLETED",
                "scope": "PolicyLang compiler, safety pass, fixed-size IR, Z3 verifier, discrete-event simulator with replay, AI guarantee schema gate, and offline rule baseline.",
                "verified_exit_criteria": "Regression suite and documented simulator soundness experiment are available; see experiment provenance.",
            },
            {
                "phase": "1b",
                "title": "Rule-vs-LLM Inference Harness",
                "weight_pct": 5,
                "status": "IMPLEMENTED_LIVE_NOT_RUN",
                "scope": "Evaluation harness comparing rule table baseline vs real LLM across 12+ intents with variance analysis.",
                "verified_exit_criteria": "Harness and offline baseline are implemented; a live-provider evaluation requires explicit credentials and opt-in.",
            },
            {
                "phase": 2,
                "title": "Feature 2: Adversarial Workloads",
                "weight_pct": 25,
                "status": "COMPLETED",
                "scope": "Simulator v2 for bursty/blocking tasks, random + hill-climbing attackers, structured attacker interface, and counterfactual gate.",
                "verified_exit_criteria": "Implemented and evaluated with recorded offline experiment artifacts; live LLM runs are separately labelled.",
            },
            {
                "phase": 3,
                "title": "Feature 3: Violation Explanation & Repair",
                "weight_pct": 20,
                "status": "COMPLETED",
                "scope": "Cause taxonomy for counterexamples, bounded repair loop, synthesis integration, and comparative offline baselines.",
                "verified_exit_criteria": "Implemented with a benchmark corpus; live-provider results remain opt-in and distinct from offline results.",
            },
            {
                "phase": 4,
                "title": "Feature 4: sched_ext Backend & Error Predictor",
                "weight_pct": 25,
                "status": "EXPERIMENTAL_NOT_RUN",
                "scope": "Bounded C emission, build/preflight interfaces, lifecycle/watchdog state, real-trace schema, predictor interface, and conservative gate integration.",
                "verified_exit_criteria": "Not run: Linux 6.12+ VM compilation, load, telemetry, and learned-predictor validation require explicitly authorized real-kernel evidence.",
            },
        ],
        "components": [
            {"name": "PolicyLang Lexer & LL(1) Parser", "status": "Implemented & Tested", "color": "emerald"},
            {"name": "Safety Pass (Codes E001-E013)", "status": "Implemented & Tested", "color": "emerald"},
            {"name": "Fixed-Size IR Construction", "status": "Implemented & Tested", "color": "emerald"},
            {"name": "Z3 Closed-Form Wait Bound Verifier", "status": "Implemented & Tested", "color": "emerald"},
            {"name": "Single-CPU Discrete-Event Simulator", "status": "Implemented & Tested", "color": "emerald"},
            {"name": "Counterexample Replay Engine", "status": "Implemented & Tested", "color": "emerald"},
            {"name": "AI Property Schema Gate", "status": "Implemented & Tested", "color": "emerald"},
            {"name": "Adaptive Parameter Range Tuner", "status": "Implemented & Tested", "color": "emerald"},
            {"name": "eBPF sched_ext C Emitter", "status": "Experimental; emission only", "color": "amber"},
            {"name": "Multi-Intent LLM Evaluation (1b)", "status": "Implemented; live calls not run", "color": "amber"},
            {"name": "Adversarial Workload Generator", "status": "Implemented & Tested", "color": "emerald"},
            {"name": "Policy Synthesis & Repair Agent", "status": "Implemented & Tested", "color": "emerald"},
            {"name": "Linux Kernel sched_ext Live Loader", "status": "Not run; explicit Linux VM workflow", "color": "slate"},
            {"name": "Learned Simulator Error Predictor", "status": "Not run; no paired real traces", "color": "slate"},
        ],
    }


# ---------------------------------------------------------
# Web Studio Static Files
# ---------------------------------------------------------
if STUDIO_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STUDIO_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def serve_studio():
        index_file = STUDIO_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return HTMLResponse("<h2>SchedLang Studio initializing...</h2>")
