import argparse, json, sys
from .compiler import compile_file
from .dsl import DSLError
from .verify.properties import check_all, analyze
from .sim import simulate, Workload


def _load(path):
    try:
        res = compile_file(path)
    except FileNotFoundError:
        print(f"error: policy file not found: {path}", file=sys.stderr); raise SystemExit(2)
    except OSError as e:
        print(f"error: cannot read policy file '{path}': {e}", file=sys.stderr); raise SystemExit(2)
    except DSLError as e:
        print(f"syntax error: {e}", file=sys.stderr); raise SystemExit(2)
    if not res.ok:
        for d in res.diagnostics:
            print(f"safety error {d}", file=sys.stderr)
        raise SystemExit(2)
    return res.ir


def cmd_ir(a):
    print(_load(a.policy).dump())


def cmd_check(a):
    ir = _load(a.policy)
    vs = check_all(ir)
    if a.json:
        print(json.dumps([v.to_dict() for v in vs], indent=2))
    else:
        for v in vs:
            print(f"{v.status:<9} {v.guarantee.pretty()}  ({v.elapsed_ms:.1f} ms)")
            if v.counterexample:
                print(f"          counterexample tasks/class: {v.counterexample}")
            if v.replay:
                print(f"          replay: {v.replay}")
        if not vs:
            print("policy declares no guarantees")
    raise SystemExit(0 if all(v.status == "VERIFIED" for v in vs) else 1)


def cmd_analyze(a):
    facts = analyze(_load(a.policy))
    if a.json:
        print(json.dumps(facts, indent=2)); return
    print(f"{'class':<10} {'worst-case wait':<17} {'guaranteed min share'}")
    for name, f in facts.items():
        w = "UNBOUNDED" if f["tightest_wait_ms"] is None else f"{f['tightest_wait_ms']} ms"
        print(f"{name:<10} {w:<17} {f['guaranteed_min_share_pct']}%")


def cmd_simulate(a):
    ir = _load(a.policy)
    try:
        wl = Workload.from_json(a.workload)
    except FileNotFoundError:
        print(f"error: workload file not found: {a.workload}", file=sys.stderr); raise SystemExit(2)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        print(f"error: invalid workload file '{a.workload}': {e}", file=sys.stderr); raise SystemExit(2)
    try:
        res = simulate(ir, wl, a.horizon)
    except KeyError as e:
        print(f"error: {e}", file=sys.stderr); raise SystemExit(2)
    print(f"simulated {res.horizon_ms} ms, {res.decisions} dispatches, idle {res.idle_ms} ms")
    for n, s in res.per_class.items():
        print(f"{n:<10} cpu={s.cpu_ms:>7} ms  share={s.share_pct:5.1f}%  max_wait={s.max_wait_ms} ms")


def cmd_infer(a):
    from .inference import infer
    from .inference.providers import get_provider
    ir = _load(a.policy)
    try:
        with open(a.intent, encoding="utf-8") as f:
            intent = json.load(f)
    except FileNotFoundError:
        print(f"error: intent file not found: {a.intent}", file=sys.stderr); raise SystemExit(2)
    except json.JSONDecodeError as e:
        print(f"error: invalid intent JSON '{a.intent}': {e}", file=sys.stderr); raise SystemExit(2)
    rep = infer(ir, intent, get_provider(a.provider))
    if a.json:
        print(json.dumps(rep.to_dict(), indent=2)); return
    print(f"source: {rep.source}" + (f"   error: {rep.error}" if rep.error else ""))
    for g, r in rep.rejected:
        print(f"REJECTED  {g}: {r}")
    for v in rep.verdicts:
        print(f"{v.status:<9} {v.guarantee.pretty()}  {v.replay}")
    print(f"{len(rep.verified)} verified / {len(rep.violated)} violated / {len(rep.verdicts)} proposed")


def cmd_attack(a):
    from .adversary.objectives import RegressionObjective
    from .adversary.attackers import RandomAttacker, HillClimbAttacker, LLMAttacker
    from .inference.providers import get_provider

    inc = _load(a.incumbent)
    cand = _load(a.candidate)

    if a.attacker == "hillclimb":
        atk = HillClimbAttacker()
    elif a.attacker == "llm":
        atk = LLMAttacker(provider=get_provider(a.provider))
    else:
        atk = RandomAttacker()

    target_cls = a.target_class
    if not target_cls:
        for c in inc.classes:
            if c.kind in ("interactive", "realtime"):
                target_cls = c.name
                break
        if not target_cls and inc.classes:
            target_cls = inc.classes[0].name

    obj = RegressionObjective(target_class=target_cls, metric_name=a.metric, tolerance=a.tolerance)
    res = atk.search(inc, cand, obj, budget=a.budget, horizon_ms=a.horizon)

    if a.json:
        print(json.dumps(res.to_dict(), indent=2))
        return

    print(f"Attacker: {res.attacker_name}  (simulations: {res.simulations_run}/{a.budget})")
    print(f"Regressions found: {res.regressions_found}")
    print(f"Best regression: {res.best_regression:.2f} (target: {target_cls}.{a.metric}, tolerance: {a.tolerance})")
    if res.worst_workload:
        print(f"Worst workload tasks: {res.worst_workload.to_dict()['tasks']}")


