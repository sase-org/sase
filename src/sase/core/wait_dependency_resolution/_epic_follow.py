"""Epic-follow fact collector over the wait-dependency index.

Builds the pure ``wait_epic_follow_reduce`` input for every armed target and
calls the Rust binding. Nothing here is wired into a release path yet; the
release phase routes every release path through one shared decision function
built on top of this collector.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class _EpicFollowMemberFacts:
    name: str = ""
    artifact_dir: str = ""
    recorded_epic_ids: tuple[str, ...] = ()
    attributed_epic_ids: tuple[str, ...] = ()
    legacy_epic_bead_id: str | None = None
    is_epic_worker: bool = False
    launch_reserved: bool = False
    launch_argv_present: bool = False
    launch_in_flight: bool = False
    launch_reserved_age_seconds: float | None = None
    member_dismissed: bool = False
    resume_command: str | None = None


@dataclass(frozen=True)
class _EpicFollowTargetFacts:
    target: str = ""
    agent_resolved: bool = False
    previous_state: str | None = None
    previous_since: float | None = None
    cycle_epic_ids: tuple[str, ...] = ()
    members: tuple[_EpicFollowMemberFacts, ...] = ()


@dataclass(frozen=True)
class EpicFollowDecision:
    target: str = ""
    state: str = "none"
    epic_ids: tuple[str, ...] = ()
    members: tuple[str, ...] = ()
    since: float = 0.0
    reason: str | None = None
    detail: str | None = None
    resume_command: str | None = None
    skipped_epic_ids: tuple[str, ...] = ()
    launching_overdue: bool = False


def _nonempty_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _field(source: object, name: str) -> Any:
    if isinstance(source, dict):
        return source.get(name)
    return getattr(source, name, None)


def _waiter_own_bead_ids(waiter_meta: object) -> list[str]:
    ids: list[str] = []
    for key in ("bead_id", "epic_bead_id", "phase_bead_id"):
        value = _nonempty_str(_field(waiter_meta, key))
        if value is not None and value not in ids:
            ids.append(value)
    return ids


def _waiter_artifact_dir(waiter_meta: object) -> str | None:
    value = _field(waiter_meta, "artifact_dir")
    if isinstance(value, (str, Path)) and str(value).strip():
        return str(value)
    return None


def _previous_follow_map(
    previous_follows: Iterable[object] | None,
) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    if not previous_follows:
        return mapped
    for entry in previous_follows:
        target = _nonempty_str(_field(entry, "target"))
        if target is None or target in mapped:
            continue
        mapped[target] = {
            "state": _field(entry, "state"),
            "since": _field(entry, "since"),
        }
    return mapped


def _is_pinned_following(
    previous_follows: Iterable[object] | None, target: str
) -> bool:
    if not previous_follows:
        return False
    for entry in previous_follows:
        if _field(entry, "target") != target:
            continue
        state = _field(entry, "state")
        if isinstance(state, str) and state.strip().lower() == "following":
            return True
    return False


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _epic_launch_argv(member_dir: Path) -> list[str] | None:
    data = _read_json_object(member_dir / "epic_launch_argv.json")
    if data is None:
        return None
    argv = data.get("argv")
    if not isinstance(argv, list) or not argv:
        return None
    return [str(item) for item in argv]


def _plan_ref_for_member(member_dir: Path, argv: list[str] | None) -> str | None:
    if argv is not None and len(argv) >= 4 and argv[:3] == ["sase", "bead", "work"]:
        candidate = _nonempty_str(argv[3])
        if candidate is not None:
            return candidate
    plan_data = _read_json_object(member_dir / "plan_path.json")
    if plan_data is not None:
        candidate = _nonempty_str(plan_data.get("plan_path"))
        if candidate is not None:
            return candidate
    meta = _read_json_object(member_dir / "agent_meta.json")
    if meta is not None:
        for key in ("sdd_plan_path", "plan_path"):
            candidate = _nonempty_str(meta.get(key))
            if candidate is not None:
                return candidate
    return None


def _resume_command(member_dir: Path, argv: list[str] | None) -> str | None:
    plan = _plan_ref_for_member(member_dir, argv)
    if plan is None:
        return None
    try:
        from sase.bead.epic_launch import build_epic_launch_argv
    except Exception:
        return None
    try:
        built = build_epic_launch_argv(plan, artifacts_dir=member_dir)
    except Exception:
        return None
    import shlex

    return shlex.join(built)


def _active_launch_keys() -> set[str]:
    try:
        from sase.bead.epic_launch_handoff_io import active_epic_launch_keys
    except Exception:
        return set()
    try:
        return set(active_epic_launch_keys())
    except Exception:
        return set()


def _launch_key_for_dir(member_dir: str) -> str | None:
    try:
        from sase.bead.epic_launch_handoff_io import epic_completion_key
    except Exception:
        return None
    try:
        return epic_completion_key(member_dir)
    except Exception:
        return None


def collect_epic_follow_facts(
    index: Any,
    *,
    armed_targets: Iterable[str],
    resolved_deps: Iterable[object] = (),
    previous_follows: Iterable[object] | None = None,
    waiter_meta: object | None = None,
    now: float | None = None,
    dismissed_artifact_dir: str | Path | None = None,
    launching_grace_seconds: float = 600.0,
    launch_settle_seconds: float = 120.0,
) -> list[EpicFollowDecision]:
    """Collect per-member facts and reduce them to follow decisions.

    Members come from the index's member enumeration for the resolved
    entity. Recorded epics, worker flags, legacy IDs, and the outcome come
    from the index candidate, so the hot path does no extra I/O. Only
    members that would otherwise be launching or blocked cost file probes
    (``epic_launch_argv.json`` presence and age, in-flight launch lookups,
    and memoized bead-store attribution). Already-following (pinned)
    targets are skipped.
    """
    targets = [target for target in armed_targets if isinstance(target, str) and target]
    if not targets:
        return []
    resolved_items = tuple(resolved_deps)
    previous_map = _previous_follow_map(previous_follows)
    waiter_own_bead_ids = _waiter_own_bead_ids(waiter_meta or {})
    waiter_dir = _waiter_artifact_dir(waiter_meta or {})
    if dismissed_artifact_dir is not None:
        dismissed_str = str(dismissed_artifact_dir)
    else:
        dismissed_str = None
    moment = time.time() if now is None else float(now)
    active_keys = _active_launch_keys()
    attributed_cache: dict[tuple[str, str, str], tuple[str, ...]] = {}

    from sase.core.wait_dependency_resolution._epic_follow_cycle import (
        cycle_epic_ids_for_members,
        waiter_wait_names,
    )

    waiter_names = waiter_wait_names(waiter_meta or {})

    wire_targets: list[_EpicFollowTargetFacts] = []
    for target in targets:
        if _is_pinned_following(previous_follows, target):
            continue
        agent_resolved = _target_is_resolved(index, target, resolved_items, waiter_dir)
        members: tuple[_EpicFollowMemberFacts, ...] = ()
        if agent_resolved:
            members = _member_facts_for_target(
                index,
                target,
                resolved_items,
                waiter_dir,
                dismissed_str,
                moment,
                active_keys,
                attributed_cache,
            )
        previous = previous_map.get(target, {})
        raw_state = previous.get("state")
        previous_state = (
            raw_state.strip().lower()
            if isinstance(raw_state, str) and raw_state.strip()
            else None
        )
        raw_since = previous.get("since")
        previous_since: float | None = None
        if isinstance(raw_since, (int, float)) and not isinstance(raw_since, bool):
            previous_since = float(raw_since)
        try:
            cycle_epic_ids = (
                cycle_epic_ids_for_members(
                    index,
                    members,
                    waiter_own_bead_ids=waiter_own_bead_ids,
                    waiter_names=waiter_names,
                    waiter_dir=waiter_dir,
                )
                if members
                else ()
            )
        except Exception:
            cycle_epic_ids = ()
        wire_targets.append(
            _EpicFollowTargetFacts(
                target=target,
                agent_resolved=agent_resolved,
                previous_state=previous_state,
                previous_since=previous_since,
                cycle_epic_ids=cycle_epic_ids,
                members=members,
            )
        )

    if not wire_targets:
        return []
    payload = {
        "waiter_own_bead_ids": list(waiter_own_bead_ids),
        "now": moment,
        "launching_grace_seconds": launching_grace_seconds,
        "launch_settle_seconds": launch_settle_seconds,
        "targets": [
            {
                "target": facts.target,
                "agent_resolved": facts.agent_resolved,
                "previous_state": facts.previous_state,
                "previous_since": facts.previous_since,
                "cycle_epic_ids": list(facts.cycle_epic_ids),
                "members": [
                    {
                        "name": member.name,
                        "artifact_dir": member.artifact_dir,
                        "recorded_epic_ids": list(member.recorded_epic_ids),
                        "attributed_epic_ids": list(member.attributed_epic_ids),
                        "legacy_epic_bead_id": member.legacy_epic_bead_id,
                        "is_epic_worker": member.is_epic_worker,
                        "launch_reserved": member.launch_reserved,
                        "launch_argv_present": member.launch_argv_present,
                        "launch_in_flight": member.launch_in_flight,
                        "launch_reserved_age_seconds": member.launch_reserved_age_seconds,
                        "member_dismissed": member.member_dismissed,
                        "resume_command": member.resume_command,
                    }
                    for member in facts.members
                ],
            }
            for facts in wire_targets
        ],
    }
    from sase.core.rust import require_rust_binding

    reduce = require_rust_binding("wait_epic_follow_reduce")
    raw_decisions = reduce(payload)
    decisions: list[EpicFollowDecision] = []
    for raw in raw_decisions:
        decisions.append(_decision_from_wire(raw, moment))
    return decisions


def _target_is_resolved(
    index: Any,
    target: str,
    resolved_items: tuple[object, ...],
    waiter_dir: str | None,
) -> bool:
    if target in resolved_items:
        return True
    is_resolved = getattr(index, "is_resolved", None)
    if not callable(is_resolved):
        return False
    try:
        if target.startswith("@"):
            waiter_timestamp = Path(waiter_dir).name if waiter_dir else None
            return bool(
                is_resolved(
                    target,
                    exclude_artifact_dir=waiter_dir,
                    newer_than=waiter_timestamp,
                )
            )
        return bool(is_resolved(target, exclude_artifact_dir=waiter_dir))
    except Exception:
        return False


def _member_dirs_for_target(
    index: Any,
    target: str,
    resolved_items: tuple[object, ...],
    waiter_dir: str | None,
) -> list[str]:
    getter = getattr(index, "dependency_member_dirs", None)
    if not callable(getter):
        return []
    try:
        dirs = getter(
            [target],
            (),
            resolved_items,
            self_artifact_dir=waiter_dir,
        )
    except Exception:
        return []
    ordered = sorted(str(item) for item in dirs if str(item).strip())
    return ordered


def _member_facts_for_target(
    index: Any,
    target: str,
    resolved_items: tuple[object, ...],
    waiter_dir: str | None,
    dismissed_str: str | None,
    now: float,
    active_keys: set[str],
    attributed_cache: dict[tuple[str, str, str], tuple[str, ...]],
) -> tuple[_EpicFollowMemberFacts, ...]:
    from sase.core.wait_dependency_resolution._artifact_state import same_artifact_dir

    member_dirs = _member_dirs_for_target(index, target, resolved_items, waiter_dir)
    if dismissed_str and not any(
        same_artifact_dir(candidate, dismissed_str) for candidate in member_dirs
    ):
        member_dirs = [*member_dirs, dismissed_str]
    by_dir = getattr(index, "artifacts_by_dir", {}) or {}
    facts: list[_EpicFollowMemberFacts] = []
    for member_dir in member_dirs:
        candidate = by_dir.get(member_dir)
        if candidate is None:
            for key, value in by_dir.items():
                try:
                    if same_artifact_dir(key, member_dir):
                        candidate = value
                        member_dir = key
                        break
                except Exception:
                    continue
        facts.append(
            _member_facts_for_dir(
                candidate,
                member_dir,
                dismissed_str,
                now,
                active_keys,
                attributed_cache,
            )
        )
    return tuple(facts)


def _member_facts_for_dir(
    candidate: Any,
    member_dir: str,
    dismissed_str: str | None,
    now: float,
    active_keys: set[str],
    attributed_cache: dict[tuple[str, str, str], tuple[str, ...]],
) -> _EpicFollowMemberFacts:
    from sase.core.wait_dependency_resolution._artifact_state import same_artifact_dir

    if candidate is not None:
        name = _nonempty_str(getattr(candidate, "name", "")) or ""
        recorded = tuple(getattr(candidate, "recorded_epic_ids", ()) or ())
        legacy = getattr(candidate, "legacy_epic_bead_id", None)
        legacy = legacy if isinstance(legacy, str) and legacy.strip() else None
        is_worker = bool(getattr(candidate, "is_epic_worker", False))
        outcome = getattr(candidate, "outcome", None)
        project = _nonempty_str(getattr(candidate, "project_name", "")) or ""
    else:
        name = Path(member_dir).name
        recorded = ()
        legacy = None
        is_worker = False
        outcome = None
        project = ""
    member_path = Path(member_dir)
    argv = _epic_launch_argv(member_path)
    argv_present = argv is not None
    age: float | None = None
    if argv_present:
        try:
            age = max(
                0.0, now - (member_path / "epic_launch_argv.json").stat().st_mtime
            )
        except OSError:
            age = None
    launch_key = _launch_key_for_dir(member_dir)
    in_flight = launch_key is not None and launch_key in active_keys
    reserved = bool(outcome == "epic_approved" or argv_present)
    dismissed = bool(
        dismissed_str is not None
        and dismissed_str.strip()
        and _safe_same_dir(member_dir, dismissed_str)
    )
    attributed: tuple[str, ...] = ()
    if not recorded and (legacy is None or is_worker):
        attributed = _attributed_for_member(
            project, name, member_path, argv, attributed_cache
        )
    resume_command: str | None = None
    if reserved or dismissed:
        resume_command = _resume_command(member_path, argv)
    return _EpicFollowMemberFacts(
        name=name,
        artifact_dir=member_dir,
        recorded_epic_ids=tuple(recorded),
        attributed_epic_ids=attributed,
        legacy_epic_bead_id=legacy,
        is_epic_worker=is_worker,
        launch_reserved=reserved,
        launch_argv_present=argv_present,
        launch_in_flight=in_flight,
        launch_reserved_age_seconds=age,
        member_dismissed=dismissed,
        resume_command=resume_command,
    )


def _safe_same_dir(left: str, right: str) -> bool:
    from sase.core.wait_dependency_resolution._artifact_state import same_artifact_dir

    try:
        return bool(same_artifact_dir(left, right))
    except Exception:
        return False


def _attributed_for_member(
    project: str,
    creator_name: str,
    member_path: Path,
    argv: list[str] | None,
    cache: dict[tuple[str, str, str], tuple[str, ...]],
) -> tuple[str, ...]:
    plan_ref = _plan_ref_for_member(member_path, argv)
    if not project.strip() or not creator_name.strip() or plan_ref is None:
        return ()
    key = (project.strip(), creator_name.strip(), plan_ref.strip())
    if key in cache:
        return cache[key]
    try:
        from sase.core.created_epics import attributed_epic_ids
    except Exception:
        cache[key] = ()
        return ()
    try:
        ids = attributed_epic_ids(
            key[0],
            creator_global_name=key[1],
            plan_ref=key[2],
        )
    except Exception:
        cache[key] = ()
        return ()
    result = tuple(dict.fromkeys(ids))
    cache[key] = result
    return result


def _decision_from_wire(raw: object, now: float) -> EpicFollowDecision:
    def _get(name: str, default: Any = None) -> Any:
        return _field(raw, name) if _field(raw, name) is not None else default

    def _str_tuple(value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            return ()
        return tuple(str(item) for item in value if str(item).strip())

    def _optional_str(value: object) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() else None

    raw_since = _get("since", now)
    since = (
        float(raw_since)
        if isinstance(raw_since, (int, float)) and not isinstance(raw_since, bool)
        else now
    )
    return EpicFollowDecision(
        target=str(_get("target", "")),
        state=str(_get("state", "none")),
        epic_ids=_str_tuple(_get("epic_ids", ())),
        members=_str_tuple(_get("members", ())),
        since=since,
        reason=_optional_str(_get("reason")),
        detail=_optional_str(_get("detail")),
        resume_command=_optional_str(_get("resume_command")),
        skipped_epic_ids=_str_tuple(_get("skipped_epic_ids", ())),
        launching_overdue=bool(_get("launching_overdue", False)),
    )


__all__ = [
    "EpicFollowDecision",
    "collect_epic_follow_facts",
]
