# SchedGuard (Phase 1 prototype)

Guarantee-carrying scheduling policies: a small policy DSL (**PolicyLang**) compiled to a fixed-size IR,
checked by a **safety pass** and a **Z3-based property verifier**, replayed in a **simulator**, with an
**AI proposer for formal guarantees** whose output is schema-gated and then proved or refuted.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=src
python -m pytest -q                                  # 27 tests
python -m schedguard check   examples/strict_starves.sched   # VIOLATED + counterexample + replay
python -m schedguard analyze examples/aging_fix.sched        # provable worst-case wait / min share
python -m schedguard simulate examples/aging_fix.sched workloads/web_batch.json
python -m schedguard infer   examples/aging_fix.sched intents/web_batch.json --provider stub
python experiments/run_metrics.py                    # regenerates experiments/results/phase1_metrics.json
```
Real LLM: `pip install anthropic`, set `ANTHROPIC_API_KEY`, then `--provider anthropic`.
Read `AGENTS.md` first (architecture, invariants, next steps) and `docs/MODEL.md` (formal model).
