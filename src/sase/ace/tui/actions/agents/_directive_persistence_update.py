"""Orchestrated marker writes for worker-safe directive persistence."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from pathlib import Path

from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.agent_tribe import canonicalize_agent_tribe_metadata

from ._directive_persistence_io import (
    agent_directive_lock,
    read_json_object,
    write_json_file,
)
from ._directive_persistence_models import (
    AgentDirectivePersistenceResult,
    AgentDirectivePersistenceSpec,
    AgentMetaPatch,
    AgentTribeStorePatch,
    ReadyMarkerPatch,
    WaitingMarkerPatch,
)
from ._directive_persistence_prompts import persist_prompt_artifacts


def persist_agent_directive_update(
    spec: AgentDirectivePersistenceSpec,
) -> AgentDirectivePersistenceResult:
    """Persist one agent directive update from a worker thread."""
    artifacts_path = (
        Path(spec.artifacts_dir).expanduser()
        if spec.artifacts_dir is not None
        else None
    )
    artifact_backed_update = (
        spec.prompt_mutator is not None
        or spec.meta_patch is not None
        or spec.waiting_marker is not None
        or spec.ready_marker is not None
    )
    lock = (
        agent_directive_lock(artifacts_path)
        if artifact_backed_update and artifacts_path is not None
        else nullcontext()
    )
    with lock:
        result = AgentDirectivePersistenceResult()
        extra_turn_records = (
            _bind_new_turn_wait_records(artifacts_path, spec)
            if artifacts_path is not None
            else []
        )
        selected_turn_names = _turn_target_agents_from_spec(spec)
        if spec.prompt_mutator is not None:
            if artifacts_path is None:
                raise ValueError("artifacts_dir is required for prompt rewrites")
            result = persist_prompt_artifacts(artifacts_path, spec.prompt_mutator)
        if spec.meta_patch is not None:
            if artifacts_path is None:
                raise ValueError("artifacts_dir is required for agent_meta updates")
            meta_updated = _patch_agent_meta(
                artifacts_path,
                spec.meta_patch,
                extra_turn_records=extra_turn_records,
                selected_turn_names=selected_turn_names,
            )
            result = replace(result, meta_updated=meta_updated)
        if spec.tribe_patch is not None:
            tribe_updated = _patch_agent_tribe_store(spec.tribe_patch)
            result = replace(result, tribe_updated=tribe_updated)
        if spec.waiting_marker is not None:
            if artifacts_path is None:
                raise ValueError("artifacts_dir is required for waiting marker updates")
            _write_waiting_marker(
                artifacts_path,
                spec.waiting_marker,
                extra_turn_records=extra_turn_records,
                selected_turn_names=selected_turn_names,
            )
            result = replace(result, waiting_updated=True)
        if spec.ready_marker is not None:
            if artifacts_path is None:
                raise ValueError("artifacts_dir is required for ready marker updates")
            _write_ready_marker(artifacts_path, spec.ready_marker)
            result = replace(result, ready_updated=True)
        return result


def _prune_follow_entries(
    marker: dict[str, object],
    armed: set[str] | None,
) -> None:
    """Drop follow stages (and only those) for no-longer-armed targets.

    The pin stays: promoted epic beads remain in ``wait_for_beads`` and
    release through ordinary bead machinery. Turning follow back on lets
    the next evaluation re-promote.
    """
    if armed is None:
        return
    raw = marker.get("wait_epic_follows")
    if not isinstance(raw, list):
        return
    pruned = [
        entry
        for entry in raw
        if isinstance(entry, dict)
        and isinstance(entry.get("target"), str)
        and entry["target"] in armed
    ]
    if len(pruned) == len(raw):
        return
    if pruned:
        marker["wait_epic_follows"] = pruned
    else:
        marker.pop("wait_epic_follows", None)


def _prune_wait_identity_records(
    marker: dict[str, object],
    wait_names: list[str],
) -> None:
    """Keep bound wait identity records that still match remaining wait names.

    Turn pins store ``name`` as the captured member (``16h--gate``) while
    ``requested`` is the authored wait name (``16h``). Match ``requested``
    first, then ``name``, so a still-selected turn wait keeps its record.
    """
    records = marker.get("wait_for_artifacts")
    if not isinstance(records, list):
        return
    names = set(wait_names)
    pruned = [
        record
        for record in records
        if isinstance(record, dict)
        and (
            (isinstance(record.get("requested"), str) and record["requested"] in names)
            or (isinstance(record.get("name"), str) and record["name"] in names)
        )
    ]
    if pruned:
        marker["wait_for_artifacts"] = pruned
    else:
        marker.pop("wait_for_artifacts", None)


def _drop_unselected_turn_records(
    marker: dict[str, object],
    turn_names: tuple[str, ...],
) -> None:
    """Drop turn identity records no longer authored as turn waits."""
    records = marker.get("wait_for_artifacts")
    if not isinstance(records, list):
        return
    names = set(turn_names)
    pruned = [
        record
        for record in records
        if not (
            isinstance(record, dict)
            and record.get("target") == "turn"
            and not (
                (
                    isinstance(record.get("requested"), str)
                    and record["requested"] in names
                )
                or (isinstance(record.get("name"), str) and record["name"] in names)
            )
        )
    ]
    if len(pruned) == len(records):
        return
    if pruned:
        marker["wait_for_artifacts"] = pruned
    else:
        marker.pop("wait_for_artifacts", None)


def _merge_wait_identity_records(
    marker: dict[str, object],
    extra_records: list[dict[str, object]],
) -> None:
    """Append newly bound turn records that prune did not already keep."""
    if not extra_records:
        return
    records = marker.get("wait_for_artifacts")
    if not isinstance(records, list):
        records = []
    existing: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        requested = record.get("requested")
        name = record.get("name")
        if isinstance(requested, str) and requested:
            existing.add(requested)
        if isinstance(name, str) and name:
            existing.add(name)
    for record in extra_records:
        requested = record.get("requested")
        name = record.get("name")
        keys = {key for key in (requested, name) if isinstance(key, str) and key}
        if keys & existing:
            continue
        records.append(record)
        existing.update(keys)
    if records:
        marker["wait_for_artifacts"] = records


def _turn_record_names(marker: dict[str, object]) -> set[str]:
    records = marker.get("wait_for_artifacts")
    if not isinstance(records, list):
        return set()
    names: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or record.get("target") != "turn":
            continue
        for key in ("requested", "name"):
            value = record.get(key)
            if isinstance(value, str) and value:
                names.add(value)
    return names


def _turn_target_agents_from_spec(
    spec: AgentDirectivePersistenceSpec,
) -> tuple[str, ...] | None:
    if (
        spec.waiting_marker is not None
        and spec.waiting_marker.turn_target_agents is not None
    ):
        return spec.waiting_marker.turn_target_agents
    if spec.turn_target_agents is not None:
        from ._directive_persistence_wait import durable_wait_names

        return durable_wait_names(spec.turn_target_agents)
    return None


def _bind_new_turn_wait_records(
    artifacts_path: Path,
    spec: AgentDirectivePersistenceSpec,
) -> list[dict[str, object]]:
    """Bind newly authored turn waits once; skip names that already have records."""
    turn_names = _turn_target_agents_from_spec(spec)
    if not turn_names:
        return []
    existing = _turn_record_names(read_json_object(artifacts_path / "agent_meta.json"))
    existing.update(
        _turn_record_names(read_json_object(artifacts_path / "waiting.json"))
    )
    missing = [name for name in turn_names if name not in existing]
    if not missing:
        return []
    from sase.agent.wait_target_binding import bind_wait_target

    records: list[dict[str, object]] = []
    for name in missing:
        binding = bind_wait_target(
            name,
            requested_target="turn",
            waiter_artifact_dir=artifacts_path,
        )
        if binding.identity_record is None:
            raise RuntimeError(f"Cannot bind turn wait {name!r}")
        records.append(dict(binding.identity_record))
    return records


def _patch_agent_meta(
    artifacts_path: Path,
    patch: AgentMetaPatch,
    extra_turn_records: list[dict[str, object]] | None = None,
    selected_turn_names: tuple[str, ...] | None = None,
) -> bool:
    meta_path = artifacts_path / "agent_meta.json"
    meta = read_json_object(meta_path)
    original = dict(meta)
    canonicalize_agent_tribe_metadata(meta)
    for key in patch.remove_keys:
        meta.pop(key, None)
    meta.update(dict(patch.set_values))
    from sase.autonomy.record import RETUNE_TRIGGER_KEYS, retune_meta_record

    if any(
        key in RETUNE_TRIGGER_KEYS
        for key in tuple(patch.remove_keys) + tuple(patch.set_values)
    ):
        # The ``A`` toggle mutates ``%auto`` state through legacy keys.
        # Retune the stored autonomy record from the result so record
        # readers track the toggle; the legacy keys leave disk again.
        retune_meta_record(meta)
    if "wait_for_epics_of" in patch.set_values:
        raw_armed = patch.set_values["wait_for_epics_of"]
        armed = (
            {str(n) for n in raw_armed if isinstance(n, str)}
            if isinstance(raw_armed, (list, tuple))
            else set()
        )
        _prune_follow_entries(meta, armed)
    elif "wait_for_epics_of" in patch.remove_keys:
        _prune_follow_entries(meta, set())
    remaining_wait_names: list[str] | None = None
    if "wait_for" in patch.set_values:
        raw_names = patch.set_values["wait_for"]
        remaining_wait_names = (
            [str(n) for n in raw_names if isinstance(n, str)]
            if isinstance(raw_names, (list, tuple))
            else []
        )
    elif "wait_for" in patch.remove_keys:
        remaining_wait_names = []
    if remaining_wait_names is not None:
        _prune_wait_identity_records(meta, remaining_wait_names)
    if selected_turn_names is not None:
        _drop_unselected_turn_records(meta, selected_turn_names)
    _merge_wait_identity_records(meta, extra_turn_records or [])
    if meta == original:
        return False
    write_json_file(meta_path, meta)
    update_agent_artifact_index_for_marker_mutation(str(artifacts_path))
    from sase.core.agent_tribe_evidence import invalidate_agent_tribe_evidence_cache

    invalidate_agent_tribe_evidence_cache()
    return True


def _patch_agent_tribe_store(patch: AgentTribeStorePatch) -> bool:
    from sase.ace.agent_tribes import update_agent_tribe_assignment
    from sase.config.inventory import discover_layer_inputs

    return update_agent_tribe_assignment(
        patch.identity, patch.tribe, layers=discover_layer_inputs()
    )


def _write_waiting_marker(
    artifacts_path: Path,
    patch: WaitingMarkerPatch,
    extra_turn_records: list[dict[str, object]] | None = None,
    selected_turn_names: tuple[str, ...] | None = None,
) -> None:
    # Serialize with the admission poller's check/refresh critical section so
    # a parked agent cannot overwrite a just-saved threshold with the value it
    # read immediately before the TUI edit.
    with _runner_slot_marker_lock():
        waiting_path = artifacts_path / "waiting.json"
        existing = read_json_object(waiting_path)
        for condition_key in (
            "waiting_for",
            "wait_for_epics_of",
            "wait_for_beads",
            "wait_for_hoods",
            "wait_duration",
            "wait_until",
        ):
            existing.pop(condition_key, None)
        existing["waiting_for"] = list(patch.waiting_for)
        if patch.wait_for_epics_of:
            existing["wait_for_epics_of"] = list(patch.wait_for_epics_of)
        else:
            existing.pop("wait_for_epics_of", None)
        _prune_follow_entries(existing, set(patch.wait_for_epics_of))
        _prune_wait_identity_records(existing, list(patch.waiting_for))
        if selected_turn_names is not None:
            _drop_unselected_turn_records(existing, selected_turn_names)
        _merge_wait_identity_records(existing, extra_turn_records or [])
        if patch.wait_for_beads:
            existing["wait_for_beads"] = list(patch.wait_for_beads)
        if patch.wait_for_hoods:
            existing["wait_for_hoods"] = list(patch.wait_for_hoods)
        if patch.wait_duration is not None:
            existing["wait_duration"] = patch.wait_duration
        if patch.wait_until is not None:
            existing["wait_until"] = patch.wait_until
        if patch.update_wait_runners:
            from sase.axe.run_agent_wait_markers import queue_capacity_marker_fields

            existing.pop("queue_capacity", None)
            existing.pop("queue_capacity_explicit", None)
            existing.pop("queue_capacity_multiplier", None)
            existing.pop("wait_runners", None)
            existing.pop("wait_runners_explicit", None)
            existing.update(
                queue_capacity_marker_fields(
                    patch.wait_runners,
                    explicit=patch.wait_runners is not None,
                    queue_capacity_multiplier=patch.queue_capacity_multiplier,
                )
            )
        if patch.update_wait_priority:
            existing.pop("wait_priority", None)
            existing["wait_priority_explicit"] = patch.wait_priority is not None
            if patch.wait_priority is not None:
                existing["wait_priority"] = patch.wait_priority
        if patch.update_queue_weight:
            existing.pop("queue_weight", None)
            existing["queue_weight_explicit"] = (
                patch.queue_weight is not None and patch.queue_weight_explicit
            )
            if patch.queue_weight is not None:
                existing["queue_weight"] = patch.queue_weight
        write_json_file(waiting_path, existing)
    update_agent_artifact_index_for_marker_mutation(str(artifacts_path))
    from sase.axe.run_agent_wait_markers import (
        touch_project_refresh_pulse_for_artifacts_dir,
        waiting_payload_has_dependencies,
    )

    try:
        if waiting_payload_has_dependencies(existing):
            touch_project_refresh_pulse_for_artifacts_dir(str(artifacts_path))
    except Exception:  # noqa: BLE001 - pulse must never fail the TUI edit
        pass


def _write_ready_marker(artifacts_path: Path, patch: ReadyMarkerPatch) -> None:
    ready_path = artifacts_path / "ready.json"
    if ready_path.exists():
        raise FileExistsError(str(ready_path))
    data: dict[str, object] = {"resolved_deps": list(patch.resolved_deps)}
    if patch.unwait:
        data["unwait"] = True
    write_json_file(ready_path, data)


@contextmanager
def _runner_slot_marker_lock() -> Iterator[None]:
    from sase.core.agent_directive_lock import runner_slot_marker_lock

    with runner_slot_marker_lock():
        yield


__all__ = [
    "persist_agent_directive_update",
]
