"""Shared epic-follow release decision for every wait release path.

Routes the runner initial check, the parked-runner fallback, the AXE
``wait_checks`` chop, and kill/dismiss through one decision function so an
armed ``%wait(for_epic=)`` target is never released past an epic it launched.
User-authored agent targets are armed by default at parse time; a marker
with no ``wait_for_epics_of`` field (predating the feature, or explicitly
opted out) releases exactly as it does today.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.agent_directive_lock import (
    agent_directive_lock,
    runner_slot_marker_lock,
)
from sase.core.agent_meta_update import update_agent_meta_locked
from sase.core.wait_dependency_resolution._confirmation import (
    confirm_dependency_resolution,
)
from sase.core.wait_dependency_resolution._epic_follow import (
    EpicFollowDecision,
    collect_epic_follow_facts,
)
from sase.core.wait_dependency_resolution._index import WaitDependencyIndex
from sase.core.wait_dependency_resolution._json_io import read_json_dict
from sase.core.wait_dependency_resolution._resolution import (
    dependency_resolution_status,
)
from sase.core.wait_dependency_resolution._types import WaitDependencyStatus

_PERSISTED_FOLLOW_STATES = ("launching", "following", "blocked")
_BLOCKING_FOLLOW_STATES = ("agent", "launching", "blocked")
_PREIMAGE_FIELDS = (
    "waiting_for",
    "wait_for_epics_of",
    "wait_for_beads",
    "resolved_deps",
    "wait_epic_follows",
)


@dataclass(frozen=True)
class WaitEpicFollowPatch:
    """Full replacement lists plus the compare-and-set preimage."""

    wait_for_beads: tuple[Any, ...] = ()
    resolved_deps: tuple[Any, ...] = ()
    wait_epic_follows: tuple[dict[str, Any], ...] = ()
    expected: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WaitReleaseDecision:
    """One shared release verdict for a waiter marker."""

    status: WaitDependencyStatus
    follows: tuple[EpicFollowDecision, ...] = ()
    patch: WaitEpicFollowPatch | None = None
    releasable: bool = False
    confirmation_failed: bool = False


def _raw_list(marker: Mapping[str, Any], key: str) -> list[Any]:
    value = marker.get(key)
    return list(value) if isinstance(value, list) else []


def _str_list(marker: Mapping[str, Any], key: str) -> list[str]:
    return [item for item in _raw_list(marker, key) if isinstance(item, str)]


def armed_wait_epic_targets(marker: Mapping[str, Any]) -> list[str]:
    """Return the ordered intersection of ``wait_for_epics_of`` and ``waiting_for``.

    A missing or non-list ``wait_for_epics_of`` means there are no armed
    targets; implicit targets the contract phase kept out of
    ``wait_for_epics_of`` stay unarmed.
    """
    raw_armed = marker.get("wait_for_epics_of")
    if not isinstance(raw_armed, list):
        return []
    waiting_for = marker.get("waiting_for")
    if not isinstance(waiting_for, list):
        return []
    allowed = {item for item in waiting_for if isinstance(item, str)}
    ordered = [
        item for item in raw_armed if isinstance(item, str) and item and item in allowed
    ]
    return list(dict.fromkeys(ordered))


def _is_pinned_following(previous_follows: list[Any], target: str) -> bool:
    for entry in previous_follows:
        if not isinstance(entry, dict) or entry.get("target") != target:
            continue
        state = entry.get("state")
        if isinstance(state, str) and state.strip().lower() == "following":
            return True
    return False


def _read_waiter_meta(waiter_dir: str | Path) -> dict[str, Any]:
    meta = read_json_dict(Path(waiter_dir) / "agent_meta.json")
    if meta is None:
        return {"artifact_dir": str(waiter_dir)}
    result = dict(meta)
    result.setdefault("artifact_dir", str(waiter_dir))
    return result


def resolve_wait_release(
    index: WaitDependencyIndex,
    marker: Mapping[str, Any],
    *,
    waiter_dir: str | Path,
    closed_bead_ids: Collection[str] | None,
    now: float,
    dismissed_artifact_dir: str | Path | None = None,
    fresh_index: Callable[[], WaitDependencyIndex] | None = None,
) -> WaitReleaseDecision:
    """Decide one release pass for a waiter marker through epic follow.

    ``marker`` is the ``waiting.json`` object (or the launch dict before
    that file exists). ``now`` is an explicit epoch float so tests do not
    use the wall clock.
    """
    waiting_for = _raw_list(marker, "waiting_for")
    wait_identity_deps = _raw_list(marker, "wait_for_artifacts")
    wait_fork_sources = _raw_list(marker, "wait_for_fork_sources")
    wait_beads = _raw_list(marker, "wait_for_beads")
    wait_hoods = _raw_list(marker, "wait_for_hoods")
    resolved_deps = _raw_list(marker, "resolved_deps")
    armed = armed_wait_epic_targets(marker)
    agent_shaped = bool(
        waiting_for or wait_identity_deps or wait_fork_sources or wait_hoods
    )

    status = dependency_resolution_status(
        index,
        waiting_for,
        wait_identity_deps,
        resolved_deps,
        wait_fork_sources=wait_fork_sources,
        wait_beads=wait_beads,
        wait_hoods=wait_hoods,
        closed_bead_ids=closed_bead_ids,
        self_artifact_dir=waiter_dir,
    )
    if not armed:
        if status.resolved and agent_shaped and fresh_index is not None:
            try:
                confirmation = confirm_dependency_resolution(
                    index,
                    fresh_index,
                    waiting_for,
                    wait_identity_deps,
                    resolved_deps,
                    wait_fork_sources=wait_fork_sources,
                    wait_beads=wait_beads,
                    wait_hoods=wait_hoods,
                    closed_bead_ids=closed_bead_ids,
                    self_artifact_dir=waiter_dir,
                )
            except Exception:  # noqa: BLE001 - a failed confirmation must park.
                return WaitReleaseDecision(status, (), None, False, True)
            if not confirmation.confirmed:
                return WaitReleaseDecision(confirmation.status, (), None, False, True)
            return WaitReleaseDecision(confirmation.status, (), None, True, False)
        return WaitReleaseDecision(status, (), None, status.resolved, False)

    if fresh_index is None:
        return WaitReleaseDecision(status, (), None, False, True)
    collect_index = index
    if status.resolved and agent_shaped:
        memo: dict[str, WaitDependencyIndex] = {}

        def _memo_fresh() -> WaitDependencyIndex:
            built = fresh_index()
            memo["fresh"] = built
            return built

        try:
            confirmation = confirm_dependency_resolution(
                index,
                _memo_fresh,
                waiting_for,
                wait_identity_deps,
                resolved_deps,
                wait_fork_sources=wait_fork_sources,
                wait_beads=wait_beads,
                wait_hoods=wait_hoods,
                closed_bead_ids=closed_bead_ids,
                self_artifact_dir=waiter_dir,
            )
        except Exception:  # noqa: BLE001 - a failed confirmation must park.
            return WaitReleaseDecision(status, (), None, False, True)
        if not confirmation.confirmed:
            return WaitReleaseDecision(confirmation.status, (), None, False, True)
        fresh = memo.get("fresh", index)
        status = dependency_resolution_status(
            fresh,
            waiting_for,
            wait_identity_deps,
            resolved_deps,
            wait_fork_sources=wait_fork_sources,
            wait_beads=wait_beads,
            wait_hoods=wait_hoods,
            closed_bead_ids=closed_bead_ids,
            self_artifact_dir=waiter_dir,
        )
        collect_index = fresh

    previous_follows = _raw_list(marker, "wait_epic_follows")
    try:
        follows = collect_epic_follow_facts(
            collect_index,
            armed_targets=armed,
            resolved_deps=resolved_deps,
            previous_follows=previous_follows,
            waiter_meta=_read_waiter_meta(waiter_dir),
            now=now,
            dismissed_artifact_dir=dismissed_artifact_dir,
        )
    except Exception:  # noqa: BLE001 - unknown follow facts must park.
        return WaitReleaseDecision(status, (), None, False, False)
    patch, pending_promotion = _build_follow_patch(marker, resolved_deps, follows)
    if any(decision.state in _BLOCKING_FOLLOW_STATES for decision in follows):
        releasable = False
    else:
        releasable = bool(status.resolved and not pending_promotion)
    return WaitReleaseDecision(status, tuple(follows), patch, releasable, False)


def _build_follow_patch(
    marker: Mapping[str, Any],
    resolved_deps: list[Any],
    follows: list[EpicFollowDecision],
) -> tuple[WaitEpicFollowPatch | None, bool]:
    """Build one patch from fresh follow decisions.

    Persists ``launching`` and ``blocked`` stages (including ``since``)
    even when other dependencies are still unresolved, and promotes a
    target the first time it reaches ``following``. ``none`` is never
    persisted; a previous ``launching``/``blocked`` entry whose new state
    is ``none`` (or ``agent``) is dropped. Pinned ``following`` entries
    the collector skipped are kept unchanged.
    """
    prev_beads = _raw_list(marker, "wait_for_beads")
    prev_follows = _raw_list(marker, "wait_epic_follows")
    new_beads = list(prev_beads)
    new_deps = list(resolved_deps)
    new_follows: list[dict[str, Any]] = []
    replaced: set[str] = set()
    pending_promotion = False
    for decision in follows:
        target = decision.target
        state = decision.state
        replaced.add(target)
        if state not in _PERSISTED_FOLLOW_STATES:
            continue
        if state == "following" and not _is_pinned_following(prev_follows, target):
            pending_promotion = True
        added_bead_ids: list[str] = []
        for epic_id in decision.epic_ids:
            if epic_id and epic_id not in new_beads:
                new_beads.append(epic_id)
                added_bead_ids.append(epic_id)
        if state == "following" and target not in new_deps:
            new_deps.append(target)
        new_follows.append(
            {
                "target": target,
                "state": state,
                "epic_ids": list(decision.epic_ids),
                "added_bead_ids": added_bead_ids,
                "members": list(decision.members),
                "since": decision.since,
                "reason": decision.reason,
                "detail": decision.detail,
                "resume_command": decision.resume_command,
                "skipped_epic_ids": list(decision.skipped_epic_ids),
            }
        )
    for entry in prev_follows:
        if not isinstance(entry, dict):
            continue
        prev_target = entry.get("target")
        if not isinstance(prev_target, str) or prev_target in replaced:
            continue
        new_follows.append(dict(entry))
    if (
        new_beads == prev_beads
        and new_deps == list(resolved_deps)
        and new_follows == prev_follows
    ):
        return None, False
    expected = {key: _raw_list(marker, key) for key in _PREIMAGE_FIELDS}
    return (
        WaitEpicFollowPatch(
            wait_for_beads=tuple(new_beads),
            resolved_deps=tuple(new_deps),
            wait_epic_follows=tuple(new_follows),
            expected=expected,
        ),
        pending_promotion,
    )


def _preimage_matches(current: dict[str, Any], expected: dict[str, Any]) -> bool:
    for key in _PREIMAGE_FIELDS:
        current_value = current.get(key)
        expected_value = expected.get(key)
        current_list = list(current_value) if isinstance(current_value, list) else []
        expected_list = list(expected_value) if isinstance(expected_value, list) else []
        if current_list != expected_list:
            return False
    return True


def _updated_patch_targets(patch: WaitEpicFollowPatch) -> list[str]:
    previous = {
        entry.get("target"): entry
        for entry in patch.expected.get("wait_epic_follows", [])
        if isinstance(entry, dict)
    }
    updated: list[str] = []
    for entry in patch.wait_epic_follows:
        target = entry.get("target")
        if not isinstance(target, str) or target in updated:
            continue
        if previous.get(target) != entry:
            updated.append(target)
    return updated


def apply_wait_epic_follow_patch(
    waiter_dir: str | Path, patch: WaitEpicFollowPatch
) -> bool:
    """Apply a follow patch under the directive locks with compare-and-set.

    Returns False (writing nothing) when ``waiting.json`` is missing, the
    five preimage fields differ from the decision preimage, or a
    promoted/updated target left ``waiting_for``/``wait_for_epics_of``.
    """
    waiter_path = Path(waiter_dir)
    waiting_path = waiter_path / "waiting.json"
    with agent_directive_lock(waiter_path):
        with runner_slot_marker_lock():
            current = read_json_dict(waiting_path)
            if current is None:
                return False
            if not _preimage_matches(current, patch.expected):
                return False
            current_waiting_for = _str_list(current, "waiting_for")
            current_armed = _str_list(current, "wait_for_epics_of")
            for target in _updated_patch_targets(patch):
                if target not in current_waiting_for or target not in current_armed:
                    return False
            current["wait_for_beads"] = list(patch.wait_for_beads)
            current["resolved_deps"] = list(patch.resolved_deps)
            current["wait_epic_follows"] = [
                dict(entry) for entry in patch.wait_epic_follows
            ]
            fd, tmp_name = tempfile.mkstemp(
                prefix=".waiting.json.",
                suffix=".tmp",
                dir=waiter_path,
            )
            tmp_path = Path(tmp_name)
            replaced = False
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(current, stream, indent=2)
                os.replace(tmp_path, waiting_path)
                replaced = True
            finally:
                if not replaced:
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
    update_agent_meta_locked(
        waiter_path,
        lambda meta: meta.update(
            {
                "wait_for_beads": list(patch.wait_for_beads),
                "resolved_deps": list(patch.resolved_deps),
                "wait_epic_follows": [dict(entry) for entry in patch.wait_epic_follows],
            }
        ),
    )
    update_agent_artifact_index_for_marker_mutation(waiter_path)
    return True


def set_waiting_until(waiter_dir: str | Path, wait_until: str | None) -> None:
    """Set only ``wait_until`` on ``waiting.json`` under the directive locks.

    Re-reads the marker so follows, derived beads, and pins written while
    the runner was parked are preserved. Missing markers are a no-op.
    """
    waiter_path = Path(waiter_dir)
    waiting_path = waiter_path / "waiting.json"
    with agent_directive_lock(waiter_path):
        with runner_slot_marker_lock():
            current = read_json_dict(waiting_path)
            if current is None:
                return
            if wait_until is None:
                current.pop("wait_until", None)
            else:
                current["wait_until"] = wait_until
            fd, tmp_name = tempfile.mkstemp(
                prefix=".waiting.json.",
                suffix=".tmp",
                dir=waiter_path,
            )
            tmp_path = Path(tmp_name)
            replaced = False
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(current, stream, indent=2)
                os.replace(tmp_path, waiting_path)
                replaced = True
            finally:
                if not replaced:
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
    update_agent_artifact_index_for_marker_mutation(waiter_path)


__all__ = [
    "WaitEpicFollowPatch",
    "WaitReleaseDecision",
    "apply_wait_epic_follow_patch",
    "armed_wait_epic_targets",
    "resolve_wait_release",
    "set_waiting_until",
]
