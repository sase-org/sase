"""Gate fingerprint and persisted-state tests for the task triage chop."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import sase.scripts.sase_chop_bead_task_triage as task_triage
from sase.bead.model import (
    CloseRecord,
    ReopenCause,
    Resolution,
    TaskPlusOneEvidence,
)

from sase.scripts._bead_task_triage_gates import presentation_fingerprint
from sase.task_types._models import (
    TaskTypeProvenance,
    TaskTypeRecord,
    TaskTypeRegistry,
)

from tests._axe_chop_bead_task_triage_helpers import (
    make_runtime,
    make_snoozed_task,
    make_task,
    patch_project,
    patch_task_type_registry,
)


def _typed_registry(*, glyph: str) -> TaskTypeRegistry:
    record = TaskTypeRecord(
        task_type="flake",
        spec={
            "task_type": "flake",
            "label": "Flaky test",
            "fields": [
                {"name": "node_id", "label": "Test node ID", "required": True},
                {"name": "evidence", "label": "Evidence", "required": True},
            ],
        },
        digest="a" * 64,
        provenance=TaskTypeProvenance(
            source="builtin", name="sase", package="sase", version="1.0.0", builtin=True
        ),
        resolved_glyph=glyph,
        resolved_accent_color="#00D7D7",
    )
    return TaskTypeRegistry(records=(record,), diagnostics=())


def test_missing_presentation_fingerprint_is_canceled_and_recreated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ready = [make_task()]
    patch_project(monkeypatch, tmp_path, ready)
    old_request_id = task_triage._request_id(
        "sase", "sase-task.1", 1, task_triage.TASK_TRIAGE_KIND
    )
    state_path = tmp_path / task_triage._STATE_FILENAME
    task_triage._write_state(
        state_path,
        {
            "sase": task_triage._ProjectState(
                gates={"sase-task.1": old_request_id},
                generations={"sase-task.1": 1},
            )
        },
    )
    canceled: list[tuple[str, str]] = []
    created: list[dict[str, Any]] = []
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda kind, request_id, *, reason: (
            canceled.append((request_id, reason)) or True
        ),
    )
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs),
    )

    result = task_triage._run(make_runtime(tmp_path))

    assert result.counters == {
        "gated": 1,
        "canceled": 1,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "suppressed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert canceled == [(old_request_id, "task_triage_presentation_changed")]
    assert created[0]["request_id"].endswith("-g2")
    state = task_triage._read_state(state_path)["sase"]
    assert state.fingerprints == {
        "sase-task.1": task_triage._presentation_fingerprint(ready[0])
    }


def test_current_presentation_fingerprint_remains_pending(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = make_task()
    patch_project(monkeypatch, tmp_path, [task])
    request_id = task_triage._request_id(
        "sase", "sase-task.1", 1, task_triage.TASK_TRIAGE_KIND
    )
    task_triage._write_state(
        tmp_path / task_triage._STATE_FILENAME,
        {
            "sase": task_triage._ProjectState(
                gates={"sase-task.1": request_id},
                generations={"sase-task.1": 1},
                fingerprints={
                    "sase-task.1": task_triage._presentation_fingerprint(task),
                },
            )
        },
    )
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda *_args, **_kwargs: pytest.fail("current gate was canceled"),
    )
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **_kwargs: pytest.fail("duplicate gate was created"),
    )

    result = task_triage._run(make_runtime(tmp_path))

    assert result.reason == "no_triage_changes"
    assert result.counters == {
        "gated": 0,
        "canceled": 0,
        "skipped": 1,
        "deferred": 0,
        "resnoozed": 0,
        "suppressed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }


def test_presentation_fingerprint_covers_the_bead_creation_time() -> None:
    """A gate created before created_at was shown must regenerate exactly once."""

    without_created_at = make_task()
    without_created_at.created_at = ""

    assert task_triage._presentation_fingerprint(
        without_created_at
    ) != task_triage._presentation_fingerprint(make_task())


def test_presentation_fingerprint_covers_the_snooze_record() -> None:
    """A re-snooze must replace a gate still advertising the old wake time."""
    original = make_snoozed_task(until="2026-09-01T09:00:00+00:00")
    deferred_longer = make_snoozed_task(until="2026-09-08T09:00:00+00:00")
    other_reason = make_snoozed_task(
        until="2026-09-01T09:00:00+00:00", reason="Blocked."
    )

    fingerprint = task_triage._presentation_fingerprint(original)

    assert fingerprint != task_triage._presentation_fingerprint(deferred_longer)
    assert fingerprint != task_triage._presentation_fingerprint(other_reason)
    assert fingerprint != task_triage._presentation_fingerprint(make_task())


def test_presentation_fingerprint_covers_the_format_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bumping the format version must refresh every pending gate once."""
    task = make_task()
    fingerprint = task_triage._presentation_fingerprint(task)

    monkeypatch.setattr(task_triage, "_PRESENTATION_FORMAT_VERSION", 999)

    assert task_triage._presentation_fingerprint(task) != fingerprint


