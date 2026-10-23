"""Explicit, opt-in sched_ext lifecycle and deterministic health state.

No function in this module loads or unloads a scheduler by default.  The
loader contract is intentionally narrow so a future Linux VM adapter can be
tested without making the Windows Studio privileged.
"""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import platform
from pathlib import Path
from typing import Any, Callable


@dataclass
class LifecycleState:
    stage: str = "INSPECTION_ONLY"
    policy_id: str | None = None
    previous_policy_id: str | None = None
    failure_reason: str | None = None
    healthy_signal: bool = False
    fallback: str = "kernel_default_scheduler"
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PreflightResult:
    status: str
    platform: str
    kernel_release: str | None
    sched_ext_available: bool
    privileged: bool
    diagnostics: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def preflight() -> PreflightResult:
    linux = platform.system() == "Linux"
    release = platform.release() if linux else None
    diagnostics = []
    if not linux:
        diagnostics.append("NOT_RUN: kernel operations are restricted to a Linux sched_ext VM")
    if linux and not release:
        diagnostics.append("kernel release unavailable")
    # Capability probing is intentionally read-only and conservative.
    sched_ext = linux and any(Path(p).exists() for p in ("/sys/kernel/sched_ext", "/sys/kernel/debug/sched_ext"))
    if linux and not sched_ext:
        diagnostics.append("sched_ext capability not observed in standard sysfs paths")
    return PreflightResult("READY" if linux and sched_ext else "NOT_READY", platform.system(), release,
                           sched_ext, False, diagnostics)


def authorize_load(state: LifecycleState, policy_id: str, confirmation: str,
                   loader: Callable[[str], bool], allow_kernel_load: bool = False) -> LifecycleState:
    """Load only after explicit confirmation and a caller-supplied VM loader."""
    if not allow_kernel_load or confirmation != "LOAD_SCHEDGUARD_IN_VM":
        raise PermissionError("kernel load requires explicit VM authorization token")
    if platform.system() != "Linux":
        raise RuntimeError("kernel load is supported only in a Linux sched_ext VM")
    if not loader(policy_id):
        state.stage = "LOAD_FAILED"
        state.failure_reason = "loader reported failure"
        state.updated_at = datetime.now(timezone.utc).isoformat()
        return state
    state.previous_policy_id = state.policy_id
    state.policy_id = policy_id
    state.stage = "LOADED_AWAITING_HEALTH"
    state.updated_at = datetime.now(timezone.utc).isoformat()
    return state


def watchdog_check(state: LifecycleState, telemetry_ok: bool, healthy_signal: bool) -> LifecycleState:
    """Drive fallback from deterministic telemetry conditions, never AI output."""
    state.healthy_signal = healthy_signal
    if not telemetry_ok or not healthy_signal:
        state.stage = "FALLBACK_REQUIRED"
        state.failure_reason = "missing telemetry or healthy-startup signal"
        state.fallback = "kernel_default_scheduler"
    elif state.stage == "LOADED_AWAITING_HEALTH":
        state.stage = "HEALTHY"
    state.updated_at = datetime.now(timezone.utc).isoformat()
    return state
