"""Hourly bead_stale_cleanup chop reconciliation tests."""

from __future__ import annotations

import json
from datetime import timedelta
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import sase.scripts.sase_chop_bead_stale_cleanup as stale_cleanup
from sase.bead.model import Issue, IssueType, Status
from sase.chops.sdk import ChopLogger
from sase.scripts._bead_gate_projects import enabled_project_stores

from sase.task_types._models import (
    TaskTypeProvenance,
    TaskTypeRecord,
    TaskTypeRegistry,
)

from tests._axe_chop_bead_stale_cleanup_helpers import (
    NOW,
    capture_canceled,
    capture_created,
    expected_counters,
    make_due_flag,
    make_runtime,
    make_snoozed_task,
    make_task,
    patch_projects,
    patch_task_type_registry,
)


def _flake_task_type_registry(*, min_plus_ones: int) -> TaskTypeRegistry:
    record = TaskTypeRecord(
        task_type="flake",
        spec={"task_type": "flake", "triage": {"min_plus_ones": min_plus_ones}},
        digest="a" * 64,
        provenance=TaskTypeProvenance(
            source="builtin", name="sase", package="sase", version="1.0.0", builtin=True
        ),
    )
    return TaskTypeRegistry(records=(record,), diagnostics=())


def _state(tmp_path: Path) -> dict[str, Any]:
    path = tmp_path / stale_cleanup._STATE_FILENAME
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_ready_task_beads_requests_ready_tasks_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, object] = {}

    def fake_list(
        beads_dir: Path,
        statuses: object = None,
        issue_types: object = None,
        **_kwargs: object,
    ) -> list[Issue]:
        seen["beads_dir"] = beads_dir
        seen["statuses"] = statuses
        seen["issue_types"] = issue_types
        return []

    monkeypatch.setattr(stale_cleanup.rust_beads, "list_issues", fake_list)
    assert stale_cleanup._ready_task_beads(tmp_path) == []
    assert seen["beads_dir"] == tmp_path
    assert seen["statuses"] == [Status.READY]
    assert seen["issue_types"] == [IssueType.TASK]


def test_below_threshold_creates_no_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_projects(monkeypatch, tmp_path, [make_task()], stale_cleanup_min_beads=2)
    created = capture_created(monkeypatch)

    result = stale_cleanup._run(make_runtime(tmp_path))

    assert result.reason == "below_stale_threshold"
    assert result.counters == expected_counters(stale=1)
    assert created == []
    assert _state(tmp_path) == {}


def test_exactly_at_threshold_creates_one_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    beads = [make_task("sase-task.1"), make_task("sase-task.2")]
    patch_projects(monkeypatch, tmp_path, beads, stale_cleanup_min_beads=2)
    created = capture_created(monkeypatch)

    result = stale_cleanup._run(make_runtime(tmp_path))

    assert result.reason is None
    assert result.counters == expected_counters(gated=1, stale=2, offered=2)
    assert len(created) == 1
    assert created[0]["request_id"].endswith("-g1")
    assert created[0]["omitted_count"] == 0
    assert created[0]["min_plus_ones"] == 1
    assert created[0]["stale_after_days"] == 7
    assert created[0]["stale_cleanup_min_beads"] == 2
    assert created[0]["stale_as_of"] == NOW.isoformat()
    assert created[0]["producer"] == {"chop": "bead_stale_cleanup"}
    assert [bead["bead_id"] for bead in created[0]["beads"]] == [
        "sase-task.1",
        "sase-task.2",
    ]
    state = _state(tmp_path)
    assert state["request_id"] == created[0]["request_id"]
    assert state["generation"] == 1


def test_non_stale_beads_are_never_counted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    young = make_task("sase-task.young", created_at="2026-08-16T11:00:00-04:00")
    corroborated = make_task("sase-task.plus", plus_ones=1)
    open_task = make_task("sase-task.open", status=Status.OPEN)
    mixed = [
        young,
        corroborated,
        make_snoozed_task(),
        open_task,
        make_due_flag(),
        make_task("sase-task.stale"),
    ]
    patch_projects(monkeypatch, tmp_path, mixed, stale_cleanup_min_beads=1)
    created = capture_created(monkeypatch)

    result = stale_cleanup._run(make_runtime(tmp_path))

    assert result.counters == expected_counters(gated=1, stale=1, offered=1)
    assert [bead["bead_id"] for bead in created[0]["beads"]] == ["sase-task.stale"]