def cmd_gate(a):
    from .gate import evaluate_candidate
    from .adversary.attackers import RandomAttacker, HillClimbAttacker, LLMAttacker
    from .inference.providers import get_provider

    inc = _load(a.incumbent)
    cand = _load(a.candidate)

    if a.attacker == "hillclimb":
        atk = HillClimbAttacker()
    elif a.attacker == "llm":
        atk = LLMAttacker(provider=get_provider(a.provider))
    else:
        atk = RandomAttacker()

    dec = evaluate_candidate(
        incumbent=inc,
        candidate=cand,
        recorded_traces=a.traces_dir,
        budget=a.budget,
        tolerance=a.tolerance,
        attacker=atk,
        target_class=a.target_class,
        metric_name=a.metric,
        horizon_ms=a.horizon,
    )

    if a.json:
        print(json.dumps(dec.to_dict(), indent=2))
    else:
        status_color = dec.decision
        print(f"Gate Verdict: {status_color}")
        if dec.reasons:
            print("Reasons for rejection:")
            for r in dec.reasons:
                print(f"  - {r}")
        else:
            print("All static guarantees, recorded traces, and adversarial searches passed.")
        print(f"Traces evaluated: {len(dec.recorded_trace_results)}")
        if dec.worst_workload:
            print(f"Worst workload: {dec.worst_workload['tasks']}")
        print(f"Limitations note: {dec.limitations}")

    raise SystemExit(0 if dec.decision == "ACCEPT" else 1)


def cmd_studio(a):
    import uvicorn
    from .server import app
    print(f"Starting SchedLang Studio at http://{a.host}:{a.port}")
    uvicorn.run(app, host=a.host, port=a.port, log_level="info")


def main(argv=None):
    p = argparse.ArgumentParser(prog="schedguard")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("ir"); s.add_argument("policy"); s.set_defaults(f=cmd_ir)
    s = sub.add_parser("check"); s.add_argument("policy"); s.add_argument("--json", action="store_true"); s.set_defaults(f=cmd_check)
    s = sub.add_parser("analyze"); s.add_argument("policy"); s.add_argument("--json", action="store_true"); s.set_defaults(f=cmd_analyze)
    s = sub.add_parser("simulate"); s.add_argument("policy"); s.add_argument("workload")
    s.add_argument("--horizon", type=int, default=60_000); s.set_defaults(f=cmd_simulate)
    s = sub.add_parser("infer"); s.add_argument("policy"); s.add_argument("intent")
    s.add_argument("--provider", choices=["stub", "anthropic", "openrouter"], default=None)
    s.add_argument("--json", action="store_true"); s.set_defaults(f=cmd_infer)

    s = sub.add_parser("attack")
    s.add_argument("incumbent")
    s.add_argument("candidate")
    s.add_argument("--attacker", choices=["random", "hillclimb", "llm"], default="random")
    s.add_argument("--budget", type=int, default=30)
    s.add_argument("--metric", default="p99_dispatch_latency")
    s.add_argument("--class", dest="target_class", default=None)
    s.add_argument("--tolerance", type=float, default=5.0)
    s.add_argument("--horizon", type=int, default=10_000)
    s.add_argument("--provider", default=None)
    s.add_argument("--json", action="store_true")
    s.set_defaults(f=cmd_attack)

    s = sub.add_parser("gate")
    s.add_argument("incumbent")
    s.add_argument("candidate")
    s.add_argument("--traces-dir", default="traces")
    s.add_argument("--attacker", choices=["random", "hillclimb", "llm"], default="random")
    s.add_argument("--budget", type=int, default=30)
    s.add_argument("--metric", default="p99_dispatch_latency")
    s.add_argument("--class", dest="target_class", default=None)
    s.add_argument("--tolerance", type=float, default=5.0)
    s.add_argument("--horizon", type=int, default=10_000)
    s.add_argument("--provider", default=None)
    s.add_argument("--json", action="store_true")
    s.set_defaults(f=cmd_gate)

    s = sub.add_parser("studio")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(f=cmd_studio)
    a = p.parse_args(argv)
    return a.f(a)


if __name__ == "__main__":
    raise SystemExit(main())
