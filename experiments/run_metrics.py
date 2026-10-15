"""Phase-1 metrics. Everything here is MEASURED by running the code; nothing is hand-entered.
Usage: PYTHONPATH=src python experiments/run_metrics.py"""
import glob, json, pathlib, random, statistics, subprocess, sys, time
sys.path.insert(0, "src"); sys.path.insert(0, "experiments")
import soundness
from schedguard.compiler import compile_file, compile_source
from schedguard.ir import IRGuarantee, IRPolicy, IRClass
from schedguard.sim import simulate, Workload
from schedguard.verify.properties import check_guarantee, check_all, analyze
from schedguard.inference import infer
from schedguard.inference.providers import StubProvider

OUT = pathlib.Path("experiments/results"); OUT.mkdir(parents=True, exist_ok=True)
M = {}

# 1. code size + tests
loc = sum(len([l for l in open(f, encoding="utf-8") if l.strip()]) for f in glob.glob("src/**/*.py", recursive=True))
M["loc_src_nonblank"] = loc
p = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header"], capture_output=True, text=True,
                   env={**__import__("os").environ, "PYTHONPATH": "src"})
M["pytest_summary"] = p.stdout.strip().splitlines()[-1]

# 2. example corpus: end-to-end latency (parse+safety+lower+Z3 verdicts)
rows = []
for f in sorted(glob.glob("examples/*.sched")):
    name = pathlib.Path(f).stem
    t0 = time.perf_counter()
    res = compile_file(f)
    t_front = (time.perf_counter() - t0) * 1e3
    if not res.ok:
        rows.append({"policy": name, "frontend_ms": round(t_front, 2), "outcome": "REJECTED by safety pass",
                     "diagnostics": [d.code for d in res.diagnostics]}); continue
    t0 = time.perf_counter(); vs = check_all(res.ir); t_ver = (time.perf_counter() - t0) * 1e3
    rows.append({"policy": name, "frontend_ms": round(t_front, 2), "verify_ms": round(t_ver, 1),
                 "verdicts": [v.status for v in vs]})
M["corpus"] = rows

# 3. verification latency vs. policy size (Z3 over all workloads up to 64 tasks/class)
scal = []
for k in (2, 4, 8, 16):
    cls = tuple(IRClass(i, f"c{i}", i % 4, 5 + 5 * (i % 3), 100 if i % 2 else 0, "") for i in range(k))
    ir = IRPolicy("scal", cls, (), 64)
    ts = []
    for _ in range(10):
        t0 = time.perf_counter()
        for c in ir.classes:
            check_guarantee(ir, IRGuarantee("no_starvation", c.idx, c.name, 5000), replay=False)
        ts.append((time.perf_counter() - t0) * 1e3 / k)
    scal.append({"classes": k, "ms_per_guarantee_mean": round(statistics.mean(ts), 2),
                 "ms_per_guarantee_max": round(max(ts), 2)})
M["scalability"] = scal

# 4. soundness differential test (bound vs simulator)
M["soundness"] = soundness.run(trials=2000, seed=11)

# 5. false-accept test: every VERIFIED guarantee is attacked with random workloads in the simulator
rng = random.Random(5)
verified = violated = unknown = attacks = false_accept = confirmed = 0
for _ in range(250):
    ir = soundness.random_policy(rng)
    c = rng.choice(ir.classes)
    g = (IRGuarantee("no_starvation", c.idx, c.name, rng.choice([50, 100, 200, 500, 1000, 3000])) if rng.random() < 0.6
         else IRGuarantee("min_share", c.idx, c.name, rng.choice([2, 5, 10, 25, 50])))
    v = check_guarantee(ir, g)
    if v.status == "VIOLATED": violated += 1; confirmed += 1
    elif v.status == "UNKNOWN": unknown += 1
    else:
        verified += 1
        for _ in range(4):
            counts = {x.name: rng.randint(0, ir.max_tasks) for x in ir.classes}
            counts[c.name] = max(1, counts[c.name])
            rnd = sum(counts[x.name] * x.quantum_ms for x in ir.classes)
            res = simulate(ir, Workload.from_counts(counts), min(200_000, max(20_000, 8 * rnd + 3000)))
            st = res.per_class[c.name]; attacks += 1
            bad = st.max_wait_ms > g.value if g.kind == "no_starvation" else st.share_pct + 1.0 < g.value
            false_accept += bad
M["verification_gate"] = {"random_guarantees": 250, "verified": verified, "violated_confirmed_by_replay": violated,
                          "unknown_conservative": unknown, "random_workload_attacks_on_verified": attacks,
                          "false_accepts": false_accept}

# 6. inference pipeline (offline stub; integration test, NOT an LLM result)
ir = compile_file("examples/aging_fix.sched").ir
rep = infer(ir, json.load(open("intents/web_batch.json")), StubProvider())
M["inference_pipeline_stub"] = {"proposed": len(rep.proposed), "rejected_by_schema": len(rep.rejected),
                                "verified": len(rep.verified), "violated": len(rep.violated),
                                "statuses": [v.status for v in rep.verdicts]}
(OUT / "phase1_metrics.json").write_text(json.dumps(M, indent=2))
print(json.dumps(M, indent=2))
