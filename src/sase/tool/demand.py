"""Per-run demand recording: provider context, rusage, tree RSS, grants.

Python owns capturing the demand facts; the Rust core owns the wires, their
validation and merge, and the store column (see ``tool_run_record_demand``).
Every write here is fail-open: a recording failure warns at most once per
process and never changes the child's result.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.agent.identity import discover_agent_runtime
from sase.core.tool_run import tool_run_record_demand
from sase.env_contracts import (
    SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV,
    SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS_ENV,
)
from sase.telemetry.metrics import TOOL_RUN_RECORDING_ERRORS
from sase.tool.executor_display import warn_once
from sase.tool.executor_process import (
    DEMAND_FILE_NAME,
    TOOL_RUN_DEMAND_ENV,
    TOOL_RUN_PROVIDER_ENV,
)
from sase.tool.observe import inc_tool_metric
from sase.tool.routing import read_ceiling_seconds

#: Warning printed at most once per process when a demand write fails.
_DEMAND_WRITE_WARNING = "sase: run demand not recorded"

#: Diagnostic stored when a demand file holds another run's grant record.
CROSS_RUN_DIAGNOSTIC = "ignored cross-run demand record"

#: Availability reason when the child was settled without ``wait4`` rusage.
RUSAGE_UNAVAILABLE = "rusage unavailable"

#: Availability reason when the host has no process tree to sample.
TREE_RSS_UNAVAILABLE = "tree RSS unavailable on this host"

#: Bounds mirrored from the core demand wire (see ``demand_wire.rs``).
_DEMAND_MAX_BYTES = 64 * 1024
_DEMAND_MAX_LINE_BYTES = 4 * 1024
_DEMAND_MAX_GRANTS = 64

_warned_no_demand = False


def demand_context(
    env: Mapping[str, str] | None = None,
    *,
    include_ceilings: bool = True,
) -> dict[str, Any] | None:
    """Return the provider/ceiling context for a run starting in *env*.

    The provider is ``discover_agent_runtime`` with the
    ``SASE_TOOL_RUN_PROVIDER`` overlay as fallback. Ceilings are recorded only
    when *include_ceilings* holds: a foreground run and a starter-scoped
    (detached) reservation are bounded by the caller's harness, while a plain
    hand-off reservation records the provider only. Returns ``None`` when
    nothing is known, so the caller skips the write.
    """

    current = os.environ if env is None else env
    provider = discover_agent_runtime(current)
    if provider is None:
        raw_overlay = current.get(TOOL_RUN_PROVIDER_ENV)
        if raw_overlay is not None and str(raw_overlay).strip():
            provider = str(raw_overlay).strip()
    context: dict[str, Any] = {}
    if provider is not None:
        context["provider"] = provider
    if include_ceilings:
        ceiling = read_ceiling_seconds(current, SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV)
        if ceiling is not None:
            context["sync_ceiling_seconds"] = ceiling
        soft_ceiling = read_ceiling_seconds(
            current, SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS_ENV
        )
        if soft_ceiling is not None:
            context["sync_soft_ceiling_seconds"] = soft_ceiling
    return context or None


def record_run_demand(
    run_id: str,
    *,
    context: Mapping[str, Any] | None = None,
    usage: Mapping[str, Any] | None = None,
    grants: Sequence[Mapping[str, Any]] = (),
    diagnostics: Sequence[str] = (),
) -> bool:
    """Merge one demand fragment into *run_id*; never raises.

    A failure warns at most once per process and bumps
    ``TOOL_RUN_RECORDING_ERRORS`` with ``op="demand"``. A stale wheel without
    the binding (the ``AttributeError`` from ``require_rust_binding``) is such
    a failure.
    """

    global _warned_no_demand
    # Skip a no-op write: the core reports it replayed, and an empty fragment
    # carries no fact worth a store round-trip.
    if context is None and usage is None and not grants and not diagnostics:
        return True
    request: dict[str, Any] = {"run_id": run_id}
    if context is not None:
        request["context"] = dict(context)
    if usage is not None:
        request["usage"] = dict(usage)
    if grants:
        request["worker_grants"] = [dict(grant) for grant in grants]
    if diagnostics:
        request["diagnostics"] = [str(item) for item in diagnostics]
    try:
        tool_run_record_demand(request)
    except Exception as exc:  # noqa: BLE001 - recording is fail-open.
        if not _warned_no_demand:
            _warned_no_demand = True
            warn_once(f"{_DEMAND_WRITE_WARNING} ({exc})")
        inc_tool_metric(TOOL_RUN_RECORDING_ERRORS, op="demand")
        return False
    return True


def demand_file_path(events_path: Path | None) -> Path | None:
    """Return the grant-channel path beside *events_path*, if any."""

    if events_path is None:
        return None
    return events_path.parent / DEMAND_FILE_NAME


def read_demand_grants(
    path: Path | None, run_id: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Read worker-grant records for *run_id* from a demand JSONL file.

    Reads at most 64 KiB, skips lines over 4 KiB, and takes at most 64
    grants. Keeps only ``schema_version == 1``, ``kind == "worker_grant"``
    records for this run; a cross-run record adds one diagnostic. A grant is
    forwarded only when its fields have the right primitive types; the core
    validates the rest. A missing file reads as no grants. Never raises.
    """

    if path is None:
        return [], []
    try:
        raw = Path(path).read_bytes()[:_DEMAND_MAX_BYTES]
    except OSError:
        return [], []
    grants: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    for line in raw.splitlines():
        if len(grants) >= _DEMAND_MAX_GRANTS:
            break
        if len(line) > _DEMAND_MAX_LINE_BYTES or not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        if record.get("kind") != "worker_grant":
            continue
        if (
            not _is_int(record.get("schema_version"))
            or record.get("schema_version") != 1
        ):
            continue
        record_run_id = record.get("run_id")
        if not isinstance(record_run_id, str) or not record_run_id:
            continue
        if record_run_id != run_id:
            if CROSS_RUN_DIAGNOSTIC not in diagnostics:
                diagnostics.append(CROSS_RUN_DIAGNOSTIC)
            continue
        grant = record.get("grant")
        if not isinstance(grant, dict):
            continue
        if _valid_grant(grant):
            grants.append(dict(grant))
    return grants, diagnostics