def test_untyped_bead_fingerprint_omits_task_type_display() -> None:
    """The new key must not change an untyped bead's fingerprint shape."""
    untyped = make_task()
    typed = make_task(task_type="flake")
    typed.task_type_fields = {
        "node_id": "tests/x.py::test_y",
        "evidence": "3/50 under -n 8",
    }

    via_wrapper = task_triage._presentation_fingerprint(untyped)
    via_hasher = presentation_fingerprint(
        untyped,
        format_version=task_triage._PRESENTATION_FORMAT_VERSION,
        gate_contract_version=task_triage._GATE_CONTRACT_VERSION,
    )
    via_explicit_none = presentation_fingerprint(
        untyped,
        format_version=task_triage._PRESENTATION_FORMAT_VERSION,
        gate_contract_version=task_triage._GATE_CONTRACT_VERSION,
        task_type_display=None,
    )

    assert via_wrapper == via_hasher == via_explicit_none
    assert task_triage._presentation_fingerprint(typed) != via_wrapper
    assert task_triage._presentation_fingerprint(
        untyped, registry=_typed_registry(glyph="≈")
    ) == task_triage._presentation_fingerprint(
        untyped, registry=_typed_registry(glyph="!")
    )


def test_task_type_display_change_replaces_pending_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A registered glyph/name/accent change must replace the pending gate."""
    task = make_task(task_type="flake")
    task.task_type_fields = {
        "node_id": "tests/x.py::test_y",
        "evidence": "3/50 under -n 8",
    }
    patch_project(monkeypatch, tmp_path, [task])
    patch_task_type_registry(monkeypatch, _typed_registry(glyph="≈"))
    created: list[dict[str, Any]] = []
    canceled: list[tuple[str, str]] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs),
    )
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda kind, request_id, *, reason: (
            canceled.append((request_id, reason)) or True
        ),
    )

    task_triage._run(make_runtime(tmp_path))
    patch_task_type_registry(monkeypatch, _typed_registry(glyph="!"))
    refreshed = task_triage._run(make_runtime(tmp_path))

    assert refreshed.counters == {
        "gated": 1,
        "canceled": 1,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "suppressed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert canceled == [(created[0]["request_id"], "task_triage_presentation_changed")]
    assert created[1]["request_id"].endswith("-g2")


def test_untyped_pending_gate_is_stable_across_registry_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Beads with no type must not churn when the catalog's glyphs change."""
    task = make_task()
    patch_project(monkeypatch, tmp_path, [task])
    patch_task_type_registry(monkeypatch, _typed_registry(glyph="≈"))
    request_id = task_triage._request_id(
        "sase", "sase-task.1", 1, task_triage.TASK_TRIAGE_KIND
    )
    task_triage._write_state(
        tmp_path / task_triage._STATE_FILENAME,
        {
            "sase": task_triage._ProjectState(
                gates={"sase-task.1": request_id},
                generations={"sase-task.1": 1},
                fingerprints={
                    "sase-task.1": task_triage._presentation_fingerprint(task),
                },
            )
        },
    )
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda *_args, **_kwargs: pytest.fail("untyped gate was canceled"),
    )
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **_kwargs: pytest.fail("duplicate gate was created"),
    )
    patch_task_type_registry(monkeypatch, _typed_registry(glyph="!"))

    result = task_triage._run(make_runtime(tmp_path))

    assert result.reason == "no_triage_changes"
    assert result.counters["skipped"] == 1


