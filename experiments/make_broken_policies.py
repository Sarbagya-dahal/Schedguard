"""Broken-policy dataset generator.

Generates >= 30 broken PolicyLang policies by mutating known-good policies.
Ground-truth causes directly reflect the mutation construction:
- NO_AGING (6 policies)
- AGING_TOO_SLOW (6 policies)
- OVERPROMISED_BOUND (5 policies)
- QUANTUM_IMBALANCE (5 policies)
- TIER_CONTENTION (5 policies)
- SHARE_INFEASIBLE (5 policies)

Verifies every policy genuinely violates its declared guarantee.
Outputs to experiments/broken_policies/ and experiments/broken_policies/labels.json.
"""
import json
import os
import pathlib
import sys
from typing import Any

sys.path.insert(0, "src")

from schedguard.compiler import compile_source
from schedguard.verify.properties import check_all


def generate_dataset(output_dir: str = "experiments/broken_policies") -> list[dict[str, Any]]:
    out_path = pathlib.Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    dataset_specs = []

    # 1. NO_AGING (6 policies)
    for i in range(1, 7):
        p_name = f"broken_no_aging_{i:02d}"
        bound = 300 + i * 50
        src = f"""// Mutation: batch has no aging, top tier starves it
policy {p_name} {{
  option max_tasks = 8;
  class web   {{ prio 0; quantum {5 + i} ms;  kind interactive; }}
  class batch {{ prio 1; quantum 20 ms;  kind batch; }}
  guarantee no_starvation(batch, {bound} ms);
}}
"""
        dataset_specs.append({
            "filename": f"{p_name}.sched",
            "name": p_name,
            "source": src,
            "ground_truth_cause": "NO_AGING",
            "target_class": "batch",
            "target_guarantee": f"no_starvation(batch, {bound} ms)",
            "description": "Lower-priority batch class has no aging and starves under load.",
        })

    # 2. AGING_TOO_SLOW (6 policies)
    for i in range(1, 7):
        p_name = f"broken_slow_aging_{i:02d}"
        aging_val = 500 + i * 100
        bound = 150 + i * 20
        src = f"""// Mutation: batch aging interval exceeds declared bound
policy {p_name} {{
  option max_tasks = 8;
  class web   {{ prio 0; quantum 5 ms;  kind interactive; }}
  class batch {{ prio 1; quantum 20 ms; aging {aging_val} ms; kind batch; }}
  guarantee no_starvation(batch, {bound} ms);
}}
"""
        dataset_specs.append({
            "filename": f"{p_name}.sched",
            "name": p_name,
            "source": src,
            "ground_truth_cause": "AGING_TOO_SLOW",
            "target_class": "batch",
            "target_guarantee": f"no_starvation(batch, {bound} ms)",
            "description": f"Batch aging interval of {aging_val}ms exceeds declared bound of {bound}ms.",
        })

    # 3. OVERPROMISED_BOUND (5 policies)
    for i in range(1, 6):
        p_name = f"broken_overpromised_{i:02d}"
        q = 10 + i * 2
        bound = 2 + i  # bound is less than single quantum!
        src = f"""// Mutation: declared bound is smaller than own quantum
policy {p_name} {{
  option max_tasks = 8;
  class web   {{ prio 0; quantum {q} ms;  kind interactive; }}
  class batch {{ prio 1; quantum 20 ms; aging 100 ms; kind batch; }}
  guarantee no_starvation(web, {bound} ms);
}}
"""
        dataset_specs.append({
            "filename": f"{p_name}.sched",
            "name": p_name,
            "source": src,
            "ground_truth_cause": "OVERPROMISED_BOUND",
            "target_class": "web",
            "target_guarantee": f"no_starvation(web, {bound} ms)",
            "description": f"Web declared bound of {bound}ms is less than its quantum of {q}ms.",
        })

    # 4. QUANTUM_IMBALANCE (5 policies)
    for i in range(1, 6):
        p_name = f"broken_quantum_imbalance_{i:02d}"
        heavy_q = 60 + i * 15
        bound = 30 + i * 5  # tight bound violated by heavy web quantum
        src = f"""// Mutation: heavy quantum in top tier delays batch
policy {p_name} {{
  option max_tasks = 8;
  class web   {{ prio 0; quantum {heavy_q} ms;  kind interactive; }}
  class batch {{ prio 1; quantum 20 ms; aging 100 ms; kind batch; }}
  guarantee no_starvation(batch, {bound} ms);
}}
"""
        dataset_specs.append({
            "filename": f"{p_name}.sched",
            "name": p_name,
            "source": src,
            "ground_truth_cause": "QUANTUM_IMBALANCE",
            "target_class": "batch",
            "target_guarantee": f"no_starvation(batch, {bound} ms)",
            "description": f"Web tier quantum of {heavy_q}ms introduces severe head-of-line blocking.",
        })

    # 5. TIER_CONTENTION (5 policies)
    for i in range(1, 6):
        p_name = f"broken_tier_contention_{i:02d}"
        bound = 20 + i * 5
        src = f"""// Mutation: 3 competing tiers with tight bound
policy {p_name} {{
  option max_tasks = 8;
  class rt    {{ prio 0; quantum 5 ms;  kind realtime; }}
  class web   {{ prio 1; quantum 15 ms; aging 80 ms; kind interactive; }}
  class batch {{ prio 2; quantum 25 ms; aging 150 ms; kind batch; }}
  guarantee no_starvation(batch, {bound} ms);
}}
"""
        dataset_specs.append({
            "filename": f"{p_name}.sched",
            "name": p_name,
            "source": src,
            "ground_truth_cause": "TIER_CONTENTION",
            "target_class": "batch",
            "target_guarantee": f"no_starvation(batch, {bound} ms)",
            "description": "Multi-tier contention prevents batch from dispatching within tight bound.",
        })

    # 6. SHARE_INFEASIBLE (5 policies)
    for i in range(1, 6):
        p_name = f"broken_share_infeasible_{i:02d}"
        promised_share = 70 + i * 4
        src = f"""// Mutation: batch demands excessive share against higher prio web
policy {p_name} {{
  option max_tasks = 8;
  class web   {{ prio 0; quantum 5 ms;  kind interactive; }}
  class batch {{ prio 1; quantum 20 ms; aging 100 ms; kind batch; }}
  guarantee min_share(batch, {promised_share} %);
}}
"""
        dataset_specs.append({
            "filename": f"{p_name}.sched",
            "name": p_name,
            "source": src,
            "ground_truth_cause": "SHARE_INFEASIBLE",
            "target_class": "batch",
            "target_guarantee": f"min_share(batch, {promised_share} %)",
            "description": f"Batch claims {promised_share}% CPU share, mathematically impossible against priority 0.",
        })

    # Verify and write files
    labels = []
    print(f"Validating and generating {len(dataset_specs)} broken policies...")
    for spec in dataset_specs:
        file_path = out_path / spec["filename"]
        file_path.write_text(spec["source"], encoding="utf-8")

        res = compile_source(spec["source"])
        if not res.ok:
            raise RuntimeError(f"Syntax/safety error in generated policy {spec['name']}: {res.diagnostics}")

        verdicts = check_all(res.ir)
        has_violation = any(v.status == "VIOLATED" for v in verdicts)
        if not has_violation:
            raise RuntimeError(f"Generated policy {spec['name']} does NOT violate any guarantee!")

        labels.append({
            "filename": spec["filename"],
            "name": spec["name"],
            "ground_truth_cause": spec["ground_truth_cause"],
            "target_class": spec["target_class"],
            "target_guarantee": spec["target_guarantee"],
            "description": spec["description"],
            "violations_count": sum(1 for v in verdicts if v.status == "VIOLATED"),
        })

    labels_file = out_path / "labels.json"
    with open(labels_file, "w", encoding="utf-8") as fp:
        json.dump(labels, fp, indent=2)

    print(f"Generated {len(labels)} verified broken policies in {output_dir}/")
    return labels


if __name__ == "__main__":
    generate_dataset()