def _is_int(value: object) -> bool:
    return type(value) is int


def _is_optional_str(value: object) -> bool:
    return value is None or isinstance(value, str)


def _is_optional_int(value: object) -> bool:
    return value is None or type(value) is int


def _valid_grant(grant: Mapping[str, Any]) -> bool:
    """Return whether *grant* has the primitive types the core expects."""

    grant_id = grant.get("grant_id")
    if not isinstance(grant_id, str) or not grant_id:
        return False
    if not isinstance(grant.get("source"), str) or not grant.get("source"):
        return False
    if not isinstance(grant.get("path"), str) or not grant.get("path"):
        return False
    if not _is_int(grant.get("observed_ts_ms")):
        return False
    if not _is_optional_str(grant.get("lane")):
        return False
    for key in ("requested_floor", "requested_ceiling", "granted", "wait_ms"):
        if not _is_int(grant.get(key)):
            return False
    if not _is_optional_int(grant.get("budget")):
        return False
    if not _is_optional_int(grant.get("selected_files")):
        return False
    return _is_optional_str(grant.get("escalated_from"))


def _proc_stat_ppid_rss(stat_path: Path) -> tuple[int, int] | None:
    """Return ``(ppid, rss_pages)`` from one ``/proc/<pid>/stat`` file."""

    try:
        text = stat_path.read_text(encoding="utf-8")
    except OSError:
        return None
    # Parse after the last ")": a comm containing spaces or parentheses is
    # safe, and tail[1]/tail[21] are then ppid and rss pages.
    tail = text[text.rfind(")") + 1 :].split()
    if len(tail) < 22:
        return None
    try:
        return int(tail[1]), int(tail[21])
    except ValueError:
        return None


