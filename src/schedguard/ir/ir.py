"""Fixed-size IR: what a bounded (eBPF-like) backend could consume.
Class table + guarantee table; no dynamic structures."""
from dataclasses import dataclass


@dataclass(frozen=True)
class IRClass:
    idx: int
    name: str
    prio: int
    quantum_ms: int
    aging_ms: int          # 0 = no aging
    kind: str              # "" if unspecified


@dataclass(frozen=True)
class IRGuarantee:
    kind: str              # "no_starvation" | "min_share"
    cls_idx: int
    cls_name: str
    value: int             # ms or percent

    def pretty(self) -> str:
        unit = "ms" if self.kind == "no_starvation" else "%"
        return f"{self.kind}({self.cls_name}, {self.value}{unit})"


@dataclass(frozen=True)
class IRAdaptation:
    cls_idx: int
    cls_name: str
    param: str             # "aging" | "quantum"
    min_val: int
    max_val: int

    def pretty(self) -> str:
        return f"adapt {self.cls_name}.{self.param} in {self.min_val}ms..{self.max_val}ms"


@dataclass(frozen=True)
class IRPolicy:
    name: str
    classes: tuple[IRClass, ...]
    guarantees: tuple[IRGuarantee, ...]
    max_tasks: int
    adaptations: tuple[IRAdaptation, ...] = ()
    sched_ext_map: str | None = None

    def cls(self, name: str) -> IRClass:
        for c in self.classes:
            if c.name == name:
                return c
        raise KeyError(name)

    def dump(self) -> str:
        lines = [f"policy {self.name}  (classes={len(self.classes)}, max_tasks={self.max_tasks})",
                 "  idx name       prio quantum aging kind"]
        for c in self.classes:
            lines.append(f"  {c.idx:<3} {c.name:<10} {c.prio:<4} {c.quantum_ms:<7} "
                         f"{c.aging_ms or '-':<5} {c.kind or '-'}")
        for g in self.guarantees:
            lines.append(f"  guarantee {g.pretty()}")
        for a in self.adaptations:
            lines.append(f"  {a.pretty()}")
        return "\n".join(lines)
