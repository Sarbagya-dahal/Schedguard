# SchedGuard (Phase 1 prototype)

Guarantee-carrying scheduling policies: a small policy DSL (**PolicyLang**) compiled to a fixed-size IR,
checked by a **safety pass** and a **Z3-based property verifier**, replayed in a **simulator**, with an
**AI proposer for formal guarantees** whose output is schema-gated and then proved or refuted.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=src:experiments
python -m pytest -q                                  # 71 tests
python -m schedguard check   examples/strict_starves.sched   # VIOLATED + counterexample + replay
python -m schedguard analyze examples/aging_fix.sched        # provable worst-case wait / min share
python -m schedguard simulate examples/aging_fix.sched workloads/web_batch.json
python -m schedguard infer   examples/aging_fix.sched intents/web_batch.json --provider stub
python -m schedguard attack  examples/aging_fix.sched examples/strict_starves.sched --attacker random
python -m schedguard gate    examples/aging_fix.sched examples/aging_fix.sched --traces-dir traces
python experiments/run_metrics.py                    # regenerates experiments/results/phase1_metrics.json
python experiments/eval_inference.py                 # runs Phase 1b rule-vs-LLM eval harness
python experiments/planted_regressions.py            # runs Phase 2 planted regression benchmark
python experiments/run_phase2_metrics.py             # runs Phase 2 multi-seed attacker metrics
```

### LLM Providers
- **OpenRouter (recommended)**:
  ```bash
  export OPENROUTER_API_KEY="your-openrouter-key"
  export SCHEDGUARD_MODEL="openai/gpt-4o-mini"   # or any OpenRouter model
  python -m schedguard infer examples/aging_fix.sched intents/web_batch.json --provider openrouter
  ```
- **Anthropic**:
  ```bash
  pip install anthropic
  export ANTHROPIC_API_KEY="your-anthropic-key"
  python -m schedguard infer examples/aging_fix.sched intents/web_batch.json --provider anthropic
  ```
- **Offline Mode**:
  If no API keys are set, `--provider stub` and the rule-table baseline work fully offline with zero external network access. All responses are strictly validated through `schema.validate` before reaching the Z3 verifier.

Read `AGENTS.md` first (architecture, invariants, next steps) and `docs/MODEL.md` (formal model).
