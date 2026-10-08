"""Orphaned-scope reaper backstop: sweep ``sase-agent`` scopes whose runner is gone.

Uses the shared engine from :mod:`sase.agent._scope_sweep_core`. Only
:func:`reap_orphaned_agent_scopes` is public; the ``_``-prefixed discovery
helpers are used only inside this file.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from sase.agent._scope_sweep_core import (
    execute_scope_sweep,
    format_entry,
    is_agent_runner,
    plan_scope_sweep,
    read_scope_members,
)
from sase.agent._scope_sweep_types import (
    AGENT_SCOPE_UNIT_PREFIX,
    DEFAULT_SPARE_PROCESS_PATTERNS,
    AgentScope,
    ReapResult,
    ReapedScope,
    ScopeMember,
)

log = logging.getLogger(__name__)

#: Basename identifying the pre-exec ``systemd-run`` window.
_SYSTEMD_RUN_BASENAME = "systemd-run"
#: How deep below the user-manager root scope discovery descends.
_REAPER_MAX_DISCOVERY_DEPTH = 3
#: Per-scope entries recorded for a reaped scope.
_REAPER_ENTRY_LIMIT = 5
#: Message when a pytest process attempts an unfiltered real-tree scan.
_REAPER_PYTEST_GUARD_MESSAGE = (
    "Refusing unfiltered orphaned-scope scan of the real cgroup tree "
    "from a pytest process: pass an explicit cgroup_root or only_units."
)


def _parse_scope_created_ns(unit: str) -> int | None:
    """Return the trailing ``<time_ns>`` from a scope unit name, or ``None``."""
    name = unit
    if name.endswith(".scope"):
        name = name[: -len(".scope")]
    tail = name.rsplit("-", 1)[-1] if "-" in name else ""
    if tail.isdigit():
        try:
            return int(tail)
        except ValueError:
            return None
    return None


def _is_agent_scope_name(name: str) -> bool:
    return name.startswith(AGENT_SCOPE_UNIT_PREFIX + "-") and name.endswith(".scope")


def _is_systemd_run_member(member: ScopeMember) -> bool:
    if member.comm == _SYSTEMD_RUN_BASENAME:
        return True
    return any(
        PurePosixPath(arg).name == _SYSTEMD_RUN_BASENAME for arg in member.argv[:3]
    )


def _cgroup_v2_unified(*, proc_root: Path = Path("/proc")) -> bool:
    try:
        text = (proc_root / str(os.getpid()) / "cgroup").read_text(encoding="utf-8")
    except OSError:
        return False
    for line in text.splitlines():
        fields = line.split(":", 2)
        if len(fields) == 3 and fields[0] == "0" and fields[1] == "":
            return True
    return False


def _own_cgroup_text(*, proc_root: Path = Path("/proc")) -> str | None:
    try:
        return (proc_root / str(os.getpid()) / "cgroup").read_text(encoding="utf-8")
    except OSError:
        return None


def _user_manager_root(
    cgroup_text: str | None, *, uid: int, cgroup_base: Path = Path("/sys/fs/cgroup")
) -> Path:
    """Resolve the ``user@<uid>.service`` subtree from own cgroup text."""
    if cgroup_text:
        for line in cgroup_text.splitlines():
            fields = line.split(":", 2)
            path = fields[2] if len(fields) == 3 else line
            components = [part for part in path.split("/") if part]
            for index, component in enumerate(components):
                if component == f"user@{uid}.service":
                    return cgroup_base.joinpath(*components[: index + 1])
    return cgroup_base / "user.slice" / f"user-{uid}.slice" / f"user@{uid}.service"


def _iter_scope_dirs(search_root: Path, *, max_depth: int = 3) -> list[Path]:
    """Return ``sase-agent-*.scope`` directories at most *max_depth* deep."""
    found: list[Path] = []
    try:
        if not search_root.is_dir():
            return []
    except OSError:
        return []
    # Breadth-first walk bounded by depth; never follow symlinked dirs.
    queue: list[tuple[Path, int]] = [(search_root, 0)]
    while queue:
        current, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        try:
            children = list(current.iterdir())
        except OSError:
            continue
        for child in children:
            try:
                if child.is_symlink():
                    continue
                if not child.is_dir():
                    continue
            except OSError:
                continue
            if _is_agent_scope_name(child.name):
                found.append(child)
            queue.append((child, depth + 1))
    return found


def _discover_agent_scopes(
    *,
    cgroup_root: Path | str | None = None,
    only_units: set[str] | frozenset[str] | None = None,
    proc_root: Path = Path("/proc"),
) -> list[AgentScope]:
    """Locate ``sase-agent-*.scope`` directories under the user manager.

    With *cgroup_root* given, that tree is searched directly (tests pass a
    fake root). Otherwise the ``user@<uid>.service`` subtree is resolved
    from ``/proc/self/cgroup``, falling back to the conventional
    ``user.slice/user-<uid>.slice/user@<uid>.service`` path.

    At most 3 levels deep are searched. Returns nothing on non-Linux hosts
    or without unified cgroup v2. Under pytest an unfiltered scan of the
    real tree is refused: pass an explicit fake root or unit filter.
    """
    from sase.core.state_write_guard import pytest_context_detected

    if sys.platform != "linux":
        log.info("orphan scope discovery: not Linux; nothing eligible")
        return []
    if pytest_context_detected() and cgroup_root is None and only_units is None:
        raise RuntimeError(_REAPER_PYTEST_GUARD_MESSAGE)
    if not _cgroup_v2_unified(proc_root=proc_root):
        log.info("orphan scope discovery: no unified cgroup v2; nothing eligible")
        return []
    if cgroup_root is not None:
        search_root = Path(cgroup_root)
    else:
        cgroup_text = _own_cgroup_text(proc_root=proc_root)
        try:
            uid = os.getuid()
        except OSError:
            return []
        search_root = _user_manager_root(cgroup_text, uid=uid)
    wanted = set(only_units) if only_units is not None else None
    scopes: list[AgentScope] = []
    for scope_dir in _iter_scope_dirs(
        search_root, max_depth=_REAPER_MAX_DISCOVERY_DEPTH
    ):
        if wanted is not None and scope_dir.name not in wanted:
            continue
        scopes.append(
            AgentScope(
                unit=scope_dir.name,
                path=scope_dir,
                created_ns=_parse_scope_created_ns(scope_dir.name),
            )
        )
    scopes.sort(key=lambda scope: scope.unit)
    return scopes


def _read_agent_name(pid: int, *, proc_root: Path = Path("/proc")) -> str | None:
    """Best-effort ``SASE_AGENT_NAME`` read from ``/proc/<pid>/environ``."""
    try:
        data = (proc_root / str(pid) / "environ").read_bytes()
    except OSError:
        return None
    for entry in data.split(b"\0"):
        if entry.startswith(b"SASE_AGENT_NAME="):
            try:
                value = entry.split(b"=", 1)[1].decode("utf-8", errors="replace")
            except IndexError:
                return None
            value = value.strip()
            return value or None
    return None


def reap_orphaned_agent_scopes(
    *,
    apply: bool,
    min_age_seconds: float | None = None,
    cgroup_root: Path | str | None = None,
    only_units: set[str] | frozenset[str] | None = None,
    proc_root: Path = Path("/proc"),
    grace_seconds: float | None = None,
    spare_patterns: tuple[str, ...] | list[str] | None = None,
    now_ns: int | None = None,
    kill: Callable[[int, int], None] | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> ReapResult:
    """Sweep ``sase-agent`` scopes whose runner is gone.

    Each discovered scope classifies as ``skipped_young`` (younger than
    *min_age_seconds*, or with an unparsable trailing timestamp, which fails
    closed), ``live`` (holds a runner or ``systemd-run`` member), ``empty``
    (no live members), ``spared_only`` (every member spared), or
    ``reapable``. Reapable scopes run the shared selection rule with no
    protect root and, when *apply* is true, the shared signal execution;
    with ``apply=False`` nothing is signalled.
    """
    if sys.platform != "linux":
        return ReapResult(
            scanned=0,
            live=0,
            skipped_young=0,
            empty=0,
            spared_only=0,
            reaped=(),
            terminated=0,
            errors=0,
            reason="not_linux",
        )
    if not _cgroup_v2_unified(proc_root=proc_root):
        return ReapResult(
            scanned=0,
            live=0,
            skipped_young=0,
            empty=0,
            spared_only=0,
            reaped=(),
            terminated=0,
            errors=0,
            reason="no_cgroup_v2",
        )
    if min_age_seconds is None:
        try:
            from sase.config._settings_system import (
                get_agent_scope_teardown_reaper_min_scope_age_seconds,
            )

            min_age_seconds = get_agent_scope_teardown_reaper_min_scope_age_seconds()
        except Exception:  # noqa: BLE001 - the reaper fails open to a safe default.
            min_age_seconds = 120
    if grace_seconds is None:
        try:
            from sase.config._settings_system import (
                get_agent_scope_teardown_term_grace_seconds,
            )

            grace_seconds = get_agent_scope_teardown_term_grace_seconds()
        except Exception:  # noqa: BLE001 - the reaper fails open to a safe default.
            grace_seconds = 3.0
    if spare_patterns is None:
        try:
            from sase.config._settings_system import (
                get_agent_scope_teardown_spare_process_patterns,
            )

            spare_patterns = tuple(get_agent_scope_teardown_spare_process_patterns())
        except Exception:  # noqa: BLE001 - the reaper fails open to a safe default.
            spare_patterns = tuple(DEFAULT_SPARE_PROCESS_PATTERNS)
    else:
        spare_patterns = tuple(spare_patterns)
    now = time.time_ns() if now_ns is None else int(now_ns)
    min_age = max(0.0, float(min_age_seconds))

    # The pytest guard lives in discovery; let its refusal propagate so a
    # test that forgets its fake root fails loudly instead of scanning host.
    scopes = _discover_agent_scopes(
        cgroup_root=cgroup_root, only_units=only_units, proc_root=proc_root
    )
    live = 0
    skipped_young = 0
    empty = 0
    spared_only = 0
    reaped: list[ReapedScope] = []
    terminated_total = 0
    errors = 0
    for scope in scopes:
        try:
            if scope.created_ns is None:
                skipped_young += 1
                continue
            age_seconds = (now - scope.created_ns) / 1_000_000_000
            if age_seconds < min_age:
                skipped_young += 1
                continue
            members = read_scope_members(scope.path, proc_root=proc_root)
            if not members:
                empty += 1
                continue
            if any(
                is_agent_runner(member) or _is_systemd_run_member(member)
                for member in members
            ):
                live += 1
                continue
            plan = plan_scope_sweep(
                members, protect_root=None, spare_patterns=spare_patterns
            )
            if not plan.targets:
                spared_only += 1
                continue
            agent_name = _read_agent_name(plan.targets[0].pid, proc_root=proc_root)
            entries = tuple(
                format_entry(member) for member in plan.targets[:_REAPER_ENTRY_LIMIT]
            )
            terminated_here = 0
            if apply:
                sweep_kwargs: dict = {
                    "grace_seconds": float(grace_seconds),
                    "proc_root": proc_root,
                }
                if kill is not None:
                    sweep_kwargs["kill"] = kill
                if clock is not None:
                    sweep_kwargs["clock"] = clock
                if sleep is not None:
                    sweep_kwargs["sleep"] = sleep
                sweep_result = execute_scope_sweep(plan, scope.path, **sweep_kwargs)
                terminated_here = len(sweep_result.terminated)
                terminated_total += terminated_here
            reaped.append(
                ReapedScope(
                    unit=scope.unit,
                    agent_name=agent_name,
                    targets=len(plan.targets),
                    terminated=terminated_here,
                    entries=entries,
                )
            )
        except Exception:  # noqa: BLE001 - one bad scope never stops the pass.
            log.exception("Orphaned agent scope reap failed for %s", scope.unit)
            errors += 1
    return ReapResult(
        scanned=len(scopes),
        live=live,
        skipped_young=skipped_young,
        empty=empty,
        spared_only=spared_only,
        reaped=tuple(reaped),
        terminated=terminated_total,
        errors=errors,
    )


__all__ = [
    "reap_orphaned_agent_scopes",
]
