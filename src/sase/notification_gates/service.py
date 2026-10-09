"""Durable constructor and revision service for notification gates."""

from __future__ import annotations

import dataclasses
import shutil
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.core.time import get_timezone
from sase.notification_gates.durability import (
    atomic_write_json,
    canonical_json_bytes,
    file_lock,
    fsync_dir,
    materialize_resource,
    read_json_object,
    request_sha256,
    sha256_bytes,
    sha256_file,
)
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import (
    GATE_REQUEST_SCHEMA_VERSION,
    GATE_RESULT_SCHEMA_VERSION,
    GateCreationResult,
    GateError,
    GateSpec,
    validate_color,
)
from sase.notification_gates.presentation import (
    GATE_CHIP_COLOR_ACTION_DATA_KEY,
    GATE_CHIP_GLYPH_ACTION_DATA_KEY,
    GATE_CHIP_LABEL_ACTION_DATA_KEY,
    GATE_ORIGIN_AGENT_ACTION_DATA_KEY,
    GATE_PANEL_ACTION_DATA_KEY,
    GATE_PANEL_ICON_ACTION_DATA_KEY,
    GATE_TITLE_ACTION_DATA_KEY,
    GateChip,
    normalize_gate_chip,
    normalize_gate_origin_agent,
    normalize_gate_panel,
    normalize_gate_panel_icon,
    normalize_gate_snooze_until,
    normalize_gate_title,
)
from sase.notification_gates.paths import (
    bundle_paths,
    interaction_requests_dir,
    owned_resource_path,
)
from sase.notification_gates.registry import (
    GateAdapter,
    adapter_for_kind,
    validate_gate_spec,
)
from sase.notifications.models import Notification, normalize_notification_tags

CREATION_JOURNAL_SCHEMA_VERSION = 1


def create_gate(spec_value: Mapping[str, Any] | GateSpec) -> GateCreationResult:
    """Create or repair one durable gate, idempotently by request id."""
    spec = (
        spec_value
        if isinstance(spec_value, GateSpec)
        else GateSpec.from_mapping(spec_value)
    )
    adapter = adapter_for_kind(spec.kind)
    validate_gate_spec(spec, adapter)
    request_id = spec.request_id or f"{adapter.kind}-{uuid4()}"
    paths = bundle_paths(adapter.kind, request_id)
    lock_path = (
        interaction_requests_dir() / ".locks" / adapter.kind / f"{request_id}.lock"
    )
    with file_lock(lock_path):
        if paths.creation_result.is_file():
            return GateCreationResult.from_mapping(
                read_json_object(paths.creation_result)
            )
        journal = _optional_json(paths.journal)
        if journal.get("state") in {"initializing", "failed"}:
            shutil.rmtree(paths.root, ignore_errors=True)
            journal = {}

        if journal:
            return _resume_gate_creation(spec, adapter, paths, journal)
        return _start_gate_creation(spec, adapter, paths)


def _evaluate_gate_request(
    spec: GateSpec, adapter: GateAdapter
) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, Any]]:
    """Evaluate one gate creation through core ``evaluate()`` exactly once.

    Returns ``(record, decision, policy_block)`` from the record snapshot
    the spec carries (or the legacy ``enabled``/``argument`` translation
    for hand-built specs). A cross-tier argument evaluates to ``ask``
    through the record's policy, so the gate parks as manual; an unknown
    spelling stays an ``invalid_auto_argument`` error.
    """
    from sase.autonomy.gates import (
        evaluate_gate,
        policy_block_for_decision,
        record_for_auto_block,
    )

    try:
        record = record_for_auto_block(
            {
                "enabled": spec.auto.enabled,
                "argument": spec.auto.argument,
                "policy": spec.auto.policy,
            }
        )
    except ValueError as exc:
        raise GateError("invalid_auto_argument", "auto.argument", str(exc)) from exc
    decision = evaluate_gate(
        record,
        gate_kind=adapter.kind,
        option_ids=[option.id for option in spec.options],
    )
    if decision.get("profile") != "manual":
        _append_gate_decision_log(spec, adapter, record, decision)
    return record, decision, policy_block_for_decision(decision)


def _append_gate_decision_log(
    spec: GateSpec,
    adapter: GateAdapter,
    record: dict[str, Any] | None,
    decision: dict[str, Any],
) -> None:
    """Append the host decision-log row for one non-manual evaluation."""
    from sase.autonomy.gates import append_decision_log, creator_meta_for_producer

    try:
        producer = spec.producer if isinstance(spec.producer, dict) else {}
    except Exception:
        producer = {}
    append_decision_log(
        decision=decision,
        gate_kind=adapter.kind,
        gate_id=spec.request_id or "",
        creator_meta=creator_meta_for_producer(producer),
    )


