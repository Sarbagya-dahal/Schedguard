"""Safe, inspection-first build and prerequisite checks for generated BPF."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any


@dataclass
class ToolchainReport:
    status: str
    platform: str
    kernel_release: str | None
    clang: str | None
    clang_version: str | None
    vmlinux_header: str | None
    scx_header: str | None
    diagnostics: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BuildResult:
    status: str
    source: str
    output: str | None
    command: list[str]
    diagnostics: str
    prerequisites: ToolchainReport

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "prerequisites": self.prerequisites.to_dict()}


def _version(clang: str | None) -> str | None:
    if not clang:
        return None
    try:
        p = subprocess.run([clang, "--version"], capture_output=True, text=True, timeout=5, check=False)
        return p.stdout.splitlines()[0] if p.stdout else p.stderr.splitlines()[0]
    except (OSError, IndexError, subprocess.TimeoutExpired):
        return None


def check_toolchain(vmlinux_header: str | os.PathLike[str] | None = None,
                    scx_header: str | os.PathLike[str] | None = None) -> ToolchainReport:
    """Inspect prerequisites without installing packages or loading BPF."""
    clang = shutil.which("clang")
    kernel = platform.release() if platform.system() == "Linux" else None
    vm = Path(vmlinux_header).resolve() if vmlinux_header else None
    scx = Path(scx_header).resolve() if scx_header else None
    diagnostics = []
    if platform.system() != "Linux":
        diagnostics.append("NOT_RUN: sched_ext compilation/load requires a Linux target; current host is not Linux")
    if not clang:
        diagnostics.append("clang not found (required: clang -target bpf)")
    if not vm or not vm.is_file():
        diagnostics.append("vmlinux.h not supplied or not found")
    if not scx or not scx.is_file():
        diagnostics.append("scx/common.bpf.h not supplied or not found")
    status = "READY" if not diagnostics else "NOT_READY"
    return ToolchainReport(status, platform.system(), kernel, clang, _version(clang),
                           str(vm) if vm and vm.is_file() else None,
                           str(scx) if scx and scx.is_file() else None, diagnostics)


def build_ebpf(source: str | os.PathLike[str], output: str | os.PathLike[str],
               vmlinux_header: str | os.PathLike[str] | None = None,
               scx_header: str | os.PathLike[str] | None = None) -> BuildResult:
    """Compile generated source only when all explicit prerequisites exist."""
    src = Path(source).resolve()
    out = Path(output).resolve()
    report = check_toolchain(vmlinux_header, scx_header)
    include_dirs = []
    for item in (Path(vmlinux_header).parent if vmlinux_header else None,
                 Path(scx_header).parents[1] if scx_header else None):
        if item:
            include_dirs += ["-I", str(item)]
    command = [report.clang or "clang", "-target", "bpf", "-O2", "-g", "-c", str(src), "-o", str(out), *include_dirs]
    if report.status != "READY" or not src.is_file():
        diagnostics = "source missing" if not src.is_file() else "; ".join(report.diagnostics)
        return BuildResult("NOT_RUN", str(src), None, command, diagnostics, report)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        p = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        status = "COMPILE_SUCCEEDED" if p.returncode == 0 else "COMPILE_FAILED"
        return BuildResult(status, str(src), str(out) if p.returncode == 0 else None, command,
                           (p.stdout + p.stderr).strip(), report)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return BuildResult("COMPILE_FAILED", str(src), None, command, str(exc), report)
