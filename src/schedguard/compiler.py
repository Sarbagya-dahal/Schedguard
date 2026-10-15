"""Front-end driver: source text -> AST -> safety pass -> IR."""
import time
from dataclasses import dataclass, field
from typing import Any
from .dsl import parse, DSLError
from .dsl.lexer import tokenize
from .dsl.parser import _Parser
from .ir import lower, IRPolicy
from .verify.safety import check, Diagnostic


@dataclass
class CompileResult:
    ir: IRPolicy | None
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.ir is not None and not self.diagnostics


@dataclass
class CompilerStageInfo:
    name: str                        # "Lexical Analysis", "Parsing & AST", "Safety Pass", "IR Lowering"
    status: str                      # "COMPLETED" | "FAILED" | "SKIPPED"
    duration_ms: float
    details: str
    output_summary: str = ""


@dataclass
class DetailedCompileResult:
    ir: IRPolicy | None
    ast: Any | None
    tokens_count: int
    diagnostics: list[Diagnostic] = field(default_factory=list)
    stages: list[CompilerStageInfo] = field(default_factory=list)
    total_duration_ms: float = 0.0
    syntax_error: str | None = None
    syntax_line: int = 0
    syntax_col: int = 0

    @property
    def ok(self) -> bool:
        return self.ir is not None and not self.diagnostics and not self.syntax_error


def compile_source(src: str) -> CompileResult:
    ast = parse(src)                       # raises DSLError on syntax errors
    diags = check(ast)
    return CompileResult(None if diags else lower(ast), diags)


def compile_file(path: str) -> CompileResult:
    with open(path, encoding="utf-8") as f:
        return compile_source(f.read())


def compile_instrumented(src: str) -> DetailedCompileResult:
    """Compiles source with real timing instrumentation for each compiler stage."""
    t_start = time.perf_counter()
    stages: list[CompilerStageInfo] = []
    tokens = []
    ast = None
    ir = None
    diags: list[Diagnostic] = []

    # 1. Lexical Analysis
    t0 = time.perf_counter()
    try:
        tokens = tokenize(src)
        dur1 = (time.perf_counter() - t0) * 1000.0
        stages.append(CompilerStageInfo(
            name="Lexical Analysis",
            status="COMPLETED",
            duration_ms=round(dur1, 2),
            details=f"Tokenized input into {len(tokens)} lexemes (keywords, identifiers, literals, punctuation).",
            output_summary=f"{len(tokens)} tokens"
        ))
    except DSLError as e:
        dur1 = (time.perf_counter() - t0) * 1000.0
        stages.append(CompilerStageInfo(
            name="Lexical Analysis",
            status="FAILED",
            duration_ms=round(dur1, 2),
            details=f"Lexical error: {e}",
            output_summary="Failed"
        ))
        stages.append(CompilerStageInfo("Parsing & AST", "SKIPPED", 0.0, "Skipped due to lexical error"))
        stages.append(CompilerStageInfo("Safety Pass", "SKIPPED", 0.0, "Skipped due to lexical error"))
        stages.append(CompilerStageInfo("IR Lowering", "SKIPPED", 0.0, "Skipped due to lexical error"))
        tot = (time.perf_counter() - t_start) * 1000.0
        return DetailedCompileResult(None, None, 0, [], stages, round(tot, 2), str(e), e.line, e.col)

    # 2. Parsing & AST Construction
    t0 = time.perf_counter()
    try:
        parser = _Parser(tokens)
        ast = parser.policy()
        dur2 = (time.perf_counter() - t0) * 1000.0
        stages.append(CompilerStageInfo(
            name="Parsing & AST",
            status="COMPLETED",
            duration_ms=round(dur2, 2),
            details=f"Constructed PolicyAST for '{ast.name}' with {len(ast.classes)} class declarations, "
                    f"{len(ast.guarantees)} guarantees, and max_tasks={ast.max_tasks or 16}.",
            output_summary=f"AST built: {len(ast.classes)} classes"
        ))
    except DSLError as e:
        dur2 = (time.perf_counter() - t0) * 1000.0
        stages.append(CompilerStageInfo(
            name="Parsing & AST",
            status="FAILED",
            duration_ms=round(dur2, 2),
            details=f"Syntax error: {e}",
            output_summary="Syntax error"
        ))
        stages.append(CompilerStageInfo("Safety Pass", "SKIPPED", 0.0, "Skipped due to syntax error"))
        stages.append(CompilerStageInfo("IR Lowering", "SKIPPED", 0.0, "Skipped due to syntax error"))
        tot = (time.perf_counter() - t_start) * 1000.0
        return DetailedCompileResult(None, None, len(tokens), [], stages, round(tot, 2), str(e), e.line, e.col)

    # 3. Semantic / Safety Pass
    t0 = time.perf_counter()
    diags = check(ast)
    dur3 = (time.perf_counter() - t0) * 1000.0
    if diags:
        codes = ", ".join(d.code for d in diags)
        stages.append(CompilerStageInfo(
            name="Safety Pass",
            status="FAILED",
            duration_ms=round(dur3, 2),
            details=f"Safety pass rejected AST with {len(diags)} diagnostic violation(s): {codes}.",
            output_summary=f"Rejected: {len(diags)} diagnostics"
        ))
        stages.append(CompilerStageInfo("IR Lowering", "SKIPPED", 0.0, "Skipped due to safety pass violations"))
        tot = (time.perf_counter() - t_start) * 1000.0
        return DetailedCompileResult(None, ast, len(tokens), diags, stages, round(tot, 2))
    else:
        stages.append(CompilerStageInfo(
            name="Safety Pass",
            status="COMPLETED",
            duration_ms=round(dur3, 2),
            details="All static semantic checks passed: class uniqueness, quantum ranges, priority tiers, and guarantee syntax.",
            output_summary="Passed (0 diagnostics)"
        ))

    # 4. IR Lowering
    t0 = time.perf_counter()
    ir = lower(ast)
    dur4 = (time.perf_counter() - t0) * 1000.0
    stages.append(CompilerStageInfo(
        name="IR Lowering",
        status="COMPLETED",
        duration_ms=round(dur4, 2),
        details=f"Lowered AST into fixed-size IRPolicy '{ir.name}' ({len(ir.classes)} classes, {len(ir.guarantees)} guarantees).",
        output_summary=f"IR: {len(ir.classes)} classes, {len(ir.guarantees)} guarantees"
    ))

    tot = (time.perf_counter() - t_start) * 1000.0
    return DetailedCompileResult(ir, ast, len(tokens), [], stages, round(tot, 2))