def _effective_auto_state(
    spec: GateSpec, adapter: GateAdapter
) -> tuple[GateSpec, dict[str, Any], dict[str, Any], bool]:
    """Evaluate one creation and normalize the spec to its outcome.

    Returns ``(effective_spec, decision, policy_block, auto_execute)``.
    The effective spec keeps the requested auto block only when the gate
    actually auto-executes; an ``ask`` decision normalizes it to manual
    before fingerprinting, so the notification and pending row are
    published as today. The policy block rides along either way, so every
    plan, epic, and question gate carries one.
    """
    from sase.autonomy.gates import POLICY_BLOCK_KINDS

    _record, decision, block = _evaluate_gate_request(spec, adapter)
    auto_execute = bool(spec.auto.enabled) and decision.get("outcome") == "auto"
    if auto_execute:
        return spec, decision, block, True
    return (
        dataclasses.replace(
            spec,
            auto=dataclasses.replace(
                spec.auto, enabled=False, argument=None, policy=spec.auto.policy
            ),
        ),
        decision,
        block,
        False,
    )


def _start_gate_creation(
    spec: GateSpec, adapter: GateAdapter, paths: Any
) -> GateCreationResult:
    effective, decision, policy_block, auto_execute = _effective_auto_state(
        spec, adapter
    )
    notification_id = None if auto_execute else str(uuid4())
    paths.root.mkdir(parents=True, exist_ok=False)
    fsync_dir(paths.root.parent)
    _write_journal(
        paths.journal,
        state="initializing",
        request_id=paths.root.name,
        kind=adapter.kind,
        notification_id=notification_id,
    )
    published = False
    try:
        for resource in effective.resources:
            materialize_resource(paths.root, resource)
        resource_hashes = {
            resource.path: sha256_file(owned_resource_path(paths.root, resource.path))
            for resource in effective.resources
        }
        envelope = _build_envelope(
            effective,
            adapter,
            request_id=paths.root.name,
            notification_id=notification_id,
            resource_hashes=resource_hashes,
            policy_block=policy_block,
        )
        fingerprint = _spec_fingerprint(effective, adapter, resource_hashes)
        atomic_write_json(paths.request, envelope)
        _write_journal(
            paths.journal,
            state="bundle_written",
            request_id=paths.root.name,
            kind=adapter.kind,
            notification_id=notification_id,
            spec_sha256=fingerprint,
        )
        if auto_execute:
            return _resolve_auto_gate(
                effective,
                adapter,
                paths,
                envelope,
                fingerprint,
                decision,
                policy_block,
            )

        assert notification_id is not None
        _write_journal(
            paths.journal,
            state="notification_prepared",
            request_id=paths.root.name,
            kind=adapter.kind,
            notification_id=notification_id,
            spec_sha256=fingerprint,
        )
        notification = _build_notification(effective, adapter, paths, notification_id)
        from sase.notifications.store import append_notification_strict

        append_notification_strict(notification)
        published = True
        return _complete_manual_gate(
            effective,
            adapter,
            paths,
            envelope,
            fingerprint,
            notification_id,
            policy_block,
        )
    except BaseException:
        row_exists = notification_id is not None and _notification_exists(
            notification_id
        )
        if published or row_exists:
            _compensate_published_gate(notification_id, paths)
        else:
            shutil.rmtree(paths.root, ignore_errors=True)
        raise


def _resume_gate_creation(
    spec: GateSpec, adapter: GateAdapter, paths: Any, journal: dict[str, Any]
) -> GateCreationResult:
    state = journal.get("state")
    if state not in {"bundle_written", "notification_prepared"}:
        raise GateError(
            "invalid_creation_state", str(paths.journal), f"unknown gate state: {state}"
        )
    envelope = read_json_object(paths.request)
    effective, decision, policy_block, auto_execute = _effective_auto_state(
        spec, adapter
    )
    candidate_fingerprint = _spec_fingerprint(
        effective, adapter, _source_hashes(effective)
    )
    if candidate_fingerprint != journal.get("spec_sha256"):
        raise GateError(
            "request_id_conflict",
            paths.root.name,
            "request id already belongs to a different gate specification",
        )
    if auto_execute:
        return _resolve_auto_gate(
            effective,
            adapter,
            paths,
            envelope,
            candidate_fingerprint,
            decision,
            policy_block,
        )
    notification_id = journal.get("notification_id")
    if not isinstance(notification_id, str) or not notification_id:
        raise GateError(
            "invalid_creation_state",
            str(paths.journal),
            "manual gate journal has no notification id",
        )
    if _notification_exists(notification_id):
        from sase.notifications.pending_actions import register_notification

        notification = _find_notification(notification_id)
        assert notification is not None
        register_notification(notification)
    else:
        notification = _build_notification(effective, adapter, paths, notification_id)
        from sase.notifications.store import append_notification_strict

        append_notification_strict(notification)
    return _complete_manual_gate(
        effective,
        adapter,
        paths,
        envelope,
        candidate_fingerprint,
        notification_id,
        policy_block,
    )