def tree_rss_kib(
    child_pid: int,
    *,
    proc_root: Path | str = "/proc",
    page_size: int | None = None,
) -> int | None:
    """Return the summed RSS of *child_pid*'s process tree in KiB.

    Walks the ppid→children map built from ``<proc_root>/[0-9]*/stat`` starting
    at *child_pid*. Returns ``None`` when the tree cannot be read (no proc
    root, or the whole tree vanished); a read error on one entry skips that
    entry. Never raises.
    """

    root = Path(proc_root)
    try:
        entries = list(root.iterdir())
    except OSError:
        return None
    children: dict[int, list[int]] = {}
    rss_pages: dict[int, int] = {}
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            pid = int(entry.name)
        except ValueError:
            continue
        parsed = _proc_stat_ppid_rss(entry / "stat")
        if parsed is None:
            continue
        ppid, pages = parsed
        rss_pages[pid] = pages
        children.setdefault(ppid, []).append(pid)
    if child_pid not in rss_pages and child_pid not in children:
        return None
    try:
        size = page_size if page_size is not None else os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError):
        return None
    total_pages = 0
    seen = {child_pid}
    queue = [child_pid]
    while queue:
        current = queue.pop()
        total_pages += rss_pages.get(current, 0)
        for member in children.get(current, ()):
            if member not in seen:
                seen.add(member)
                queue.append(member)
    return (total_pages * size) // 1024


def build_resource_usage(
    rusage: Any,
    *,
    peak_tree_rss_kib: int | None = None,
    tree_rss_samples: int = 0,
    availability: Sequence[str] = (),
) -> dict[str, Any]:
    """Build the stored ``usage`` wire from a ``wait4`` rusage and tree peak.

    ``ru_maxrss`` is KiB on Linux and bytes on macOS; it is normalized to
    KiB. A ``None`` rusage (the ``Popen`` fallback path) records no CPU or
    max-RSS facts and carries the ``rusage unavailable`` reason instead of
    zeros. Never raises.
    """

    reasons = [str(item) for item in availability if str(item)]
    usage: dict[str, Any] = {}
    if rusage is not None:
        try:
            user_ms = int(round(float(rusage.ru_utime) * 1000))
            system_ms = int(round(float(rusage.ru_stime) * 1000))
            max_rss = int(rusage.ru_maxrss)
        except (AttributeError, TypeError, ValueError):
            rusage = None
        else:
            if sys.platform == "darwin":
                max_rss = max_rss // 1024
            usage["cpu_user_ms"] = max(0, user_ms)
            usage["cpu_system_ms"] = max(0, system_ms)
            usage["max_process_rss_kib"] = max(0, max_rss)
    if rusage is None and RUSAGE_UNAVAILABLE not in reasons:
        reasons.append(RUSAGE_UNAVAILABLE)
    if peak_tree_rss_kib is not None:
        usage["peak_tree_rss_kib"] = max(0, int(peak_tree_rss_kib))
    usage["tree_rss_samples"] = max(0, int(tree_rss_samples))
    usage["availability"] = reasons
    return usage


def format_ceiling_seconds(seconds: int | None) -> str:
    """Format a ceiling in seconds as ``4h``, ``10m``, or ``45s``."""

    if seconds is None:
        return "—"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def format_cpu_cores(cpu_ms: int | None, wall_ms: int | None) -> str | None:
    """Return effective cores (CPU seconds over wall seconds), if computable."""

    if (
        type(cpu_ms) is not int
        or type(wall_ms) is not int
        or wall_ms < 1000
        or cpu_ms < 0
    ):
        return None
    return f"{cpu_ms / wall_ms:.1f}"


__all__ = [
    "CROSS_RUN_DIAGNOSTIC",
    "RUSAGE_UNAVAILABLE",
    "TREE_RSS_UNAVAILABLE",
    "build_resource_usage",
    "demand_context",
    "demand_file_path",
    "format_ceiling_seconds",
    "format_cpu_cores",
    "read_demand_grants",
    "record_run_demand",
    "tree_rss_kib",
]
