"""Pressure-recovery helpers: fail-open inventory, episode keys, and notices."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.core.disk_footprint_utils import DISK_SIZE_UNMEASURED
from sase.core.disk_footprint_utils import format_bytes
from sase.core.disk_footprint_utils import format_measured_bytes
from sase.core.time import local_now
from sase.notification_gates.durability import atomic_write_json, file_lock

INVENTORY_TIMEOUT_SECONDS = 20.0
EPISODE_SCHEMA_VERSION = 1
PRESSURE_NOTICE_SENDER = "disk_pressure"
PRESSURE_REAP_OWNERS = frozenset(
    {
        "managed_tmp_reaper",
        "proc_runtime_sweep",
        "proc_log_lock_sweep",
        "registry_tmp_sweep",
        "tool_run_retention",
    }
)
_UNATTRIBUTED_OWNER = "unattributed"
_EPISODE_STATE_NAME = "disk_pressure_episodes.json"


@dataclass(frozen=True)
class _InventoryAttempt:
    """Fail-open result of a pressure-recovery inventory collection."""

    report: Any | None
    unavailable_reason: str | None


def collect_inventory_fail_open(
    collect_fn: Callable[[], Any],
    *,
    timeout_seconds: float = INVENTORY_TIMEOUT_SECONDS,
) -> _InventoryAttempt:
    """Collect inventory without delaying or skipping recovery.

    The inventory's own scan budget is typically 5s. This hard cap is larger so
    a healthy scan can finish, while hung discovery cannot block the chop.
    """

    if timeout_seconds <= 0:
        return _InventoryAttempt(None, "inventory timed out")
    pool = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="disk-pressure-inventory"
    )
    try:
        future = pool.submit(collect_fn)
        try:
            return _InventoryAttempt(future.result(timeout=timeout_seconds), None)
        except FuturesTimeoutError:
            return _InventoryAttempt(None, "inventory timed out")
        except Exception as exc:  # noqa: BLE001 - attribution is fail-open.
            return _InventoryAttempt(
                None, f"{type(exc).__name__}: {_bounded_error(exc)}"
            )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def filesystem_id(row: Mapping[str, Any]) -> str:
    """Stable per-filesystem episode key part from a pressure observation."""

    label = str(row.get("label") or "").strip()
    raw = label or str(row.get("measurement_path") or row.get("path") or "unknown")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("_")
    return slug or "unknown"


def pressure_notice_key(filesystem: str, episode_id: str) -> str:
    return f"disk_pressure:{filesystem}:{episode_id}"


def pressure_escalation_key(filesystem: str, episode_id: str) -> str:
    return f"disk_pressure:{filesystem}:{episode_id}:escalation"


def _episode_state_path(home: Path) -> Path:
    return home / "axe" / _EPISODE_STATE_NAME


def start_or_continue_episode(home: Path, filesystem: str) -> str:
    """Return the active episode id for *filesystem*, creating one if needed."""

    episodes = _read_episodes(home)
    current = episodes.get(filesystem)
    if isinstance(current, dict):
        existing = current.get("episode_id")
        if isinstance(existing, str) and existing:
            return existing
    episode_id = uuid4().hex
    episodes[filesystem] = {
        "episode_id": episode_id,
        "started_at": local_now().isoformat(),
    }
    _write_episodes(home, episodes)
    return episode_id


def end_inactive_episodes(home: Path, active: set[str]) -> None:
    """Drop episode records for filesystems that are no longer under pressure."""

    episodes = _read_episodes(home)
    kept = {key: value for key, value in episodes.items() if key in active}
    if kept != episodes:
        _write_episodes(home, kept)


def end_all_episodes(home: Path) -> None:
    """Clear every pressure episode; used when the chop reports ``space_ok``."""

    _write_episodes(home, {})


def build_pressure_notes(
    *,
    pressure_row: Mapping[str, Any],
    free_percent: float,
    reclaimed_bytes: int,
    available_after_bytes: int | None,
    recovery_target_bytes: int,
    top_rows: Sequence[Mapping[str, Any]],
    report: Any | None,
    unavailable_reason: str | None,
    changed_owners: tuple[str, ...],
    failed_owners: tuple[str, ...],
    blocked_owners: tuple[str, ...],
    incomplete_owners: tuple[str, ...],
) -> list[str]:
    """Build the episode notice: free space and recovery first."""

    notes = [
        (
            "SASE disk pressure: "
            f"{format_bytes(int(pressure_row['free_bytes']))} free "
            f"on {pressure_row['label']} ({free_percent:.1f}%)"
        ),
        (
            "Recovery: reclaimed "
            f"{format_bytes(reclaimed_bytes)}; available after "
            f"{_available_text(available_after_bytes)} "
            f"(target {format_bytes(recovery_target_bytes)})"
        ),
    ]
    if unavailable_reason is not None:
        notes.append(f"Attribution unavailable: {unavailable_reason}")
    else:
        unmeasured = _unmeasured_owners(report)
        if unmeasured:
            count = len(unmeasured)
            owner_word = "owner" if count == 1 else "owners"
            notes.append(f"Unmeasured {owner_word} ({count}): " + "; ".join(unmeasured))
        measured = _measured_top_owners(top_rows)
        notes.append(
            "Top measured owners: "
            + (
                "; ".join(f"{row['owner']} {_owner_size_text(row)}" for row in measured)
                if measured
                else "none reported"
            )
        )
        residual = _residual_line(report)
        if residual is not None:
            notes.append(residual)
    notes.extend(
        (
            "Reap changed owners: " + _owner_list(changed_owners),
            "Reap failed owners: " + _owner_list(failed_owners),
            "Reap blocked/incomplete owners: "
            + _owner_list((*blocked_owners, *incomplete_owners)),
        )
    )
    return notes


def build_escalation_notes(
    *,
    pressure_row: Mapping[str, Any],
    reclaimed_bytes: int,
    available_after_bytes: int,
    recovery_target_bytes: int,
    owners: Sequence[Mapping[str, Any]],
    top_rows: Sequence[Mapping[str, Any]],
    report: Any | None,
) -> list[str]:
    """Build the distinct missed-target escalation notice."""

    notes = [
        (
            "SASE disk pressure recovery missed on "
            f"{pressure_row['label']}: "
            f"{format_bytes(available_after_bytes)} available after vs "
            f"{format_bytes(recovery_target_bytes)} target"
        ),
        f"Reclaimed: {format_bytes(reclaimed_bytes)}",
        f"Available after: {format_bytes(available_after_bytes)}",
        f"Recovery target: {format_bytes(recovery_target_bytes)}",
        "Blockers: " + _blocker_summary(owners),
    ]
    unreaped = _unreaped_owner_lines(top_rows, report)
    notes.append(
        "Largest unreaped measured owners: "
        + ("; ".join(unreaped) if unreaped else "none reported")
    )
    return notes


def pressure_plus_one_note(
    *,
    free_bytes: int,
    reclaimed_bytes: int,
) -> str:
    return (
        "still under pressure: "
        f"{format_bytes(free_bytes)} free, reclaimed {format_bytes(reclaimed_bytes)}"
    )


def escalation_plus_one_note(
    *,
    available_after_bytes: int,
    recovery_target_bytes: int,
) -> str:
    return (
        "recovery still short: "
        f"{format_bytes(available_after_bytes)} available vs "
        f"{format_bytes(recovery_target_bytes)} target"
    )


def _read_episodes(home: Path) -> dict[str, dict[str, str]]:
    path = _episode_state_path(home)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema_version") != (
        EPISODE_SCHEMA_VERSION
    ):
        return {}
    raw = payload.get("episodes")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        episode_id = value.get("episode_id")
        started_at = value.get("started_at")
        if isinstance(episode_id, str) and episode_id and isinstance(started_at, str):
            result[key] = {"episode_id": episode_id, "started_at": started_at}
    return result


def _write_episodes(home: Path, episodes: Mapping[str, Mapping[str, str]]) -> None:
    path = _episode_state_path(home)
    try:
        with file_lock(path.with_suffix(path.suffix + ".lock")):
            atomic_write_json(
                path,
                {
                    "schema_version": EPISODE_SCHEMA_VERSION,
                    "episodes": dict(episodes),
                },
            )
    except Exception:  # noqa: BLE001 - episode persistence is fail-open.
        return


def _unmeasured_owners(report: Any | None) -> tuple[str, ...]:
    if report is None:
        return ()
    owners = getattr(report, "unmeasured_owners", None)
    if owners:
        return tuple(str(owner) for owner in owners)
    return ()


def _measured_top_owners(
    top_rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    measured: list[dict[str, Any]] = []
    for row in top_rows:
        if str(row.get("size_state") or "measured") == DISK_SIZE_UNMEASURED:
            continue
        if str(row.get("owner") or "") == _UNATTRIBUTED_OWNER:
            continue
        measured.append(dict(row))
    return tuple(measured)


def _owner_size_text(row: Mapping[str, Any]) -> str:
    size = row.get("size_bytes") or 0
    state = str(row.get("size_state") or "measured")
    return format_measured_bytes(int(size), state)


def _residual_line(report: Any | None) -> str | None:
    if report is None:
        return None
    rows = getattr(report, "rows", ())
    for row in rows:
        payload = _row_payload(row)
        if payload.get("owner") != _UNATTRIBUTED_OWNER:
            continue
        horizon = str(payload.get("horizon") or "").strip()
        size_state = str(payload.get("size_state") or "measured")
        size = payload.get("exclusive_size_bytes")
        if size is None:
            size = payload.get("size_bytes") or 0
        size_text = format_measured_bytes(int(size), size_state)
        if horizon:
            return f"Residual ({size_text}): {horizon}"
        name = str(payload.get("name") or _UNATTRIBUTED_OWNER)
        return f"Residual ({size_text}): {name}"
    return None


def _blocker_summary(owners: Sequence[Mapping[str, Any]]) -> str:
    counts: Counter[str] = Counter()
    for owner in owners:
        status = str(owner.get("status") or "")
        if status not in {"blocked", "incomplete"}:
            continue
        name = str(owner.get("owner") or "unknown")
        reasons = owner.get("reasons") or ()
        reason_list = [str(reason) for reason in reasons if reason]
        if not reason_list:
            reason_list = [status]
        for reason in reason_list:
            counts[f"{name} {reason}"] += 1
    if not counts:
        return "none"
    return ", ".join(f"{label}×{count}" for label, count in sorted(counts.items()))


def _unreaped_owner_lines(
    top_rows: Sequence[Mapping[str, Any]],
    report: Any | None,
) -> list[str]:
    reclaim_by_owner: dict[str, str | None] = {}
    reclaim_by_key: dict[tuple[str, str], str | None] = {}
    if report is not None:
        for row in getattr(report, "rows", ()):
            payload = _row_payload(row)
            owner = str(payload.get("owner") or "")
            if (
                not owner
                or owner in PRESSURE_REAP_OWNERS
                or owner == _UNATTRIBUTED_OWNER
            ):
                continue
            if str(payload.get("size_state") or "measured") == DISK_SIZE_UNMEASURED:
                continue
            reclaim = payload.get("reclaim")
            reclaim_text = str(reclaim) if reclaim else None
            reclaim_by_owner.setdefault(owner, reclaim_text)
            reclaim_by_key[(owner, str(payload.get("path") or ""))] = reclaim_text
    lines: list[str] = []
    for row in _measured_top_owners(top_rows):
        owner = str(row.get("owner") or "")
        if owner in PRESSURE_REAP_OWNERS or owner == _UNATTRIBUTED_OWNER:
            continue
        path = str(row.get("path") or "")
        reclaim = reclaim_by_key.get((owner, path), reclaim_by_owner.get(owner))
        command = reclaim or "no reclaim command"
        lines.append(f"{owner} {_owner_size_text(row)} ({command})")
    return lines


def _row_payload(row: Any) -> Mapping[str, Any]:
    if hasattr(row, "to_json_dict"):
        payload = row.to_json_dict()
        if isinstance(payload, Mapping):
            return payload
    if isinstance(row, Mapping):
        return row
    return {}


def _available_text(available_after_bytes: int | None) -> str:
    if available_after_bytes is None:
        return "unknown"
    return format_bytes(available_after_bytes)


def _owner_list(owners: tuple[str, ...]) -> str:
    return ",".join(owners) if owners else "none"


def _bounded_error(exc: Exception) -> str:
    detail = " ".join(str(exc).split())
    return detail[:300] + ("…" if len(detail) > 300 else "")


__all__ = [
    "EPISODE_SCHEMA_VERSION",
    "INVENTORY_TIMEOUT_SECONDS",
    "PRESSURE_NOTICE_SENDER",
    "PRESSURE_REAP_OWNERS",
    "build_escalation_notes",
    "build_pressure_notes",
    "collect_inventory_fail_open",
    "end_all_episodes",
    "end_inactive_episodes",
    "escalation_plus_one_note",
    "filesystem_id",
    "pressure_escalation_key",
    "pressure_notice_key",
    "pressure_plus_one_note",
    "start_or_continue_episode",
]
