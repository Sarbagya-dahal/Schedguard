"""Attacker implementations for adversarial workload synthesis.

Provides:
- RandomAttacker: Uniformly samples bounded workloads
- HillClimbAttacker: Iteratively mutates the best-so-far workload
- LLMAttacker: Adaptively prompts an LLM with measured feedback and validates all specs
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
import random
import time
from typing import Any
from ..ir import IRPolicy
from ..sim.workload import Workload
from ..inference.prompts import Prompt
from ..inference.providers import get_provider, StubProvider
from ..inference.schema import extract_json
from .space import random_workload, mutate_workload, validate_spec
from .objectives import RegressionObjective, RegressionResult


@dataclass
class AttackResult:
    attacker_name: str
    simulations_run: int
    regressions_found: int
    simulations_to_first_success: int | None
    best_regression: float
    worst_workload: Workload | None
    worst_result: RegressionResult | None
    rejection_count: int = 0
    rounds_run: int = 0
    elapsed_ms: float = 0.0
    history: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "attacker": self.attacker_name,
            "simulations_run": self.simulations_run,
            "regressions_found": self.regressions_found,
            "simulations_to_first_success": self.simulations_to_first_success,
            "best_regression": round(self.best_regression, 2),
            "worst_workload": self.worst_workload.to_dict() if self.worst_workload else None,
            "worst_result": self.worst_result.to_dict() if self.worst_result else None,
            "rejection_count": self.rejection_count,
            "rounds_run": self.rounds_run,
            "elapsed_ms": round(self.elapsed_ms, 2),
        }


class Attacker(ABC):
    @abstractmethod
    def search(
        self,
        incumbent: IRPolicy,
        candidate: IRPolicy,
        objective: RegressionObjective,
        budget: int = 50,
        rng: random.Random | None = None,
        horizon_ms: int = 10_000,
    ) -> AttackResult:
        pass


class RandomAttacker(Attacker):
    """Samples uniform random workloads within the bounded parameter space."""

    def search(
        self,
        incumbent: IRPolicy,
        candidate: IRPolicy,
        objective: RegressionObjective,
        budget: int = 50,
        rng: random.Random | None = None,
        horizon_ms: int = 10_000,
    ) -> AttackResult:
        rng = rng or random.Random()
        t0 = time.perf_counter()

        sims = 0
        regressions = 0
        first_success = None
        best_reg = -float("inf")
        worst_wl: Workload | None = None
        worst_res: RegressionResult | None = None
        history = []

        for step in range(budget):
            wl = random_workload(rng, incumbent)
            res = objective.evaluate(incumbent, candidate, wl, horizon_ms=horizon_ms)
            sims += 1

            if res.is_regression:
                regressions += 1
                if first_success is None:
                    first_success = sims

            if res.regression > best_reg or worst_wl is None:
                best_reg = res.regression
                worst_wl = wl
                worst_res = res

            history.append({
                "sim": sims,
                "regression": round(res.regression, 2),
                "is_regression": res.is_regression,
            })

        elapsed = (time.perf_counter() - t0) * 1e3
        return AttackResult(
            attacker_name="random",
            simulations_run=sims,
            regressions_found=regressions,
            simulations_to_first_success=first_success,
            best_regression=best_reg if best_reg != -float("inf") else 0.0,
            worst_workload=worst_wl,
            worst_result=worst_res,
            rejection_count=0,
            rounds_run=1,
            elapsed_ms=elapsed,
            history=history,
        )


class HillClimbAttacker(Attacker):
    """Mutates the best-so-far workload to locate local regression extrema."""

    def search(
        self,
        incumbent: IRPolicy,
        candidate: IRPolicy,
        objective: RegressionObjective,
        budget: int = 50,
        rng: random.Random | None = None,
        horizon_ms: int = 10_000,
    ) -> AttackResult:
        rng = rng or random.Random()
        t0 = time.perf_counter()

        sims = 0
        regressions = 0
        first_success = None
        best_reg = -float("inf")
        worst_wl: Workload | None = None
        worst_res: RegressionResult | None = None
        history = []

        # Seed with initial random workload
        current_wl = random_workload(rng, incumbent)
        res = objective.evaluate(incumbent, candidate, current_wl, horizon_ms=horizon_ms)
        sims += 1
        best_reg = res.regression
        worst_wl = current_wl
        worst_res = res
        if res.is_regression:
            regressions += 1
            first_success = 1

        history.append({"sim": 1, "regression": round(res.regression, 2), "is_regression": res.is_regression})

        while sims < budget:
            mutated = mutate_workload(current_wl, rng, incumbent)
            res = objective.evaluate(incumbent, candidate, mutated, horizon_ms=horizon_ms)
            sims += 1

            if res.is_regression:
                regressions += 1
                if first_success is None:
                    first_success = sims

            # Adopt mutation if it improves or matches regression objective
            if res.regression >= best_reg:
                best_reg = res.regression
                current_wl = mutated
                worst_wl = mutated
                worst_res = res

            history.append({
                "sim": sims,
                "regression": round(res.regression, 2),
                "is_regression": res.is_regression,
            })

        elapsed = (time.perf_counter() - t0) * 1e3
        return AttackResult(
            attacker_name="hillclimb",
            simulations_run=sims,
            regressions_found=regressions,
            simulations_to_first_success=first_success,
            best_regression=best_reg,
            worst_workload=worst_wl,
            worst_result=worst_res,
            rejection_count=0,
            rounds_run=1,
            elapsed_ms=elapsed,
            history=history,
        )


class LLMAttacker(Attacker):
    """Uses an LLM to hypothesize adversarial workloads in batches, strictly validated."""

    def __init__(self, provider=None, batch_size: int = 5):
        self.provider = provider or get_provider()
        self.batch_size = batch_size

    def _build_prompt(
        self,
        incumbent: IRPolicy,
        candidate: IRPolicy,
        objective: RegressionObjective,
        top_regressions: list[dict],
    ) -> Prompt:
        system = (
            "You are an adversarial scheduler benchmark designer. Your task is to generate "
            "workload specifications (in JSON) that expose performance regressions of a candidate "
            "scheduling policy compared to an incumbent policy.\n"
            "Format your response as a JSON object containing a 'workloads' list:\n"
            "{\n"
            "  \"workloads\": [\n"
            "    {\"tasks\": [{\"class\": \"<name>\", \"count\": <int>, \"burst_ms\": <int>, \"sleep_ms\": <int>}, ...]}\n"
            "  ]\n"
            "}\n"
            "Adhere strictly to class names in the policies and keep total task counts bounded."
        )

        p0_desc = {c.name: {"prio": c.prio, "quantum": c.quantum_ms, "aging": c.aging_ms} for c in incumbent.classes}
        p1_desc = {c.name: {"prio": c.prio, "quantum": c.quantum_ms, "aging": c.aging_ms} for c in candidate.classes}

        user_content = {
            "incumbent_policy": p0_desc,
            "candidate_policy": p1_desc,
            "target_class": objective.target_class,
            "target_metric": objective.metric_name,
            "tolerance": objective.tolerance,
            "batch_size_requested": self.batch_size,
            "worst_prior_workloads": top_regressions,
        }

        user_str = (
            f"Generate {self.batch_size} adversarial workload candidates to maximize regression on "
            f"class '{objective.target_class}' for metric '{objective.metric_name}'.\n"
            f"Context:\n{json.dumps(user_content, indent=2)}"
        )

        return Prompt(system=system, user=user_str, context={})

    def search(
        self,
        incumbent: IRPolicy,
        candidate: IRPolicy,
        objective: RegressionObjective,
        budget: int = 50,
        rng: random.Random | None = None,
        horizon_ms: int = 10_000,
    ) -> AttackResult:
        rng = rng or random.Random()
        t0 = time.perf_counter()

        sims = 0
        regressions = 0
        rejections = 0
        rounds = 0
        first_success = None
        best_reg = -float("inf")
        worst_wl: Workload | None = None
        worst_res: RegressionResult | None = None
        top_regressions: list[dict] = []
        history = []

        while sims < budget:
            rounds += 1
            # If provider is StubProvider, synthesize heuristic stress workloads
            if isinstance(self.provider, StubProvider):
                specs = []
                for _ in range(self.batch_size):
                    # Offline heuristic: mix of bursty target and heavy competing tasks
                    specs.append(random_workload(rng, incumbent).to_dict())
            else:
                prompt = self._build_prompt(incumbent, candidate, objective, top_regressions)
                try:
                    resp = self.provider.complete(prompt)
                    parsed = extract_json(resp)
                    if isinstance(parsed, dict) and "workloads" in parsed:
                        specs = parsed["workloads"]
                    elif isinstance(parsed, list):
                        specs = parsed
                    else:
                        specs = [parsed]
                except Exception:
                    rejections += self.batch_size
                    specs = []

            if not specs:
                # If provider failed to return specs, break or sample random fallback
                break

            for spec in specs:
                if sims >= budget:
                    break

                ok, reason, validated_wl = validate_spec(spec, incumbent)
                if not ok or validated_wl is None:
                    rejections += 1
                    continue

                res = objective.evaluate(incumbent, candidate, validated_wl, horizon_ms=horizon_ms)
                sims += 1

                if res.is_regression:
                    regressions += 1
                    if first_success is None:
                        first_success = sims

                if res.regression > best_reg or worst_wl is None:
                    best_reg = res.regression
                    worst_wl = validated_wl
                    worst_res = res

                history.append({
                    "sim": sims,
                    "regression": round(res.regression, 2),
                    "is_regression": res.is_regression,
                })

                top_regressions.append({
                    "regression": round(res.regression, 2),
                    "workload": validated_wl.to_dict(),
                })
                top_regressions.sort(key=lambda x: x["regression"], reverse=True)
                top_regressions = top_regressions[:3]

        elapsed = (time.perf_counter() - t0) * 1e3
        return AttackResult(
            attacker_name="llm",
            simulations_run=sims,
            regressions_found=regressions,
            simulations_to_first_success=first_success,
            best_regression=best_reg if best_reg != -float("inf") else 0.0,
            worst_workload=worst_wl,
            worst_result=worst_res,
            rejection_count=rejections,
            rounds_run=rounds,
            elapsed_ms=elapsed,
            history=history,
        )
