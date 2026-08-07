"""Live task-bead gate reconciliation chop tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

import sase.scripts.sase_chop_bead_task_triage as task_triage
from sase.axe.chop_script_context import ChopScriptContext
from sase.bead.model import (
    CloseRecord,
    Issue,
    IssueType,
    PhaseSize,
    ReopenCause,
    Resolution,
    SnoozeRecord,
    Status,
    TaskPlusOneEvidence,
)
from sase.chops.builtin import BuiltinChopRuntime
from sase.chops.sdk import ChopLogger
from sase.core.time import get_timezone


def _runtime(tmp_path: Path, *, dry_run: bool = False) -> BuiltinChopRuntime:
    return BuiltinChopRuntime(
        name="bead_task_triage",
        context=ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="checks",
            state_dir=str(tmp_path),
            all_changespecs_file=str(tmp_path / "all.json"),
            filtered_changespecs_file=str(tmp_path / "filtered.json"),
            dry_run=dry_run,
        ),
        log=ChopLogger(stdout=StringIO(), stderr=StringIO()),
    )


def _task(
    bead_id: str = "sase-task.1",
    *,
    created_by: str = "claude_coder",
) -> Issue:
    return Issue(
        id=bead_id,
        title="Follow up on cache invalidation",
        status=Status.READY,
        issue_type=IssueType.TASK,
        description="Make cache invalidation deterministic.",
        notes="Discovered while landing sase-bg.",
        created_at="2026-01-01T00:00:00Z",
        created_by=created_by,
        size=PhaseSize.SMALL,
    )


def _patch_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    ready: list[Issue],
) -> None:
    monkeypatch.setattr(
        task_triage,
        "_enabled_project_stores",
        lambda _log: [("sase", tmp_path / "beads")],
    )
    monkeypatch.setattr(task_triage, "_gateable_tasks", lambda _path: list(ready))


def test_ready_task_is_gated_once_while_gate_remains_pending(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ready = [_task()]
    _patch_project(monkeypatch, tmp_path, ready)
    created: list[dict[str, Any]] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs),
    )
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")

    first = task_triage._run(_runtime(tmp_path))
    second = task_triage._run(_runtime(tmp_path))

    assert first.counters == {"gated": 1, "canceled": 0, "skipped": 0, "resnoozed": 0}
    assert second.counters == {"gated": 0, "canceled": 0, "skipped": 1, "resnoozed": 0}
    assert second.reason == "no_triage_changes"
    assert len(created) == 1
    assert created[0]["bead_id"] == "sase-task.1"
    assert created[0]["project"] == "sase"
    assert created[0]["title"] == "Follow up on cache invalidation"
    assert created[0]["created_by"] == "claude_coder"
    assert created[0]["created_at"] == "2026-01-01T00:00:00Z"
    assert created[0]["request_id"].endswith("-g1")

    state = json.loads(
        (tmp_path / task_triage._STATE_FILENAME).read_text(encoding="utf-8")
    )
    assert state["projects"]["sase"]["gates"] == {
        "sase-task.1": created[0]["request_id"]
    }
    assert state["projects"]["sase"]["generations"] == {"sase-task.1": 1}
    assert state["projects"]["sase"]["fingerprints"] == {
        "sase-task.1": task_triage._presentation_fingerprint(ready[0])
    }


def test_blank_task_creator_is_forwarded_without_placeholder(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_project(monkeypatch, tmp_path, [_task(created_by="")])
    created: list[dict[str, Any]] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs),
    )

    result = task_triage._run(_runtime(tmp_path))

    assert result.counters == {"gated": 1, "canceled": 0, "skipped": 0, "resnoozed": 0}
    assert created[0]["created_by"] == ""


def test_missing_presentation_fingerprint_is_canceled_and_recreated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ready = [_task()]
    _patch_project(monkeypatch, tmp_path, ready)
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

    result = task_triage._run(_runtime(tmp_path))

    assert result.counters == {"gated": 1, "canceled": 1, "skipped": 0, "resnoozed": 0}
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
    task = _task()
    _patch_project(monkeypatch, tmp_path, [task])
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

    result = task_triage._run(_runtime(tmp_path))

    assert result.reason == "no_triage_changes"
    assert result.counters == {"gated": 0, "canceled": 0, "skipped": 1, "resnoozed": 0}


def test_presentation_fingerprint_covers_the_bead_creation_time() -> None:
    """A gate created before created_at was shown must regenerate exactly once."""

    without_created_at = _task()
    without_created_at.created_at = ""

    assert task_triage._presentation_fingerprint(
        without_created_at
    ) != task_triage._presentation_fingerprint(_task())


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


def test_later_plus_one_refreshes_pending_triage_presentation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = _task()
    ready = [task]
    _patch_project(monkeypatch, tmp_path, ready)
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

    task_triage._run(_runtime(tmp_path))
    task.plus_one_evidence.append(
        TaskPlusOneEvidence(
            timestamp="2026-08-01T15:00:00Z",
            reporter="agent.beta",
            note="Independent reproduction.",
        )
    )
    refreshed = task_triage._run(_runtime(tmp_path))

    assert refreshed.counters == {
        "gated": 1,
        "canceled": 1,
        "skipped": 0,
        "resnoozed": 0,
    }
    assert canceled == [(created[0]["request_id"], "task_triage_presentation_changed")]
    assert created[1]["plus_one_evidence"] == task.plus_one_evidence
    assert created[1]["request_id"].endswith("-g2")


def test_later_close_history_refreshes_pending_triage_presentation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = _task()
    ready = [task]
    _patch_project(monkeypatch, tmp_path, ready)
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

    task_triage._run(_runtime(tmp_path))
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
    refreshed = task_triage._run(_runtime(tmp_path))

    assert refreshed.counters == {
        "gated": 1,
        "canceled": 1,
        "skipped": 0,
        "resnoozed": 0,
    }
    assert canceled == [(created[0]["request_id"], "task_triage_presentation_changed")]
    assert created[1]["close_history"] == task.close_history
    assert created[1]["request_id"].endswith("-g2")


def test_stale_gate_is_canceled_and_ready_again_uses_new_generation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ready = [_task()]
    _patch_project(monkeypatch, tmp_path, ready)
    created: list[str] = []
    canceled: list[str] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda _kind, request_id: canceled.append(request_id) or True,
    )

    task_triage._run(_runtime(tmp_path))
    ready.clear()
    stale = task_triage._run(_runtime(tmp_path))
    ready.append(_task())
    raised_again = task_triage._run(_runtime(tmp_path))

    assert stale.counters == {"gated": 0, "canceled": 1, "skipped": 0, "resnoozed": 0}
    assert canceled == [created[0]]
    assert raised_again.counters == {
        "gated": 1,
        "canceled": 0,
        "skipped": 0,
        "resnoozed": 0,
    }
    assert len(created) == 2
    assert created[0].endswith("-g1")
    assert created[1].endswith("-g2")
    assert created[0] != created[1]


def test_terminal_gate_for_still_ready_task_is_regenerated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ready = [_task()]
    _patch_project(monkeypatch, tmp_path, ready)
    created: list[str] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "terminal")

    task_triage._run(_runtime(tmp_path))
    result = task_triage._run(_runtime(tmp_path))

    assert result.counters == {"gated": 1, "canceled": 0, "skipped": 0, "resnoozed": 0}
    assert created[0].endswith("-g1")
    assert created[1].endswith("-g2")


def test_failed_project_read_does_not_block_other_projects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        task_triage,
        "_enabled_project_stores",
        lambda _log: [
            ("broken", tmp_path / "broken"),
            ("sase", tmp_path / "beads"),
        ],
    )

    def read(path: Path) -> list[Issue]:
        if path.name == "broken":
            raise OSError("unavailable")
        return [_task()]

    monkeypatch.setattr(task_triage, "_gateable_tasks", read)
    created: list[str] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )

    result = task_triage._run(_runtime(tmp_path))

    assert result.counters == {"gated": 1, "canceled": 0, "skipped": 0, "resnoozed": 0}
    assert len(created) == 1


def test_gate_inspection_failure_preserves_mapping_without_duplicate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ready = [_task()]
    _patch_project(monkeypatch, tmp_path, ready)
    created: list[str] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )

    task_triage._run(_runtime(tmp_path))
    monkeypatch.setattr(
        task_triage,
        "_gate_state",
        lambda _kind, _id: (_ for _ in ()).throw(OSError("unreadable gate")),
    )
    result = task_triage._run(_runtime(tmp_path))

    assert result.reason == "no_triage_changes"
    assert result.counters == {"gated": 0, "canceled": 0, "skipped": 0, "resnoozed": 0}
    assert len(created) == 1
    state = task_triage._read_state(tmp_path / task_triage._STATE_FILENAME)
    assert state["sase"].gates["sase-task.1"] == created[0]


def test_dry_run_does_not_read_stores_or_mutate_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        task_triage,
        "_enabled_project_stores",
        lambda _log: pytest.fail("dry run enumerated projects"),
    )

    result = task_triage._run(_runtime(tmp_path, dry_run=True))

    assert result.reason == "dry_run"
    assert result.counters == {"gated": 0, "canceled": 0, "skipped": 0, "resnoozed": 0}
    assert not (tmp_path / task_triage._STATE_FILENAME).exists()


def test_request_ids_are_deterministic_project_scoped_kind_scoped_and_bounded() -> None:
    bead_id = "sase-" + ("x" * 120)
    triage = task_triage.TASK_TRIAGE_KIND
    snooze = task_triage.BEAD_SNOOZE_KIND

    first = task_triage._request_id("gh_sase-org__sase", bead_id, 1, triage)
    repeated = task_triage._request_id("gh_sase-org__sase", bead_id, 1, triage)
    other_project = task_triage._request_id("other", bead_id, 1, triage)
    other_kind = task_triage._request_id("gh_sase-org__sase", bead_id, 1, snooze)

    assert first == repeated
    assert first != other_project
    assert first != other_kind
    assert first.endswith("-g1")
    assert len(first) <= 128
    assert len(other_kind) <= 128


def _snoozed_task(
    bead_id: str = "sase-task.1",
    *,
    until: str | None = None,
    reason: str = "Waiting on the upstream fix.",
) -> Issue:
    issue = _task(bead_id)
    issue.status = Status.SNOOZED
    issue.snooze = SnoozeRecord(
        until=until or _future_instant(days=3),
        snoozed_at="2026-08-01T00:00:00+00:00",
        snoozed_by="bryan",
        reason=reason,
    )
    return issue


def _future_instant(*, days: int) -> str:
    return (datetime.now(get_timezone()) + timedelta(days=days)).isoformat()


def _patch_snooze_gate(
    monkeypatch: pytest.MonkeyPatch, created: list[dict[str, Any]]
) -> None:
    monkeypatch.setattr(
        task_triage,
        "create_bead_snooze_gate",
        lambda **kwargs: created.append(kwargs),
    )


def test_snoozed_task_raises_a_wake_gate_carrying_its_snooze_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    snoozed = _snoozed_task()
    _patch_project(monkeypatch, tmp_path, [snoozed])
    created: list[dict[str, Any]] = []
    _patch_snooze_gate(monkeypatch, created)
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **_kwargs: pytest.fail("a snoozed task raised a triage gate"),
    )

    result = task_triage._run(_runtime(tmp_path))

    assert result.counters == {
        "gated": 1,
        "canceled": 0,
        "skipped": 0,
        "resnoozed": 0,
    }
    assert created[0]["snooze"] == snoozed.snooze
    assert created[0]["request_id"].startswith("bead-snooze-")
    state = task_triage._read_state(tmp_path / task_triage._STATE_FILENAME)["sase"]
    assert state.kinds == {"sase-task.1": task_triage.BEAD_SNOOZE_KIND}


def test_snoozing_a_ready_task_replaces_its_triage_gate_with_a_wake_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    live = [_task()]
    _patch_project(monkeypatch, tmp_path, live)
    triage_created: list[dict[str, Any]] = []
    snooze_created: list[dict[str, Any]] = []
    canceled: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: triage_created.append(kwargs),
    )
    _patch_snooze_gate(monkeypatch, snooze_created)
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda kind, request_id, *, reason: (
            canceled.append((kind, request_id, reason)) or True
        ),
    )

    task_triage._run(_runtime(tmp_path))
    live[:] = [_snoozed_task()]
    swapped = task_triage._run(_runtime(tmp_path))

    assert swapped.counters == {
        "gated": 1,
        "canceled": 1,
        "skipped": 0,
        "resnoozed": 0,
    }
    assert canceled == [
        (
            task_triage.TASK_TRIAGE_KIND,
            triage_created[0]["request_id"],
            "bead_status_changed",
        )
    ]
    assert len(snooze_created) == 1
    assert snooze_created[0]["request_id"].endswith("-g2")
    state = task_triage._read_state(tmp_path / task_triage._STATE_FILENAME)["sase"]
    assert state.kinds == {"sase-task.1": task_triage.BEAD_SNOOZE_KIND}
    assert state.gates == {"sase-task.1": snooze_created[0]["request_id"]}


def test_waking_a_snoozed_task_replaces_its_wake_gate_with_a_triage_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    live = [_snoozed_task()]
    _patch_project(monkeypatch, tmp_path, live)
    triage_created: list[dict[str, Any]] = []
    snooze_created: list[dict[str, Any]] = []
    canceled: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: triage_created.append(kwargs),
    )
    _patch_snooze_gate(monkeypatch, snooze_created)
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda kind, request_id, *, reason: (
            canceled.append((kind, request_id, reason)) or True
        ),
    )
    monkeypatch.setattr(task_triage, "_heal_snoozed_notification", lambda *_args: False)

    task_triage._run(_runtime(tmp_path))
    live[:] = [_task()]
    swapped = task_triage._run(_runtime(tmp_path))

    assert swapped.counters == {
        "gated": 1,
        "canceled": 1,
        "skipped": 0,
        "resnoozed": 0,
    }
    assert canceled == [
        (
            task_triage.BEAD_SNOOZE_KIND,
            snooze_created[0]["request_id"],
            "bead_status_changed",
        )
    ]
    state = task_triage._read_state(tmp_path / task_triage._STATE_FILENAME)["sase"]
    assert state.kinds == {"sase-task.1": task_triage.TASK_TRIAGE_KIND}


def test_no_task_bead_ever_holds_two_pending_gates_across_a_status_swap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The bead-side counterpart to the notification-side one-tab guarantee."""
    live = [_task()]
    _patch_project(monkeypatch, tmp_path, live)
    pending: dict[tuple[str, str], bool] = {}
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: pending.__setitem__(
            (task_triage.TASK_TRIAGE_KIND, kwargs["request_id"]), True
        ),
    )
    monkeypatch.setattr(
        task_triage,
        "create_bead_snooze_gate",
        lambda **kwargs: pending.__setitem__(
            (task_triage.BEAD_SNOOZE_KIND, kwargs["request_id"]), True
        ),
    )
    monkeypatch.setattr(
        task_triage,
        "_gate_state",
        lambda kind, request_id: (
            "pending" if pending.get((kind, request_id)) else ("terminal")
        ),
    )
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda kind, request_id, **_kwargs: bool(
            pending.pop((kind, request_id), False)
        ),
    )
    monkeypatch.setattr(task_triage, "_heal_snoozed_notification", lambda *_args: False)

    for status_swap in ([_snoozed_task()], [_task()], [_snoozed_task()]):
        task_triage._run(_runtime(tmp_path))
        assert sum(pending.values()) <= 1
        live[:] = status_swap
    task_triage._run(_runtime(tmp_path))

    assert sum(pending.values()) == 1


