"""Runner own-scope teardown: detect this runner's scope and sweep it.

Uses the shared engine from :mod:`sase.agent._scope_sweep_core`. Only
:func:`sweep_own_agent_scope` is public; the ``_``-prefixed detectors are used
only inside this file.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path, PurePosixPath
from typing import Literal

from sase.agent._scope_sweep_core import (
    execute_scope_sweep,
    format_entry,
    plan_scope_sweep,
    read_scope_members,
)
from sase.agent._scope_sweep_types import (
    AGENT_SCOPE_UNIT_PREFIX,
    RUNNER_SCRIPT_NAME,
    ScopeSweepResult,
)

log = logging.getLogger(__name__)

#: Entries listed on the runner-output summary line.
_SWEEP_LOG_LIST_LIMIT = 10


def _own_cgroup_path(proc_root: Path) -> str | None:
    try:
        text = (proc_root / str(os.getpid()) / "cgroup").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        fields = line.split(":", 2)
        if len(fields) == 3 and fields[0] == "0" and fields[1] == "":
            return fields[2]
    return None


def _own_agent_scope(
    *,
    proc_root: Path = Path("/proc"),
    cgroup_root: Path = Path("/sys/fs/cgroup"),
    enabled: bool | None = None,
) -> Path | None:
    """Return this runner's own scope cgroup dir, or ``None`` when no sweep.

    Every in-runner safety rail applies: Linux only, unified cgroup v2, own
    unit matches ``sase-agent-*.scope``, detach not disabled, config enabled,
    and the current process is the runner.
    """
    if sys.platform != "linux":
        return None
    cgroup_path = _own_cgroup_path(proc_root)
    if cgroup_path is None:
        return None
    from sase.detach_scope import detach_scope_disabled, unit_from_cgroup_path

    unit = unit_from_cgroup_path(cgroup_path)
    if (
        unit is None
        or not unit.startswith(AGENT_SCOPE_UNIT_PREFIX + "-")
        or not unit.endswith(".scope")
    ):
        return None
    if detach_scope_disabled():
        return None
    if enabled is None:
        try:
            from sase.config._settings_system import (
                get_agent_scope_teardown_enabled,
            )

            enabled = get_agent_scope_teardown_enabled()
        except Exception:  # noqa: BLE001 - sweep is best-effort.
            return None
    if not enabled:
        return None
    try:
        raw = (proc_root / str(os.getpid()) / "cmdline").read_bytes()
    except OSError:
        return None
    argv = [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]
    if not any(PurePosixPath(arg).name == RUNNER_SCRIPT_NAME for arg in argv):
        return None
    relative = cgroup_path.lstrip("/")
    scope_dir = cgroup_root / relative
    try:
        if not scope_dir.is_dir():
            return None
    except OSError:
        return None
    return scope_dir


def sweep_own_agent_scope(
    *,
    context: Literal["exit", "turn"],
    proc_root: Path = Path("/proc"),
    cgroup_root: Path = Path("/sys/fs/cgroup"),
    enabled: bool | None = None,
    grace_seconds: float | None = None,
    spare_patterns: tuple[str, ...] | list[str] | None = None,
) -> ScopeSweepResult | None:
    """Sweep this runner's own scope; never raises.

    Returns the sweep result, or ``None`` when the safety rails decline.
    """
    try:
        scope_dir = _own_agent_scope(
            proc_root=proc_root, cgroup_root=cgroup_root, enabled=enabled
        )
        if scope_dir is None:
            return None
        from sase.config._settings_system import (
            get_agent_scope_teardown_spare_process_patterns,
            get_agent_scope_teardown_term_grace_seconds,
        )

        patterns = (
            tuple(spare_patterns)
            if spare_patterns is not None
            else tuple(get_agent_scope_teardown_spare_process_patterns())
        )
        grace = (
            float(grace_seconds)
            if grace_seconds is not None
            else get_agent_scope_teardown_term_grace_seconds()
        )
        members = read_scope_members(scope_dir, proc_root=proc_root)
        plan = plan_scope_sweep(
            members, protect_root=os.getpid(), spare_patterns=patterns
        )
        if not plan.targets:
            return ScopeSweepResult(
                unit=scope_dir.name, terminated=(), survivors=(), rounds=1
            )
        result = execute_scope_sweep(
            plan, scope_dir, grace_seconds=grace, proc_root=proc_root
        )
        if result.terminated:
            entries = ", ".join(
                format_entry(m) for m in result.terminated[:_SWEEP_LOG_LIST_LIMIT]
            )
            line = (
                f"[scope-sweep {context}] terminated "
                f"{len(result.terminated)} leaked process(es) "
                f"in {result.unit}: {entries}"
            )
            print(line)
            log.info("%s", line)
        return result
    except Exception:  # noqa: BLE001 - the sweep must never break the runner.
        log.exception("Agent scope sweep failed")
        return None


__all__ = [
    "sweep_own_agent_scope",
]
