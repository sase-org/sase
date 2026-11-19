#!/usr/bin/env python3
"""Managed SASE temp root reaping chop script.

Runs on the hourly ``housekeeping`` lumberjack rather than on an interactive
path: the first pass over a long-neglected root walks tens of thousands of
entries, which must never sit in front of a TUI startup or a CLI command.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.core import managed_tmp_reaper as _managed_tmp_reaper
from sase.core.disk_pressure import filesystem_pressure_policy
from sase.core.managed_tmp_reaper import reap_managed_tmpdir
from sase.core.managed_tmp_roots import (
    effective_managed_tmp_roots as _effective_managed_tmp_roots,
)
from sase.core.paths import sase_home
from sase.notification_gates.durability import atomic_write_json, file_lock

effective_managed_tmp_roots = _effective_managed_tmp_roots


@builtin_chop("managed_tmp_reap")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    effective_root = _managed_tmp_reaper.managed_tmpdir_root()
    roots = effective_managed_tmp_roots(
        effective_root=effective_root, sase_home=sase_home()
    )
    results = [_reap_one_root(root) for root in roots]
    _report_standing_skips(
        runtime,
        _standing_skip_state_path(),
        [
            (result.root, reason)
            for result in results
            for reason in getattr(result, "skip_reasons", ())
        ],
    )
    for result in results:
        # Always name each scanned root: a `nothing_stale` result over the
        # wrong root is exactly the sase-15q failure mode.
        runtime.log(result.describe(), "cyan")
        for error in getattr(result, "removal_errors", ())[:5]:
            runtime.log.warning(f"managed_tmp_reap removal error: {error}")
    runtime.log.info(_managed_tmp_roots_info([result.root for result in results]))
    combined = _combine_results(results)
    # A mismatch between the effective root and the default root is now
    # harmless: every registered root is reaped, so there is no warning.
    failed = int(combined["failed"])
    result = runtime.emit_summary(
        combined,
        reason=(
            "removal_failed"
            if failed
            else "nothing_stale"
            if not combined["removed"]
            else None
        ),
    )
    if failed:
        result.status = "check_error"
    return result


def _standing_skip_state_path() -> Path:
    return sase_home() / "axe" / "managed_tmp_reap_standing_skips.json"


def _report_standing_skips(
    runtime: BuiltinChopRuntime,
    state_path: Path,
    skips: list[tuple[Path, str]],
) -> None:
    """Log only changes to skips, retaining the latest set between passes.

    A corrupt or unwritable state file falls back to the previous bounded
    warning behavior so persistence problems cannot hide unsafe-to-reap items.
    """
    try:
        with file_lock(state_path.with_suffix(state_path.suffix + ".lock")):
            previous = _read_standing_skip_state(state_path)
            if previous is None:
                _log_standing_skip_fallback(runtime, skips)
                return
            current = _standing_skip_records(skips)
            if current.keys() != previous.keys() and not _write_standing_skip_state(
                state_path, current
            ):
                _log_standing_skip_fallback(runtime, skips)
                return
    except Exception:  # noqa: BLE001 - fail open to visible warnings
        _log_standing_skip_fallback(runtime, skips)
        return

    unchanged = 0
    for identity, record in current.items():
        old = previous.get(identity)
        if old is None or old["reason_class"] != record["reason_class"]:
            runtime.log.warning(f"managed_tmp_reap skipped: {record['reason']}")
        else:
            runtime.log.debug(
                f"managed_tmp_reap standing skip unchanged: {record['reason']}"
            )
            unchanged += 1
    current_entries = {(record["root"], record["entry"]) for record in current.values()}
    for record in previous.values():
        if (record["root"], record["entry"]) not in current_entries:
            runtime.log.info(
                "managed_tmp_reap skip cleared: "
                f"{record['root']} {record['entry']} ({record['reason_class']})"
            )
    if unchanged:
        runtime.log.info(f"managed_tmp_reap: {unchanged} standing skips unchanged")


def _read_standing_skip_state(path: Path) -> dict[str, dict[str, str]] | None:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return None
    skips = payload.get("skips")
    if not isinstance(skips, dict):
        return None
    result: dict[str, dict[str, str]] = {}
    for identity, value in skips.items():
        if not isinstance(identity, str) or not isinstance(value, dict):
            return None
        fields = ("root", "entry", "reason_class", "reason")
        if any(not isinstance(value.get(field), str) for field in fields):
            return None
        result[identity] = {field: value[field] for field in fields}
    return result


def _standing_skip_records(
    skips: list[tuple[Path, str]],
) -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    for root, reason in skips:
        root_text = str(root)
        entry = _skip_entry(root_text, reason)
        reason_class = _skip_reason_class(reason)
        identity = hashlib.sha256(
            f"{root_text}\0{entry}\0{reason_class}".encode()
        ).hexdigest()
        records.setdefault(
            identity,
            {
                "root": root_text,
                "entry": entry,
                "reason_class": reason_class,
                "reason": reason,
            },
        )
    return records


def _skip_entry(root: str, reason: str) -> str:
    """Extract the longest mentioned path inside the scanned root."""
    root_prefix = root.rstrip("/") + "/"
    paths = re.findall(r"(?<![A-Za-z0-9_])/(?:[^/\s,:]+/)*[^/\s,:]+", reason)
    candidates = [
        candidate.rstrip("'\".,;:)]}")
        for candidate in paths
        if candidate == root or candidate.startswith(root_prefix)
    ]
    nested = [candidate for candidate in candidates if candidate != root]
    return max(nested, key=len) if nested else root


def _skip_reason_class(reason: str) -> str:
    lowered = reason.lower()
    classes = (
        ("environ unreadable", "process environ unreadable"),
        ("newest write time is unobservable", "newest write time unobservable"),
        ("liveness was incomplete", "liveness incomplete"),
        ("could not fully list", "directory listing incomplete"),
        ("could not inspect", "entry inspection failed"),
        ("vanished during scan", "entry vanished during scan"),
    )
    for fragment, label in classes:
        if fragment in lowered:
            return label
    normalized = re.sub(
        r"(?<![A-Za-z0-9_])/(?:[^/\s,:]+/)*[^/\s,:]+", "<path>", lowered
    )
    normalized = re.sub(r"\bpid\s+\d+\b", "pid <n>", normalized)
    normalized = re.sub(r"\b\d+\s+\(", "<n> (", normalized)
    return " ".join(normalized.split())


def _write_standing_skip_state(
    path: Path,
    skips: dict[str, dict[str, str]],
) -> bool:
    try:
        atomic_write_json(path, {"schema_version": 1, "skips": skips})
    except OSError:
        return False
    return True


def _log_standing_skip_fallback(
    runtime: BuiltinChopRuntime,
    skips: list[tuple[Path, str]],
) -> None:
    by_root: dict[Path, list[str]] = {}
    for root, reason in skips:
        by_root.setdefault(root, []).append(reason)
    for reasons in by_root.values():
        for reason in reasons[:5]:
            runtime.log.warning(f"managed_tmp_reap skipped: {reason}")


def _reap_one_root(root: Path) -> Any:
    policy = filesystem_pressure_policy(
        label="managed_tmp",
        role="owner",
        path=root,
    )
    return reap_managed_tmpdir(
        root=root,
        filesystem_available_bytes=policy.free_bytes,
        pressure_min_available_bytes=policy.warn_free_bytes,
        pressure_recovery_available_bytes=policy.warn_free_bytes,
    )


def _combine_results(results: list[Any]) -> dict[str, Any]:
    """Sum per-root reaper results into one structured summary."""
    selected_by_subdir: dict[str, int] = {}
    removed_by_subdir: dict[str, int] = {}
    for result in results:
        for name, count in result.selected_by_subdir.items():
            selected_by_subdir[name] = selected_by_subdir.get(name, 0) + count
        for name, count in result.removed_by_subdir.items():
            removed_by_subdir[name] = removed_by_subdir.get(name, 0) + count
    triggers = [result.pressure_trigger for result in results]
    triggers = [trigger for trigger in triggers if trigger]
    first_triggered = next(
        (result for result in results if result.pressure_trigger), None
    )
    pressure_available_bytes = (
        first_triggered.pressure_available_bytes
        if first_triggered is not None and first_triggered.pressure_trigger
        else None
    )
    pressure_recovery_available_bytes = (
        first_triggered.pressure_recovery_available_bytes
        if first_triggered is not None and first_triggered.pressure_trigger
        else None
    )
    min_age_seconds = (
        int(first_triggered.pressure_effective_min_age_seconds)
        if first_triggered is not None
        and first_triggered.pressure_trigger
        and first_triggered.pressure_effective_min_age_seconds is not None
        else None
    )
    return {
        "roots_scanned": len(results),
        "scanned": sum(result.scanned for result in results),
        "selected": sum(result.selected for result in results),
        "removed": sum(result.removed for result in results),
        "selected_bytes": sum(result.selected_bytes for result in results),
        "removed_bytes": sum(result.removed_bytes for result in results),
        "subdirs": len(removed_by_subdir),
        "ordinary_selected": sum(result.ordinary_selected for result in results),
        "ordinary_removed": sum(result.ordinary_removed for result in results),
        "ordinary_reclaimable_bytes": sum(
            result.ordinary_reclaimable_bytes for result in results
        ),
        "ordinary_reclaimed_bytes": sum(
            result.ordinary_reclaimed_bytes for result in results
        ),
        "launch_selected": sum(result.launch_selected for result in results),
        "launch_removed": sum(result.launch_removed for result in results),
        "launch_reclaimable_bytes": sum(
            result.launch_reclaimable_bytes for result in results
        ),
        "launch_reclaimed_bytes": sum(
            result.launch_reclaimed_bytes for result in results
        ),
        "dead_launch_scanned": sum(result.dead_launch_scanned for result in results),
        "dead_launch_selected": sum(result.dead_launch_selected for result in results),
        "dead_launch_removed": sum(result.dead_launch_removed for result in results),
        "dead_launch_reclaimable_bytes": sum(
            result.dead_launch_reclaimable_bytes for result in results
        ),
        "dead_launch_reclaimed_bytes": sum(
            result.dead_launch_reclaimed_bytes for result in results
        ),
        "dead_launch_preserved_live": sum(
            result.dead_launch_preserved_live for result in results
        ),
        "dead_launch_preserved_incomplete": sum(
            result.dead_launch_preserved_incomplete for result in results
        ),
        "dead_launch_observer": "+".join(
            dict.fromkeys(result.dead_launch_observer for result in results)
        ),
        "pressure_selected": sum(result.pressure_selected for result in results),
        "pressure_removed": sum(result.pressure_removed for result in results),
        "pressure_reclaimable_bytes": sum(
            result.pressure_reclaimable_bytes for result in results
        ),
        "pressure_reclaimed_bytes": sum(
            result.pressure_reclaimed_bytes for result in results
        ),
        "pressure_trigger": "+".join(dict.fromkeys(triggers)) if triggers else None,
        "pressure_available_bytes": pressure_available_bytes,
        "pressure_recovery_available_bytes": pressure_recovery_available_bytes,
        "pressure_min_age_seconds": min_age_seconds,
        "deindexed": sum(result.deindexed for result in results),
        "capped": int(any(result.capped for result in results)),
        "skipped": sum(result.skipped for result in results),
        "failed": sum(result.failed for result in results),
        "incomplete_observations": sum(
            result.incomplete_observations for result in results
        ),
    }


def _managed_tmp_roots_info(roots: list[Path]) -> str:
    """Describe the roots one reaper pass scanned, for the run log."""
    noun = "root" if len(roots) == 1 else "roots"
    listed = ", ".join(str(root) for root in roots)
    return f"managed tmp reaper scans {len(roots)} {noun}: {listed}"


def main() -> None:
    run_builtin_chop("managed_tmp_reap")


if __name__ == "__main__":
    main()