def test_presentation_fingerprint_covers_the_snooze_record() -> None:
    """A re-snooze must replace a gate still advertising the old wake time."""
    original = _snoozed_task(until="2026-09-01T09:00:00+00:00")
    deferred_longer = _snoozed_task(until="2026-09-08T09:00:00+00:00")
    other_reason = _snoozed_task(until="2026-09-01T09:00:00+00:00", reason="Blocked.")

    fingerprint = task_triage._presentation_fingerprint(original)

    assert fingerprint != task_triage._presentation_fingerprint(deferred_longer)
    assert fingerprint != task_triage._presentation_fingerprint(other_reason)
    assert fingerprint != task_triage._presentation_fingerprint(_task())


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


def _patch_notification_store(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rows: list[Any],
    snoozed: list[tuple[str, datetime]],
) -> None:
    import sase.notifications.store as notification_store

    monkeypatch.setattr(notification_store, "load_notifications", lambda: list(rows))
    monkeypatch.setattr(
        notification_store,
        "mark_snoozed",
        lambda notification_id, until: (
            bool(snoozed.append((notification_id, until))) or True
        ),
    )


def _notification_row(*, muted: bool, snooze_until: str | None) -> Any:
    from sase.notifications.models import Notification

    return Notification(
        id="notif-1",
        timestamp="2026-08-01T00:00:00+00:00",
        sender="bead",
        muted=muted,
        snooze_until=snooze_until,
    )


