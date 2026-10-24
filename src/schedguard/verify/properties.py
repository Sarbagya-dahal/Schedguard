"""Property checker: proves (or refutes with a counterexample workload) the
guarantees of a policy over ALL workloads with 0..max_tasks tasks per class,
using Z3 over linear integer arithmetic. Counterexamples are replayed in the
simulator; a violation reported as CONFIRMED has been reproduced concretely."""
import time
import threading
from functools import wraps
from dataclasses import dataclass, field
import z3
from ..ir import IRPolicy, IRGuarantee
from ..limits import INF
from ..sim import simulate, Workload
from .model import wait_bound, share_lower_bound_holds, SMT


# The supported Z3 Python/runtime combinations are not reliably re-entrant
# across concurrent Optimize/Solver calls sharing the process context. The
# verifier is CPU-bound and bounded, so serialize solver operations rather
# than allowing frontend requests to corrupt the native Z3 context.
_Z3_LOCK = threading.RLock()


def _serialized_z3(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with _Z3_LOCK:
            return fn(*args, **kwargs)
    return wrapped


@dataclass
class Verdict:
    guarantee: IRGuarantee
    status: str                      # VERIFIED | VIOLATED | UNKNOWN
    counterexample: dict[str, int] | None = None
    replay: str = ""                 # human-readable replay outcome
    evidence: str = "none"            # confirmed_replay | solver_candidate | not_reproduced | none
    elapsed_ms: float = 0.0

    def to_dict(self):
        return {
            "guarantee": self.guarantee.pretty(),
            "kind": getattr(self.guarantee, "kind", ""),
            "class_name": getattr(self.guarantee, "cls_name", ""),
            "value": getattr(self.guarantee, "value", 0),
            "status": self.status,
            "counterexample": self.counterexample,
            "replay": self.replay,
            "evidence": self.evidence,
            "elapsed_ms": round(self.elapsed_ms, 2),
        }


def _vars_and_domain(ir: IRPolicy, i: int):
    n = [z3.Int(f"n_{c.name}") for c in ir.classes]
    dom = [z3.And(v >= 0, v <= ir.max_tasks) for v in n] + [n[i] >= 1]
    return n, dom


def _replay_horizon(ir: IRPolicy, counts: dict[str, int]) -> int:
    rnd = sum(counts.get(c.name, 0) * c.quantum_ms for c in ir.classes)
    age = max([c.aging_ms for c in ir.classes] + [0])
    return int(min(400_000, max(30_000, 6 * rnd + 6 * age)))


@_serialized_z3
def check_guarantee(ir: IRPolicy, g: IRGuarantee, replay: bool = True) -> Verdict:
    t0 = time.perf_counter()
    i = g.cls_idx
    n, dom = _vars_and_domain(ir, i)
    s = z3.Solver()
    s.add(*dom)
    if g.kind == "no_starvation":
        s.add(wait_bound(ir, i, n, SMT) > g.value)
    else:
        s.add(z3.Not(share_lower_bound_holds(ir, i, n, g.value, SMT)))
    chk = s.check()
    if chk == z3.unsat:
        return Verdict(g, "VERIFIED", elapsed_ms=(time.perf_counter() - t0) * 1e3)
    if chk != z3.sat:
        return Verdict(g, "UNKNOWN", replay="solver returned unknown or inconclusive",
                       evidence="solver_inconclusive",
                       elapsed_ms=(time.perf_counter() - t0) * 1e3)
    m = s.model()
    cex = {c.name: m.eval(n[c.idx], model_completion=True).as_long() for c in ir.classes}
    v = Verdict(g, "UNKNOWN", cex, evidence="solver_candidate")
    if replay:
        res = simulate(ir, Workload.from_counts(cex), _replay_horizon(ir, cex))
        st = res.per_class[g.cls_name]
        if g.kind == "no_starvation":
            confirmed = st.max_wait_ms > g.value
            v.replay = f"simulated max wait {st.max_wait_ms}ms vs bound {g.value}ms"
        else:
            confirmed = st.share_pct < g.value
            v.replay = f"simulated share {st.share_pct:.1f}% vs required {g.value}%"
        if confirmed:
            v.status = "VIOLATED"
            v.evidence = "confirmed_replay"
        else:
            v.evidence = "not_reproduced"
            v.replay += " (not reproduced: analysis is conservative here)"
    v.elapsed_ms = (time.perf_counter() - t0) * 1e3
    return v


@_serialized_z3
def tightest_wait_bound(ir: IRPolicy, i: int) -> int | None:
    """Largest provable worst-case wait over all workloads (None = unbounded)."""
    n, dom = _vars_and_domain(ir, i)
    o = z3.Optimize()
    o.add(*dom)
    h = o.maximize(wait_bound(ir, i, n, SMT))
    if o.check() != z3.sat:
        return None
    val = h.upper().as_long() if hasattr(h.upper(), "as_long") else INF
    return None if val >= INF else val


@_serialized_z3
def guaranteed_min_share(ir: IRPolicy, i: int) -> int:
    """Largest integer percent P such that min_share(class, P) is provable."""
    lo, hi = 0, 100
    while lo < hi:
        mid = (lo + hi + 1) // 2
        g = IRGuarantee("min_share", i, ir.classes[i].name, mid)
        if check_guarantee(ir, g, replay=False).status == "VERIFIED":
            lo = mid
        else:
            hi = mid - 1
    return lo


def analyze(ir: IRPolicy) -> dict[str, dict]:
    return {c.name: {"tightest_wait_ms": tightest_wait_bound(ir, c.idx),
                     "guaranteed_min_share_pct": guaranteed_min_share(ir, c.idx),
                     "prio": c.prio, "quantum_ms": c.quantum_ms,
                     "aging_ms": c.aging_ms or None, "kind": c.kind or None}
            for c in ir.classes}


def check_all(ir: IRPolicy, replay: bool = True) -> list[Verdict]:
    return [check_guarantee(ir, g, replay) for g in ir.guarantees]