def _resolve_auto_gate(
    spec: GateSpec,
    adapter: GateAdapter,
    paths: Any,
    envelope: dict[str, Any],
    fingerprint: str,
    decision: dict[str, Any],
    policy_block: dict[str, Any],
) -> GateCreationResult:
    selected_option_ids = tuple(decision.get("option_ids") or ())

    gate_turn = None
    if spec.shell is not None:
        from sase.gate_turn.store import find_gate_turn_by_gate_id

        gate_turn = find_gate_turn_by_gate_id(None, paths.root.name)

    execution_kwargs: dict[str, Any] = {}
    if gate_turn is not None:
        from sase.gate_turn.log import bind_gate_turn_execution_callbacks

        execution_kwargs = bind_gate_turn_execution_callbacks(
            gate_turn.artifacts_dir
        ).as_kwargs()

    execution = execute_gate_selection(
        paths.root,
        selected_option_ids,
        adapter.automatic_input(spec, decision),
        source="auto_resolution",
        **execution_kwargs,
    )
    _write_auto_policy_response(paths, adapter.kind, policy_block)

    if gate_turn is not None:
        from sase.gate_turn.settlement import settle_gate_turn

        # `creator_live=True`: creation-time auto-resolution always runs
        # inline in the creating agent's own process/turn, which already
        # owns the lane and workspace (and, via `prev_artifacts_timestamp`
        # pointing at that same creator, the agent session's runner-slot claim) --
        # never a separate answering process. No follow-up may launch and
        # no claim may be disposed of here.
        settle_gate_turn(
            gate_turn,
            gate_state="answered",
            reason="gate resolved automatically",
            creator_live=True,
        )

    result = _creation_result(
        spec,
        adapter,
        paths,
        envelope,
        notification_id=None,
        auto_state="resolved",
        auto_selected_option_ids=selected_option_ids,
        policy_block=policy_block,
    )
    atomic_write_json(paths.creation_result, result.to_dict())
    _write_journal(
        paths.journal,
        state="auto_resolved",
        request_id=paths.root.name,
        kind=adapter.kind,
        notification_id=None,
        spec_sha256=fingerprint,
        response_selected_option_ids=execution.response.get("selected_option_ids"),
    )
    return result


def _write_auto_policy_response(
    paths: Any, kind: str, policy_block: dict[str, Any]
) -> None:
    """Record the deciding policy block on an automatic gate's response.

    Every plan, epic, and question gate created by an agent carries the
    block that decided it; ``response.json`` carries it for automatic
    outcomes.
    """
    from sase.autonomy.gates import POLICY_BLOCK_KINDS

    if kind not in POLICY_BLOCK_KINDS:
        return
    try:
        response = read_json_object(paths.response)
    except GateError:
        return
    if not isinstance(response, dict):
        return
    response["policy"] = dict(policy_block)
    atomic_write_json(paths.response, response)


def _complete_manual_gate(
    spec: GateSpec,
    adapter: GateAdapter,
    paths: Any,
    envelope: dict[str, Any],
    fingerprint: str,
    notification_id: str,
    policy_block: dict[str, Any],
) -> GateCreationResult:
    result = _creation_result(
        spec,
        adapter,
        paths,
        envelope,
        notification_id=notification_id,
        auto_state="disabled",
        auto_selected_option_ids=None,
        policy_block=policy_block,
    )
    atomic_write_json(paths.creation_result, result.to_dict())
    _write_journal(
        paths.journal,
        state="complete",
        request_id=paths.root.name,
        kind=adapter.kind,
        notification_id=notification_id,
        spec_sha256=fingerprint,
    )
    return result