def _run_with_pending_snooze_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    snoozed_task: Issue,
    rows: list[Any],
    snoozed: list[tuple[str, datetime]],
) -> Any:
    """Reconcile once over an already-gated snoozed bead whose gate is current."""
    _patch_project(monkeypatch, tmp_path, [snoozed_task])
    request_id = task_triage._request_id(
        "sase", snoozed_task.id, 1, task_triage.BEAD_SNOOZE_KIND
    )
    task_triage._write_state(
        tmp_path / task_triage._STATE_FILENAME,
        {
            "sase": task_triage._ProjectState(
                gates={snoozed_task.id: request_id},
                generations={snoozed_task.id: 1},
                fingerprints={
                    snoozed_task.id: task_triage._presentation_fingerprint(snoozed_task)
                },
                kinds={snoozed_task.id: task_triage.BEAD_SNOOZE_KIND},
            )
        },
    )
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")
    monkeypatch.setattr(
        task_triage, "_gate_notification_id", lambda _kind, _id: "notif-1"
    )
    monkeypatch.setattr(
        task_triage,
        "create_bead_snooze_gate",
        lambda **_kwargs: pytest.fail("a current wake gate was recreated"),
    )
    _patch_notification_store(monkeypatch, rows=rows, snoozed=snoozed)
    return task_triage._run(_runtime(tmp_path))


