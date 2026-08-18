#!/usr/bin/env python3
"""Raise and reconcile one PluginsRequired gate per project.

A five-minute checks-lane chop. For each enabled project, compare
``plugins.required`` against installed distributions and raise at most one
gate per project per distinct missing set. Lane state holds the pending
request, a generation counter, and a fingerprint over that missing set.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopLogger, ChopResultBuilder
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.notification_gates.durability import (
    canonical_json_bytes,
    file_lock,
    sha256_bytes,
)
from sase.notification_gates.executor import cancel_gate
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import (
    CANCELLATION_FILENAME,
    REQUEST_FILENAME,
    RESPONSE_FILENAME,
    bundle_paths,
    interaction_requests_dir,
)
from sase.plugins.inventory import collect_plugin_inventory
from sase.plugins.required import (
    load_project_required_plugins_config,
    resolve_required_plugins,
)
from sase.plugins.required_gate import (
    PLUGINS_REQUIRED_KIND,
    create_plugins_required_gate,
    plugins_required_missing_payload,
)
from sase.scripts._bead_gate_projects import (
    project_display_name as _project_display_name,
)
from sase.scripts._bead_task_triage_gates import gate_state as _gate_state_impl

_STATE_FILENAME = "plugins_required.json"
_LOCK_FILENAME = "plugins_required.lock"
_STATE_SCHEMA_VERSION = 1
_CHOP = "plugins_required"


@dataclass
class _ProjectState:
    request_id: str | None = None
    generation: int = 0
    fingerprint: str | None = None


@dataclass
class _LaneState:
    projects: dict[str, _ProjectState] = field(default_factory=dict)


@dataclass(frozen=True)
class _ProjectInventory:
    checkouts: tuple[tuple[str, Path], ...]
    skipped_projects: frozenset[str] = frozenset()
    sweep_allowed: bool = True


@dataclass(frozen=True)
class _PendingGate:
    request_id: str
    project: str
    producer_chop: str | None


def _enabled_project_checkouts(log: ChopLogger) -> _ProjectInventory:
    """Return primary checkouts for every enabled, non-home, non-system project."""
    from sase.running_field import get_workspace_directory

    records = list(
        list_project_records(
            sase_projects_dir(),
            "all",
            include_home=False,
            projects_only=True,
        )
    )
    checkouts: list[tuple[str, Path]] = []
    skipped_projects: set[str] = set()
    for record in records:
        if (
            not record.is_project
            or record.state != "enabled"
            or record.system_managed
            or record.project_name == "home"
        ):
            continue
        try:
            checkout = Path(
                get_workspace_directory(record.project_name, 1)
            ).expanduser()
        except Exception as exc:  # noqa: BLE001 - continue with healthy projects.
            skipped_projects.add(record.project_name)
            log.warning(
                f"[{_CHOP}] Failed to locate checkout for "
                f"{_project_display_name(record.project_name)}: {exc}"
            )
            continue
        if not checkout.is_dir():
            skipped_projects.add(record.project_name)
            log.warning(
                f"[{_CHOP}] Checkout is missing for "
                f"{_project_display_name(record.project_name)}: {checkout}"
            )
            continue
        checkouts.append((record.project_name, checkout))
    return _ProjectInventory(
        checkouts=tuple(checkouts),
        skipped_projects=frozenset(skipped_projects),
        sweep_allowed=bool(records),
    )


def _read_state(path: Path) -> _LaneState:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _LaneState()
    if not isinstance(payload, dict):
        return _LaneState()
    raw_projects = payload.get("projects")
    if not isinstance(raw_projects, dict):
        return _LaneState()
    projects: dict[str, _ProjectState] = {}
    for project_name, raw_state in raw_projects.items():
        if not isinstance(project_name, str) or not isinstance(raw_state, dict):
            continue
        request_id = raw_state.get("request_id")
        generation = raw_state.get("generation")
        fingerprint = raw_state.get("fingerprint")
        projects[project_name] = _ProjectState(
            request_id=(
                request_id if isinstance(request_id, str) and request_id else None
            ),
            generation=(
                generation
                if isinstance(generation, int)
                and not isinstance(generation, bool)
                and generation >= 1
                else 0
            ),
            fingerprint=(
                fingerprint if isinstance(fingerprint, str) and fingerprint else None
            ),
        )
    return _LaneState(projects=projects)


def _write_state(path: Path, state: _LaneState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    projects: dict[str, Any] = {}
    for project_name, project_state in sorted(state.projects.items()):
        if not project_state.request_id or not project_state.fingerprint:
            continue
        projects[project_name] = {
            "request_id": project_state.request_id,
            "generation": project_state.generation,
            "fingerprint": project_state.fingerprint,
        }
    payload = {"schema_version": _STATE_SCHEMA_VERSION, "projects": projects}
    fd, temporary_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


def _clear_state(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _missing_fingerprint(missing: list[dict[str, str]]) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "missing": [
                    {"kind": item["kind"], "requirement": item["requirement"]}
                    for item in missing
                ]
            }
        )
    )


def _request_id(project_name: str, fingerprint: str, generation: int) -> str:
    return f"plugins-required-{project_name}-{fingerprint[:12]}-g{generation}"


def _gate_state(request_id: str) -> str:
    return _gate_state_impl(PLUGINS_REQUIRED_KIND, request_id)


def _cancel_pending_gate(request_id: str, *, reason: str) -> bool:
    paths = bundle_paths(PLUGINS_REQUIRED_KIND, request_id)
    try:
        cancel_gate(paths.root, reason=reason, source=_CHOP)
    except GateError as exc:
        if exc.code == "already_answered":
            return False
        raise
    return True


def _summary(
    runtime: BuiltinChopRuntime,
    *,
    gated: int = 0,
    canceled: int = 0,
    skipped: int = 0,
    missing: int = 0,
    projects: int = 0,
    swept_projects: int = 0,
    untracked_canceled: int = 0,
    reason: str | None = None,
) -> ChopResultBuilder:
    return runtime.emit_summary(
        {
            "gated": gated,
            "canceled": canceled,
            "skipped": skipped,
            "missing": missing,
            "projects": projects,
            "swept_projects": swept_projects,
            "untracked_canceled": untracked_canceled,
        },
        reason=reason,
    )


def _persist(state_path: Path, state: _LaneState, log: ChopLogger) -> None:
    try:
        if any(
            project.request_id and project.fingerprint
            for project in state.projects.values()
        ):
            _write_state(state_path, state)
        else:
            _clear_state(state_path)
    except Exception as exc:  # noqa: BLE001 - retry on the next tick.
        log.warning(f"[{_CHOP}] Failed to persist reconciliation state: {exc}")


def _inspect_gate(request_id: str, log: ChopLogger) -> str | None:
    try:
        return _gate_state(request_id)
    except Exception as exc:  # noqa: BLE001 - retry on the next tick.
        log.warning(f"[{_CHOP}] Failed to inspect gate {request_id}: {exc}")
        return None


def _cancel_if_pending(
    request_id: str,
    *,
    reason: str,
    log: ChopLogger,
) -> int | None:
    gate = _inspect_gate(request_id, log)
    if gate is None:
        return None
    if gate != "pending":
        return 0
    try:
        return int(_cancel_pending_gate(request_id, reason=reason))
    except Exception as exc:  # noqa: BLE001 - retry on the next tick.
        log.warning(f"[{_CHOP}] Failed to cancel gate {request_id}: {exc}")
        return None


def _create_gate(
    *,
    request_id: str,
    project: str,
    missing: list[dict[str, str]],
    log: ChopLogger,
) -> bool:
    try:
        create_plugins_required_gate(
            request_id=request_id,
            project=project,
            missing=missing,
            producer={"chop": _CHOP},
        )
    except Exception as exc:  # noqa: BLE001 - retry deterministically.
        log.warning(
            f"[{_CHOP}] Failed to create gate for "
            f"{_project_display_name(project)}: {exc}"
        )
        return False
    return True


def _collect_missing(
    checkout: Path,
    *,
    inventory: Any,
) -> tuple[list[dict[str, str]] | None, str | None]:
    config, _path, error = load_project_required_plugins_config(checkout)
    if error is not None:
        return None, error
    if config is None:
        return [], None
    report = resolve_required_plugins(config, inventory=inventory)
    return plugins_required_missing_payload(report.installable), None


def _find_pending_produced_gates() -> list[_PendingGate]:
    from sase.notification_gates.durability import read_json_object

    kind_dir = interaction_requests_dir() / PLUGINS_REQUIRED_KIND
    try:
        bundles = sorted(kind_dir.iterdir(), key=lambda path: path.name)
    except (FileNotFoundError, OSError):
        return []
    gates: list[_PendingGate] = []
    for bundle in bundles:
        if not bundle.is_dir():
            continue
        if (bundle / RESPONSE_FILENAME).exists() or (
            bundle / CANCELLATION_FILENAME
        ).exists():
            continue
        try:
            envelope = read_json_object(bundle / REQUEST_FILENAME)
        except GateError:
            continue
        gate = _pending_gate_from_envelope(envelope)
        if gate is not None:
            gates.append(gate)
    return gates


def _pending_gate_from_envelope(envelope: Mapping[str, object]) -> _PendingGate | None:
    if envelope.get("kind") != PLUGINS_REQUIRED_KIND:
        return None
    request_id = envelope.get("request_id")
    payload = envelope.get("payload")
    if not isinstance(request_id, str) or not request_id:
        return None
    if not isinstance(payload, Mapping):
        return None
    project = payload.get("project")
    if not isinstance(project, str) or not project:
        return None
    producer = envelope.get("producer")
    producer_chop = None
    if isinstance(producer, Mapping):
        chop = producer.get("chop")
        if isinstance(chop, str) and chop:
            producer_chop = chop
    return _PendingGate(
        request_id=request_id,
        project=project,
        producer_chop=producer_chop,
    )


def _sweep_inactive_projects(
    state: _LaneState,
    *,
    reconciled_projects: set[str],
    skipped_projects: set[str],
    log: ChopLogger,
) -> tuple[int, int]:
    canceled = 0
    swept_projects = 0
    inactive = set(state.projects) - reconciled_projects - skipped_projects
    for project_name in sorted(inactive):
        project_state = state.projects[project_name]
        if project_state.request_id:
            result = _cancel_if_pending(
                project_state.request_id,
                reason="project_no_longer_enabled",
                log=log,
            )
            if result is None:
                continue
            canceled += result
        del state.projects[project_name]
        swept_projects += 1
    return canceled, swept_projects


def _sweep_untracked_produced_gates(
    state: _LaneState,
    *,
    skipped_projects: set[str],
    log: ChopLogger,
) -> int:
    expected = {
        project_state.request_id
        for project_state in state.projects.values()
        if project_state.request_id
    }
    try:
        pending = _find_pending_produced_gates()
    except Exception as exc:  # noqa: BLE001 - retry on the next tick.
        log.warning(f"[{_CHOP}] Failed to scan pending required-plugin gates: {exc}")
        return 0
    canceled = 0
    for gate in pending:
        if gate.producer_chop != _CHOP:
            continue
        if gate.request_id in expected:
            continue
        if gate.project in skipped_projects:
            continue
        result = _cancel_if_pending(
            gate.request_id,
            reason="gate_no_longer_tracked",
            log=log,
        )
        if result is None:
            continue
        canceled += result
    return canceled


def _reconcile_project(
    project_name: str,
    missing: list[dict[str, str]],
    *,
    state: _LaneState,
    log: ChopLogger,
) -> tuple[int, int, int, bool]:
    """Return (gated, canceled, skipped, changed)."""
    project_state = state.projects.get(project_name)
    pending_id = project_state.request_id if project_state is not None else None
    if not missing:
        if project_state is None:
            return 0, 0, 0, False
        if pending_id is None:
            del state.projects[project_name]
            return 0, 0, 0, True
        result = _cancel_if_pending(
            pending_id,
            reason="required_plugins_satisfied",
            log=log,
        )
        if result is None:
            return 0, 0, 0, False
        del state.projects[project_name]
        return 0, result, 0, True

    if project_state is None:
        project_state = _ProjectState()
        state.projects[project_name] = project_state

    fingerprint = _missing_fingerprint(missing)
    if pending_id is not None and project_state.fingerprint == fingerprint:
        gate = _inspect_gate(pending_id, log)
        if gate is None:
            return 0, 0, 0, False
        if gate == "pending":
            return 0, 0, 1, False
        if gate == "terminal":
            return 0, 0, 1, False

    canceled = 0
    if pending_id is not None:
        result = _cancel_if_pending(
            pending_id,
            reason="required_set_changed",
            log=log,
        )
        if result is None:
            return 0, 0, 0, False
        canceled = result

    generation = project_state.generation + 1
    request_id = _request_id(project_name, fingerprint, generation)
    if not _create_gate(
        request_id=request_id,
        project=project_name,
        missing=missing,
        log=log,
    ):
        return 0, canceled, 0, canceled > 0
    project_state.request_id = request_id
    project_state.generation = generation
    project_state.fingerprint = fingerprint
    return 1, canceled, 0, True


def _reconcile(runtime: BuiltinChopRuntime, state_path: Path) -> ChopResultBuilder:
    if runtime.context.dry_run:
        return _summary(runtime, reason="dry_run")

    try:
        inventory = _enabled_project_checkouts(runtime.log)
    except Exception as exc:  # noqa: BLE001 - a bad inventory must fail closed.
        runtime.log.warning(f"[{_CHOP}] Failed to load enabled projects: {exc}")
        return _summary(runtime, reason="project_inventory_unavailable")

    try:
        plugin_inventory = collect_plugin_inventory(load_resource_entry_points=False)
    except Exception as exc:  # noqa: BLE001 - fail closed rather than mis-gate.
        runtime.log.warning(f"[{_CHOP}] Failed to collect plugin inventory: {exc}")
        return _summary(runtime, reason="plugin_inventory_unavailable")

    state = _read_state(state_path)
    gated = 0
    canceled = 0
    skipped = 0
    missing_total = 0
    projects = 0
    state_changed = False
    reconciled_projects: set[str] = set()
    skipped_projects = set(inventory.skipped_projects)

    for project_name, checkout in inventory.checkouts:
        try:
            missing, load_error = _collect_missing(checkout, inventory=plugin_inventory)
        except Exception as exc:  # noqa: BLE001 - one project must not stop the chop.
            skipped_projects.add(project_name)
            runtime.log.warning(
                f"[{_CHOP}] Failed to resolve required plugins for "
                f"{_project_display_name(project_name)}: {exc}"
            )
            continue
        if load_error is not None:
            skipped_projects.add(project_name)
            runtime.log.warning(
                f"[{_CHOP}] Failed to read project config for "
                f"{_project_display_name(project_name)}: {load_error}"
            )
            continue
        assert missing is not None
        projects += 1
        reconciled_projects.add(project_name)
        missing_total += len(missing)
        project_gated, project_canceled, project_skipped, changed = _reconcile_project(
            project_name,
            missing,
            state=state,
            log=runtime.log,
        )
        gated += project_gated
        canceled += project_canceled
        skipped += project_skipped
        state_changed = state_changed or changed

    swept_projects = 0
    untracked_canceled = 0
    if inventory.sweep_allowed:
        inactive_canceled, swept_projects = _sweep_inactive_projects(
            state,
            reconciled_projects=reconciled_projects,
            skipped_projects=skipped_projects,
            log=runtime.log,
        )
        canceled += inactive_canceled
        state_changed = state_changed or bool(inactive_canceled or swept_projects)
        untracked_canceled = _sweep_untracked_produced_gates(
            state,
            skipped_projects=skipped_projects,
            log=runtime.log,
        )
        canceled += untracked_canceled
        state_changed = state_changed or bool(untracked_canceled)

    if state_changed:
        _persist(state_path, state, runtime.log)

    reason = (
        None
        if (gated or canceled or missing_total or swept_projects or untracked_canceled)
        else "no_required_plugin_changes"
    )
    return _summary(
        runtime,
        gated=gated,
        canceled=canceled,
        skipped=skipped,
        missing=missing_total,
        projects=projects,
        swept_projects=swept_projects,
        untracked_canceled=untracked_canceled,
        reason=reason,
    )


@builtin_chop("plugins_required")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    state_dir = Path(runtime.context.state_dir)
    state_path = state_dir / _STATE_FILENAME
    with file_lock(state_dir / _LOCK_FILENAME):
        return _reconcile(runtime, state_path)


def main() -> None:
    run_builtin_chop("plugins_required")


if __name__ == "__main__":
    main()
