from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ClassDecl:
    name: str
    line: int
    prio: Optional[int] = None
    quantum_ms: Optional[int] = None
    aging_ms: Optional[int] = None
    kind: Optional[str] = None      # optional semantic hint (no scheduling effect)


@dataclass
class GuaranteeDecl:
    kind: str                       # "no_starvation" | "min_share"
    cls: str
    value: int                      # bound in ms, or percent
    line: int


@dataclass
class AdaptDecl:
    cls: str
    param: str                      # "aging" | "quantum"
    min_val: int
    max_val: int
    line: int


@dataclass
class PolicyAST:
    name: str
    classes: list[ClassDecl] = field(default_factory=list)
    guarantees: list[GuaranteeDecl] = field(default_factory=list)
    adaptations: list[AdaptDecl] = field(default_factory=list)
    max_tasks: Optional[int] = None
    sched_ext_map: Optional[str] = None
