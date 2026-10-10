"""W4 fresh-interpreter probe for update-skew auto-restart.

A matching error pattern plus witnesses is never enough on its own: the
healer runs the failing imports in a brand-new interpreter (``python -I``,
cwd ``~`` so a sase workspace checkout stays off ``sys.path``) and only
proceeds when the current tree imports cleanly. The probe never retries the
missing import itself, which could never succeed for removal-type skew.

``run_probe`` takes explicit module lists so tests never need a real
failure; the healer derives them from the failing traceback frames plus the
target module.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PROBE_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class _ProbeResult:
    """Outcome of one fresh-interpreter probe."""

    ok: bool
    failures: tuple[str, ...] = ()
    detail: str = ""


_PROBE_SCRIPT = """
import importlib, json, sys
modules = json.loads(sys.argv[1])
binding_checks = json.loads(sys.argv[2])
failures = []
for name in modules:
    try:
        importlib.import_module(name)
    except Exception as exc:
        failures.append(f"{name}: {type(exc).__name__}: {exc}")
for module_name, attr in binding_checks:
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        failures.append(f"{module_name}: {type(exc).__name__}: {exc}")
        continue
    if not hasattr(module, attr):
        failures.append(f"{module_name} has no attribute {attr!r}")
print(json.dumps(failures))
"""


def run_probe(
    modules: list[str],
    *,
    binding_checks: list[tuple[str, str]] | None = None,
    timeout: float = PROBE_TIMEOUT_SECONDS,
) -> _ProbeResult:
    """Import *modules* in a fresh ``-I`` interpreter; check bindings."""
    import json

    seen: list[str] = []
    for name in modules:
        name = (name or "").strip()
        if name and name not in seen:
            seen.append(name)
    checks = [(m, a) for m, a in (binding_checks or []) if m and a]
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                _PROBE_SCRIPT,
                json.dumps(seen),
                json.dumps(checks),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(Path.home()),
        )
    except subprocess.TimeoutExpired:
        return _ProbeResult(
            ok=False,
            detail=f"probe timed out after {timeout:.0f}s",
        )
    except Exception as exc:
        return _ProbeResult(ok=False, detail=f"probe could not run: {exc}")
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-500:]
        return _ProbeResult(ok=False, detail=f"probe interpreter failed: {tail}")
    try:
        failures = json.loads(proc.stdout.strip() or "[]")
    except ValueError:
        return _ProbeResult(ok=False, detail="probe returned unparseable output")
    if not isinstance(failures, list):
        return _ProbeResult(ok=False, detail="probe returned an unexpected shape")
    failures = tuple(str(f) for f in failures)
    if failures:
        return _ProbeResult(
            ok=False,
            failures=failures,
            detail="; ".join(failures)[:1000],
        )
    return _ProbeResult(ok=True, detail="fresh interpreter imports cleanly")


def probe_modules_for_frames(
    frames: list[object],
    *,
    target_module: str | None = None,
) -> list[str]:
    """Derive probe modules from failing traceback frames.

    Only managed-origin modules are probed: frame files resolving under a
    managed root contribute their module, plus the error's target module.
    """
    try:
        from sase.agent.auto_restart.managed_roots import collect_managed_roots
    except Exception:
        return [target_module] if target_module else []
    try:
        roots = [str(r.source_root) for r in collect_managed_roots()]
    except Exception:
        return [target_module] if target_module else []
    modules: list[str] = []
    for frame in frames:
        filename = getattr(frame, "file", None) or (
            frame.get("file") if isinstance(frame, dict) else None
        )
        if not filename:
            continue
        for root in roots:
            if root and str(filename).startswith(root.rstrip("/") + "/"):
                module = _path_to_module(str(filename), root)
                if module and module not in modules:
                    modules.append(module)
                break
    if target_module and target_module not in modules:
        modules.append(target_module)
    return modules


def _path_to_module(filename: str, root: str) -> str | None:
    rel = filename[len(root.rstrip("/") + "/") :]
    if not rel.endswith(".py"):
        return None
    stem = rel[:-3].replace("/", ".")
    if stem.endswith(".__init__"):
        stem = stem[: -len(".__init__")]
    return stem or None


__all__ = [
    "PROBE_TIMEOUT_SECONDS",
    "probe_modules_for_frames",
    "run_probe",
]