def test_unmuted_wake_notification_is_re_snoozed_to_the_bead_wake_time(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    snoozed_task = _snoozed_task()
    snoozed: list[tuple[str, datetime]] = []
    rows = [_notification_row(muted=False, snooze_until=None)]

    result = _run_with_pending_snooze_gate(
        monkeypatch,
        tmp_path,
        snoozed_task=snoozed_task,
        rows=rows,
        snoozed=snoozed,
    )

    assert result.counters == {
        "gated": 0,
        "canceled": 0,
        "skipped": 1,
        "resnoozed": 1,
    }
    assert result.reason is None
    assert snoozed == [("notif-1", datetime.fromisoformat(snoozed_task.snooze.until))]


def test_wake_notification_already_snoozed_to_its_wake_time_is_left_alone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    snoozed_task = _snoozed_task()
    snoozed: list[tuple[str, datetime]] = []
    rows = [_notification_row(muted=True, snooze_until=snoozed_task.snooze.until)]

    result = _run_with_pending_snooze_gate(
        monkeypatch,
        tmp_path,
        snoozed_task=snoozed_task,
        rows=rows,
        snoozed=snoozed,
    )

    assert result.counters == {
        "gated": 0,
        "canceled": 0,
        "skipped": 1,
        "resnoozed": 0,
    }
    assert result.reason == "no_triage_changes"
    assert snoozed == []


def test_a_past_wake_time_leaves_the_resurfaced_notification_unread(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """After the wake, the row is meant to be visible — re-snoozing would hide it."""
    snoozed_task = _snoozed_task(until="2020-01-01T00:00:00+00:00")
    snoozed: list[tuple[str, datetime]] = []
    rows = [_notification_row(muted=False, snooze_until=None)]

    result = _run_with_pending_snooze_gate(
        monkeypatch,
        tmp_path,
        snoozed_task=snoozed_task,
        rows=rows,
        snoozed=snoozed,
    )

    assert result.counters == {
        "gated": 0,
        "canceled": 0,
        "skipped": 1,
        "resnoozed": 0,
    }
    assert snoozed == []


def test_a_pending_triage_gate_never_touches_the_notification_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = _task()
    _patch_project(monkeypatch, tmp_path, [task])
    request_id = task_triage._request_id(
        "sase", task.id, 1, task_triage.TASK_TRIAGE_KIND
    )
    task_triage._write_state(
        tmp_path / task_triage._STATE_FILENAME,
        {
            "sase": task_triage._ProjectState(
                gates={task.id: request_id},
                generations={task.id: 1},
                fingerprints={task.id: task_triage._presentation_fingerprint(task)},
                kinds={task.id: task_triage.TASK_TRIAGE_KIND},
            )
        },
    )
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")
    monkeypatch.setattr(
        task_triage,
        "_gate_notification_id",
        lambda *_args: pytest.fail("a triage gate read the notification store"),
    )

    result = task_triage._run(_runtime(tmp_path))

    assert result.counters == {
        "gated": 0,
        "canceled": 0,
        "skipped": 1,
        "resnoozed": 0,
    }