def _build_envelope(
    spec: GateSpec,
    adapter: GateAdapter,
    *,
    request_id: str,
    notification_id: str | None,
    resource_hashes: dict[str, str],
    policy_block: dict[str, Any],
) -> dict[str, Any]:
    from sase.autonomy.gates import POLICY_BLOCK_KINDS

    created_at = datetime.now(get_timezone())
    presentation = dict(spec.presentation)
    presentation["action"] = adapter.action
    presentation.setdefault("sender", adapter.sender)
    auto_block = spec.auto.to_dict()
    if adapter.kind in POLICY_BLOCK_KINDS:
        auto_block["policy"] = dict(policy_block)
    envelope: dict[str, Any] = {
        "schema_version": GATE_REQUEST_SCHEMA_VERSION,
        "request_id": request_id,
        "kind": adapter.kind,
        "notification_id": notification_id,
        "created_at": created_at.isoformat(),
        "created_at_unix": created_at.timestamp(),
        "producer": spec.producer,
        "continuation_mode": spec.continuation_mode,
        "gate_timeout_seconds": spec.gate_timeout_seconds,
        "payload": spec.payload,
        "presentation": presentation,
        "query": spec.query,
        "options": [option.to_dict() for option in spec.options],
        "groups": [group.to_dict() for group in spec.groups],
        "branches": [list(branch) for branch in spec.branches],
        "primary_branch": list(spec.primary_branch),
        "operations": [operation.to_dict() for operation in spec.operations],
        "resources": [resource.envelope_dict() for resource in spec.resources],
        "auto": auto_block,
        "review_revision": 1,
        "hashes": {"resources": resource_hashes},
    }
    if spec.turn is not None:
        envelope["turn"] = spec.turn.to_dict()
    envelope["hashes"]["request"] = request_sha256(envelope)
    return envelope


def _build_notification(
    spec: GateSpec,
    adapter: GateAdapter,
    paths: Any,
    notification_id: str,
) -> Notification:
    presentation = spec.presentation
    notes = _string_values(presentation.get("notes", []))
    tags = _string_values(presentation.get("tags", []))
    files = [
        str(owned_resource_path(paths.root, relative))
        for relative in _string_values(presentation.get("files", []))
    ]
    preview = _preview_relative_path(spec)
    if preview is not None:
        preview_path = str(owned_resource_path(paths.root, preview))
        if preview_path not in files:
            files.append(preview_path)
    raw_action_data = presentation.get("action_data", {})
    action_data = {str(key): str(value) for key, value in dict(raw_action_data).items()}
    action_data.update(
        {
            "request_id": paths.root.name,
            "request_kind": adapter.kind,
            "bundle_path": str(paths.root),
            "request_path": str(paths.request),
            "response_path": str(paths.response),
            adapter.legacy_directory_key: str(paths.root),
        }
    )
    panel = normalize_gate_panel(presentation.get("panel"))
    if panel is not None:
        action_data[GATE_PANEL_ACTION_DATA_KEY] = panel
    panel_icon = normalize_gate_panel_icon(presentation.get("panel_icon"))
    if panel_icon is not None:
        action_data[GATE_PANEL_ICON_ACTION_DATA_KEY] = panel_icon
    chip: GateChip | None = normalize_gate_chip(presentation.get("chip"))
    if chip is not None:
        action_data[GATE_CHIP_GLYPH_ACTION_DATA_KEY] = chip.glyph
        action_data[GATE_CHIP_LABEL_ACTION_DATA_KEY] = chip.label
        if chip.color is not None:
            action_data[GATE_CHIP_COLOR_ACTION_DATA_KEY] = chip.color
    origin_agent = normalize_gate_origin_agent(presentation.get("origin_agent"))
    if origin_agent is not None:
        action_data[GATE_ORIGIN_AGENT_ACTION_DATA_KEY] = origin_agent
    title = normalize_gate_title(presentation.get("title"))
    if title is not None:
        action_data[GATE_TITLE_ACTION_DATA_KEY] = title
    if preview is not None:
        action_data["preview_path"] = str(owned_resource_path(paths.root, preview))
    sender = str(presentation.get("sender", adapter.sender)).strip()
    # A gate that is not actionable until a future instant is born snoozed, so
    # its notification never appears unread in the window between the append
    # here and a snooze applied afterwards.
    snooze_until = normalize_gate_snooze_until(presentation.get("snooze_until"))
    return Notification(
        id=notification_id,
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender=sender,
        muted=snooze_until is not None,
        snooze_until=snooze_until,
        icon=(
            str(presentation["icon"]) if presentation.get("icon") is not None else None
        ),
        color=validate_color(presentation.get("color"), "presentation.color"),
        notes=notes,
        files=files,
        tags=normalize_notification_tags(tags),
        action=adapter.action,
        action_data=action_data,
        silent=bool(presentation.get("silent", False)),
    )