def test_ready_flag_task_beads_are_never_counted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    flag_task = make_task("sase-flag.ready", task_type="flag")
    mixed = [flag_task, make_task("sase-task.stale")]
    patch_projects(monkeypatch, tmp_path, mixed, stale_cleanup_min_beads=1)
    created = capture_created(monkeypatch)

    result = stale_cleanup._run(make_runtime(tmp_path))

    assert result.counters == expected_counters(gated=1, stale=1, offered=1)
    assert [bead["bead_id"] for bead in created[0]["beads"]] == ["sase-task.stale"]


def test_typed_bead_below_its_own_higher_type_bar_is_stale_despite_global_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    typed = make_task("sase-task.flake", task_type="flake")
    patch_projects(
        monkeypatch, tmp_path, [typed], min_plus_ones=0, stale_cleanup_min_beads=1
    )
    patch_task_type_registry(monkeypatch, _flake_task_type_registry(min_plus_ones=1))
    created = capture_created(monkeypatch)

    result = stale_cleanup._run(make_runtime(tmp_path))

    assert result.counters == expected_counters(gated=1, stale=1, offered=1)
    assert [bead["bead_id"] for bead in created[0]["beads"]] == ["sase-task.flake"]


def test_typed_bead_at_its_own_lower_type_bar_is_not_stale_despite_global_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    typed = make_task("sase-task.flake", task_type="flake")
    patch_projects(
        monkeypatch, tmp_path, [typed], min_plus_ones=5, stale_cleanup_min_beads=1
    )
    patch_task_type_registry(monkeypatch, _flake_task_type_registry(min_plus_ones=0))
    created = capture_created(monkeypatch)

    result = stale_cleanup._run(make_runtime(tmp_path))

    assert result.counters == expected_counters(stale=0)
    assert created == []


def test_roster_larger_than_cap_offers_oldest_and_reports_omitted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    count = stale_cleanup.BEAD_STALE_CLEANUP_MAX_BEADS + 3
    beads = [
        make_task(
            f"sase-task.{index:02d}",
            created_at=f"2026-07-{(index % 28) + 1:02d}T00:00:00-04:00",
        )
        for index in range(count)
    ]
    patch_projects(monkeypatch, tmp_path, beads, stale_cleanup_min_beads=2)
    created = capture_created(monkeypatch)

    result = stale_cleanup._run(make_runtime(tmp_path))

    assert result.counters == expected_counters(
        gated=1,
        stale=count,
        offered=stale_cleanup.BEAD_STALE_CLEANUP_MAX_BEADS,
        omitted=3,
    )
    offered_ids = [bead["bead_id"] for bead in created[0]["beads"]]
    expected = [
        entry.issue.id
        for entry in sorted(
            (stale_cleanup._StaleEntry(project="sase", issue=issue) for issue in beads),
            key=lambda entry: entry.sort_key(),
        )[: stale_cleanup.BEAD_STALE_CLEANUP_MAX_BEADS]
    ]
    assert offered_ids == expected
    assert created[0]["omitted_count"] == 3


def test_omitted_count_is_logged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    beads = [
        make_task(f"sase-task.{index}", created_at="2026-07-01T00:00:00-04:00")
        for index in range(stale_cleanup.BEAD_STALE_CLEANUP_MAX_BEADS + 1)
    ]
    patch_projects(monkeypatch, tmp_path, beads, stale_cleanup_min_beads=2)
    capture_created(monkeypatch)
    runtime = make_runtime(tmp_path)
    messages: list[str] = []
    monkeypatch.setattr(runtime.log, "info", messages.append)

    stale_cleanup._run(runtime)

    assert any("1 omitted" in message for message in messages)


def test_second_pass_with_unchanged_roster_leaves_pending_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    beads = [make_task("sase-task.1"), make_task("sase-task.2")]
    patch_projects(monkeypatch, tmp_path, beads)
    created = capture_created(monkeypatch)
    canceled = capture_canceled(monkeypatch)

    first = stale_cleanup._run(make_runtime(tmp_path))
    second = stale_cleanup._run(make_runtime(tmp_path))

    assert first.counters == expected_counters(gated=1, stale=2, offered=2)
    assert second.reason == "unchanged_roster"
    assert second.counters == expected_counters(skipped=1, stale=2, offered=2)
    assert len(created) == 1
    assert canceled == []