def test_format_version_4_replaces_gates_fingerprinted_at_version_3(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Pending gates still advertising the typeless format must be replaced."""
    task = make_task()
    patch_project(monkeypatch, tmp_path, [task])
    monkeypatch.setattr(task_triage, "_PRESENTATION_FORMAT_VERSION", 3)
    old_fingerprint = task_triage._presentation_fingerprint(task)
    monkeypatch.setattr(task_triage, "_PRESENTATION_FORMAT_VERSION", 4)
    request_id = task_triage._request_id(
        "sase", "sase-task.1", 1, task_triage.TASK_TRIAGE_KIND
    )
    task_triage._write_state(
        tmp_path / task_triage._STATE_FILENAME,
        {
            "sase": task_triage._ProjectState(
                gates={"sase-task.1": request_id},
                generations={"sase-task.1": 1},
                fingerprints={"sase-task.1": old_fingerprint},
            )
        },
    )
    created: list[dict[str, Any]] = []
    canceled: list[tuple[str, str]] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs),
    )
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda kind, request_id, *, reason: (
            canceled.append((request_id, reason)) or True
        ),
    )

    result = task_triage._run(make_runtime(tmp_path))

    assert result.counters == {
        "gated": 1,
        "canceled": 1,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "suppressed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert canceled == [(request_id, "task_triage_presentation_changed")]
    assert created[0]["request_id"].endswith("-g2")


def test_presentation_fingerprint_covers_the_gate_contract_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bumping the gate contract version must refresh pending task gates once."""
    task = make_task()
    fingerprint = task_triage._presentation_fingerprint(task)

    monkeypatch.setattr(
        task_triage,
        "_GATE_CONTRACT_VERSION",
        task_triage._GATE_CONTRACT_VERSION,
    )
    assert task_triage._presentation_fingerprint(task) == fingerprint

    monkeypatch.setattr(
        task_triage,
        "_GATE_CONTRACT_VERSION",
        task_triage._GATE_CONTRACT_VERSION + 1,
    )
    assert task_triage._presentation_fingerprint(task) != fingerprint


def test_later_plus_one_refreshes_pending_triage_presentation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = make_task()
    ready = [task]
    patch_project(monkeypatch, tmp_path, ready)
    created: list[dict[str, Any]] = []
    canceled: list[tuple[str, str]] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs),
    )
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda kind, request_id, *, reason: (
            canceled.append((request_id, reason)) or True
        ),
    )

    task_triage._run(make_runtime(tmp_path))
    task.plus_one_evidence.append(
        TaskPlusOneEvidence(
            timestamp="2026-08-01T15:00:00Z",
            reporter="agent.beta",
            note="Independent reproduction.",
        )
    )
    refreshed = task_triage._run(make_runtime(tmp_path))

    assert refreshed.counters == {
        "gated": 1,
        "canceled": 1,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "suppressed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert canceled == [(created[0]["request_id"], "task_triage_presentation_changed")]
    assert created[1]["plus_one_evidence"] == task.plus_one_evidence
    assert created[1]["request_id"].endswith("-g2")


def test_later_close_history_refreshes_pending_triage_presentation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = make_task()
    ready = [task]
    patch_project(monkeypatch, tmp_path, ready)
    created: list[dict[str, Any]] = []
    canceled: list[tuple[str, str]] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs),
    )
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda kind, request_id, *, reason: (
            canceled.append((request_id, reason)) or True
        ),
    )

    task_triage._run(make_runtime(tmp_path))
    task.close_history.append(
        CloseRecord(
            closed_at="2026-07-30T09:12:04Z",
            reopened_at="2026-08-05T17:04:11Z",
            reopened_via=ReopenCause.PLUS_ONE,
            close_reason="Not reproducible on main.",
            resolution=Resolution.CANCELED,
            reopened_by="claude.probe",
        )
    )
    refreshed = task_triage._run(make_runtime(tmp_path))

    assert refreshed.counters == {
        "gated": 1,
        "canceled": 1,
        "skipped": 0,
        "deferred": 0,
        "resnoozed": 0,
        "suppressed": 0,
        "swept_projects": 0,
        "untracked_canceled": 0,
    }
    assert canceled == [(created[0]["request_id"], "task_triage_presentation_changed")]
    assert created[1]["close_history"] == task.close_history
    assert created[1]["request_id"].endswith("-g2")


@pytest.mark.parametrize("stored_fingerprint", [None, "", True, 0])
def test_missing_or_malformed_fingerprint_is_discarded(
    tmp_path: Path,
    stored_fingerprint: object,
) -> None:
    state_path = tmp_path / task_triage._STATE_FILENAME
    project: dict[str, object] = {
        "gates": {"sase-task.1": "old-request"},
        "generations": {"sase-task.1": 1},
    }
    if stored_fingerprint is not None:
        project["fingerprints"] = {"sase-task.1": stored_fingerprint}
    state_path.write_text(
        json.dumps({"schema_version": 1, "projects": {"sase": project}}),
        encoding="utf-8",
    )

    state = task_triage._read_state(state_path)["sase"]

    assert state.fingerprints == {}


def test_version_two_state_treats_every_recorded_gate_as_a_triage_gate(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / task_triage._STATE_FILENAME
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "projects": {
                    "sase": {
                        "gates": {"sase-task.1": "old-request"},
                        "generations": {"sase-task.1": 1},
                        "fingerprints": {"sase-task.1": "abc"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    state = task_triage._read_state(state_path)["sase"]

    assert state.kinds == {}
    assert state.kinds.get("sase-task.1", task_triage.TASK_TRIAGE_KIND) == (
        task_triage.TASK_TRIAGE_KIND
    )


def test_unknown_recorded_gate_kind_is_discarded(tmp_path: Path) -> None:
    state_path = tmp_path / task_triage._STATE_FILENAME
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "projects": {
                    "sase": {
                        "gates": {"sase-task.1": "old-request"},
                        "generations": {"sase-task.1": 1},
                        "kinds": {
                            "sase-task.1": "forged",
                            "sase-task.9": "bead_snooze",
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    state = task_triage._read_state(state_path)["sase"]

    assert state.kinds == {}