def _creation_result(
    spec: GateSpec,
    adapter: GateAdapter,
    paths: Any,
    envelope: dict[str, Any],
    *,
    notification_id: str | None,
    auto_state: str,
    auto_selected_option_ids: tuple[str, ...] | None,
    policy_block: dict[str, Any],
) -> GateCreationResult:
    from sase.autonomy.gates import POLICY_BLOCK_KINDS

    preview = _preview_relative_path(spec)
    auto_resolution: dict[str, Any] = {
        "enabled": spec.auto.enabled,
        "argument": spec.auto.argument,
        "state": auto_state,
        "selected_option_ids": (
            None if auto_selected_option_ids is None else list(auto_selected_option_ids)
        ),
    }
    if adapter.kind in POLICY_BLOCK_KINDS:
        auto_resolution["policy"] = dict(policy_block)
    return GateCreationResult(
        schema_version=GATE_RESULT_SCHEMA_VERSION,
        notification_id=notification_id,
        request_id=paths.root.name,
        kind=adapter.kind,
        bundle_path=paths.root,
        request_path=paths.request,
        response_path=paths.response,
        preview_path=(
            None if preview is None else owned_resource_path(paths.root, preview)
        ),
        continuation_mode=spec.continuation_mode,
        auto_resolution=auto_resolution,
        hashes=dict(envelope["hashes"]),
    )


def _preview_relative_path(spec: GateSpec) -> str | None:
    explicit = spec.presentation.get("preview")
    if isinstance(explicit, str):
        return explicit
    return next(
        (resource.path for resource in spec.resources if resource.role == "preview"),
        None,
    )


def _string_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value] if isinstance(value, list) else []


def _write_journal(path: Path, *, state: str, **fields: Any) -> None:
    atomic_write_json(
        path,
        {
            "schema_version": CREATION_JOURNAL_SCHEMA_VERSION,
            "state": state,
            "updated_at_unix": time.time(),
            **fields,
        },
    )


def _optional_json(path: Path) -> dict[str, Any]:
    try:
        return read_json_object(path)
    except GateError as exc:
        if exc.code == "missing_file":
            return {}
        raise


def _source_hashes(spec: GateSpec) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for resource in spec.resources:
        if resource.content is not None:
            hashes[resource.path] = sha256_bytes(resource.content.encode("utf-8"))
        else:
            assert resource.source is not None
            hashes[resource.path] = sha256_file(resource.source)
    return hashes


def _spec_fingerprint(
    spec: GateSpec, adapter: GateAdapter, resource_hashes: dict[str, str]
) -> str:
    value = {
        "kind": adapter.kind,
        "producer": spec.producer,
        "continuation_mode": spec.continuation_mode,
        "gate_timeout_seconds": spec.gate_timeout_seconds,
        "payload": spec.payload,
        "presentation": spec.presentation,
        "query": spec.query,
        "options": [option.to_dict() for option in spec.options],
        "groups": [group.to_dict() for group in spec.groups],
        "branches": [list(branch) for branch in spec.branches],
        "primary_branch": list(spec.primary_branch),
        "operations": [operation.to_dict() for operation in spec.operations],
        "resources": [resource.envelope_dict() for resource in spec.resources],
        "resource_hashes": resource_hashes,
        "auto": spec.auto.to_dict(),
        "turn": None if spec.turn is None else spec.turn.to_dict(),
    }
    return sha256_bytes(canonical_json_bytes(value))


def _notification_exists(notification_id: str) -> bool:
    return _find_notification(notification_id) is not None


def _find_notification(notification_id: str) -> Notification | None:
    from sase.notifications.store import load_notifications

    return next(
        (
            notification
            for notification in load_notifications(include_dismissed=True)
            if notification.id == notification_id
        ),
        None,
    )


def _compensate_published_gate(notification_id: str | None, paths: Any) -> None:
    if notification_id is None:
        return
    from sase.notifications.pending_actions import unregister_notification
    from sase.notifications.store import mark_dismissed

    unregister_notification(notification_id)
    mark_dismissed(notification_id)
    try:
        _write_journal(
            paths.journal,
            state="failed",
            request_id=paths.root.name,
            kind=paths.root.parent.name,
            notification_id=notification_id,
        )
    except OSError:
        pass


__all__ = ["create_gate"]