def test_stale_as_of_is_excluded_from_fingerprint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    beads = [make_task("sase-task.1"), make_task("sase-task.2")]
    patch_projects(monkeypatch, tmp_path, beads)
    created = capture_created(monkeypatch)

    stale_cleanup._run(make_runtime(tmp_path))
    monkeypatch.setattr(stale_cleanup, "_aware_now", lambda: NOW + timedelta(days=1))
    second = stale_cleanup._run(make_runtime(tmp_path))

    assert second.reason == "unchanged_roster"
    assert len(created) == 1


def test_changed_roster_cancels_and_recreates_with_next_generation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    beads = [make_task("sase-task.1"), make_task("sase-task.2")]
    patch_projects(monkeypatch, tmp_path, beads)
    created = capture_created(monkeypatch)
    canceled = capture_canceled(monkeypatch)

    stale_cleanup._run(make_runtime(tmp_path))
    beads.append(make_task("sase-task.3"))
    second = stale_cleanup._run(make_runtime(tmp_path))

    assert second.counters == expected_counters(gated=1, canceled=1, stale=3, offered=3)
    assert canceled == [(created[0]["request_id"], "stale_roster_changed")]
    assert created[0]["request_id"].endswith("-g1")
    assert created[1]["request_id"].endswith("-g2")
    assert created[0]["request_id"] != created[1]["request_id"]
    assert _state(tmp_path)["generation"] == 2


def test_backlog_below_threshold_cancels_pending_gate_and_clears_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    beads = [make_task("sase-task.1"), make_task("sase-task.2")]
    patch_projects(monkeypatch, tmp_path, beads)
    created = capture_created(monkeypatch)
    canceled = capture_canceled(monkeypatch)

    stale_cleanup._run(make_runtime(tmp_path))
    beads.clear()
    beads.append(make_task("sase-task.1"))
    result = stale_cleanup._run(make_runtime(tmp_path))

    assert result.reason is None
    assert result.counters == expected_counters(canceled=1, stale=1)
    assert canceled == [(created[0]["request_id"], "stale_backlog_below_threshold")]
    assert _state(tmp_path) == {}


def test_failed_project_read_does_not_cancel_healthy_pending_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    beads = [make_task("sase-task.1"), make_task("sase-task.2")]
    patch_projects(monkeypatch, tmp_path, beads)
    created = capture_created(monkeypatch)
    canceled = capture_canceled(monkeypatch)
    stale_cleanup._run(make_runtime(tmp_path))

    monkeypatch.setattr(
        stale_cleanup,
        "_enabled_project_stores",
        lambda _log: [
            ("broken", tmp_path / "broken"),
            ("sase", tmp_path / "sase"),
        ],
    )

    def ready(path: Path) -> list[Issue]:
        if path.name == "broken":
            raise OSError("unavailable")
        return list(beads)

    monkeypatch.setattr(stale_cleanup, "_ready_task_beads", ready)
    runtime = make_runtime(tmp_path)
    warnings: list[str] = []
    monkeypatch.setattr(runtime.log, "warning", warnings.append)
    result = stale_cleanup._run(runtime)

    assert result.reason == "unchanged_roster"
    assert result.counters == expected_counters(
        skipped=1, stale=2, offered=2, projects=1
    )
    assert canceled == []
    assert len(created) == 1
    assert any("Failed to read ready task beads" in message for message in warnings)


def test_failed_project_read_does_not_cancel_when_remaining_backlog_is_below_bar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    beads = [make_task("sase-task.1"), make_task("sase-task.2")]
    patch_projects(monkeypatch, tmp_path, beads)
    created = capture_created(monkeypatch)
    canceled = capture_canceled(monkeypatch)
    stale_cleanup._run(make_runtime(tmp_path))

    monkeypatch.setattr(
        stale_cleanup,
        "_enabled_project_stores",
        lambda _log: [
            ("broken", tmp_path / "broken"),
            ("sase", tmp_path / "sase"),
        ],
    )

    def ready(path: Path) -> list[Issue]:
        if path.name == "broken":
            raise OSError("unavailable")
        return [make_task("sase-task.1")]

    monkeypatch.setattr(stale_cleanup, "_ready_task_beads", ready)
    runtime = make_runtime(tmp_path)
    warnings: list[str] = []
    monkeypatch.setattr(runtime.log, "warning", warnings.append)
    result = stale_cleanup._run(runtime)

    assert result.reason == "incomplete_inventory"
    assert result.counters["canceled"] == 0
    assert result.counters["stale"] == 1
    assert canceled == []
    assert len(created) == 1
    assert any("Failed to read ready task beads" in message for message in warnings)


