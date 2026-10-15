"""Closed-form worst-case wait bound (the formal model; see docs/MODEL.md).

One definition, two backends: NUM (plain ints, used to cross-check the simulator)
and SMT (Z3 terms, used for proofs). Because both share this code, the numeric
and symbolic results cannot silently diverge.

Let n[j] = number of runnable CPU-bound tasks in class j, Q_j its quantum.
For class i (with n[i] >= 1):
  H  = sum_{prio_j <  prio_i} n_j Q_j            tasks in strictly higher tiers
  S  = sum_{prio_j == prio_i} n_j Q_j - Q_i      same-tier peers (incl. own class)
  G  = sum_{aging_j, prio_j > prio_i} n_j Q_j    lower-tier tasks that may be boosted ahead
  BA = sum_{aging_j, prio_j >= prio_i} n_j Q_j - Q_i
  higher = exists j with prio_j < prio_i and n_j >= 1
  W_i = INF                    if higher and class i has no aging   (starvation)
      = A_i + H + BA           if higher and class i has aging
      = S + G                  otherwise (class i is in the top populated tier)
W_i bounds the time between a task becoming ready and next being dispatched.
"""
import z3
from ..ir import IRPolicy
from ..limits import INF


class _Num:
    @staticmethod
    def ite(c, a, b): return a if c else b
    @staticmethod
    def or_(xs): return any(xs)
    @staticmethod
    def and_(a, b): return a and b
    @staticmethod
    def not_(a): return not a
    @staticmethod
    def ge1(x): return x >= 1
    @staticmethod
    def const(v): return v


class _Smt:
    @staticmethod
    def ite(c, a, b): return z3.If(c, a, b)
    @staticmethod
    def or_(xs): return z3.Or(*xs) if xs else z3.BoolVal(False)
    @staticmethod
    def and_(a, b): return z3.And(a, b)
    @staticmethod
    def not_(a): return z3.Not(a)
    @staticmethod
    def ge1(x): return x >= 1
    @staticmethod
    def const(v): return z3.IntVal(v)


NUM, SMT = _Num, _Smt


def wait_bound(ir: IRPolicy, i: int, n, B=NUM):
    cs = ir.classes
    ci = cs[i]
    qi = ci.quantum_ms
    term = lambda j: n[j] * cs[j].quantum_ms
    H = sum((term(j) for j in range(len(cs)) if cs[j].prio < ci.prio), B.const(0))
    S = sum((term(j) for j in range(len(cs)) if cs[j].prio == ci.prio), B.const(0)) - qi
    G = sum((term(j) for j in range(len(cs)) if cs[j].aging_ms and cs[j].prio > ci.prio), B.const(0))
    BA = sum((term(j) for j in range(len(cs)) if cs[j].aging_ms and cs[j].prio >= ci.prio), B.const(0)) - qi
    higher = B.or_([B.ge1(n[j]) for j in range(len(cs)) if cs[j].prio < ci.prio])
    if ci.aging_ms:
        inner = B.ite(higher, ci.aging_ms + H + BA, S + G)
        return inner
    return B.ite(higher, B.const(INF), S + G)


def share_lower_bound_holds(ir: IRPolicy, i: int, n, pct: int, B=NUM):
    """Claim: class i's long-run CPU share >= pct%. Each task is served >= one
    quantum per (W_i + Q_i) ms, so share >= n_i Q_i / (W_i + Q_i). Cross-multiplied
    to stay linear: 100 * n_i * Q_i >= pct * (W_i + Q_i)."""
    qi = ir.classes[i].quantum_ms
    w = wait_bound(ir, i, n, B)
    return 100 * n[i] * qi >= pct * (w + qi)