def test_inventory_failure_touches_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    beads = [make_task("sase-task.1"), make_task("sase-task.2")]
    patch_projects(monkeypatch, tmp_path, beads)
    created = capture_created(monkeypatch)
    canceled = capture_canceled(monkeypatch)
    stale_cleanup._run(make_runtime(tmp_path))
    pending = _state(tmp_path)

    monkeypatch.setattr(
        stale_cleanup,
        "_enabled_project_stores",
        lambda _log: (_ for _ in ()).throw(OSError("inventory unavailable")),
    )
    result = stale_cleanup._run(make_runtime(tmp_path))

    assert result.reason == "project_inventory_unavailable"
    assert result.counters == expected_counters(projects=0)
    assert canceled == []
    assert len(created) == 1
    assert _state(tmp_path) == pending


def test_dry_run_creates_and_cancels_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        stale_cleanup,
        "_enabled_project_stores",
        lambda _log: pytest.fail("dry run enumerated projects"),
    )
    created = capture_created(monkeypatch)
    canceled = capture_canceled(monkeypatch)

    result = stale_cleanup._run(make_runtime(tmp_path, dry_run=True))

    assert result.reason == "dry_run"
    assert result.counters == expected_counters(projects=0)
    assert created == []
    assert canceled == []
    assert _state(tmp_path) == {}


def test_two_projects_appear_in_one_gate_oldest_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_projects(
        monkeypatch,
        tmp_path,
        {
            "alpha": [
                make_task("sase-task.2", created_at="2026-08-01T09:14:02-04:00"),
                make_task("sase-task.1", created_at="2026-07-01T09:14:02-04:00"),
            ],
            "beta": [
                make_task("sase-task.1", created_at="2026-07-01T09:14:02-04:00"),
            ],
        },
        stale_cleanup_min_beads=2,
    )
    created = capture_created(monkeypatch)

    result = stale_cleanup._run(make_runtime(tmp_path))

    assert result.counters == expected_counters(gated=1, stale=3, offered=3, projects=2)
    assert [(bead["project"], bead["bead_id"]) for bead in created[0]["beads"]] == [
        ("alpha", "sase-task.1"),
        ("beta", "sase-task.1"),
        ("alpha", "sase-task.2"),
    ]


def test_task_triage_state_does_not_reexport_shared_inventory() -> None:
    import sase.scripts._bead_task_triage_state as task_triage_state

    assert not hasattr(task_triage_state, "ProjectInventory")
    assert not hasattr(task_triage_state, "enabled_project_stores")
    assert not hasattr(task_triage_state, "coerce_project_inventory")
    assert not hasattr(task_triage_state, "project_display_name")


def test_enabled_project_stores_labels_warnings_with_chop_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = SimpleNamespace(
        is_project=True,
        state="enabled",
        system_managed=False,
        project_name="widgets",
    )
    monkeypatch.setattr(
        "sase.scripts._bead_gate_projects.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    monkeypatch.setattr(
        "sase.scripts._bead_gate_projects.canonical_beads_dir_for_project",
        lambda _name: (_ for _ in ()).throw(OSError("missing store")),
    )
    monkeypatch.setattr(
        "sase.scripts._bead_gate_projects.project_display_name",
        lambda name: name,
    )
    stderr = StringIO()
    inventory = enabled_project_stores(
        ChopLogger(stdout=StringIO(), stderr=stderr),
        chop="bead_stale_cleanup",
    )

    assert inventory.stores == ()
    assert inventory.skipped_projects == frozenset({"widgets"})
    assert "[bead_stale_cleanup] Failed to locate bead store" in stderr.getvalue()


def test_terminal_gate_for_same_roster_is_regenerated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    beads = [make_task("sase-task.1"), make_task("sase-task.2")]
    patch_projects(monkeypatch, tmp_path, beads, gate_state="terminal")
    created = capture_created(monkeypatch)

    stale_cleanup._run(make_runtime(tmp_path))
    result = stale_cleanup._run(make_runtime(tmp_path))

    assert result.counters == expected_counters(gated=1, stale=2, offered=2)
    assert created[0]["request_id"].endswith("-g1")
    assert created[1]["request_id"].endswith("-g2")
