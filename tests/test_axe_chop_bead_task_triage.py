"""Ready task-bead triage chop tests."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

import sase.scripts.sase_chop_bead_task_triage as task_triage
from sase.axe.chop_script_context import ChopScriptContext
from sase.bead.model import Issue, IssueType, Status
from sase.chops.builtin import BuiltinChopRuntime
from sase.chops.sdk import ChopLogger


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


def _task(bead_id: str = "sase-task.1") -> Issue:
    return Issue(
        id=bead_id,
        title="Follow up on cache invalidation",
        status=Status.READY,
        issue_type=IssueType.TASK,
        description="Make cache invalidation deterministic.",
        notes="Discovered while landing sase-bg.",
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
    monkeypatch.setattr(task_triage, "_ready_tasks", lambda _path: list(ready))


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
    monkeypatch.setattr(task_triage, "_gate_state", lambda _request_id: "pending")

    first = task_triage._run(_runtime(tmp_path))
    second = task_triage._run(_runtime(tmp_path))

    assert first.counters == {"gated": 1, "canceled": 0, "skipped": 0}
    assert second.counters == {"gated": 0, "canceled": 0, "skipped": 1}
    assert second.reason == "no_triage_changes"
    assert len(created) == 1
    assert created[0]["bead_id"] == "sase-task.1"
    assert created[0]["project"] == "sase"
    assert created[0]["title"] == "Follow up on cache invalidation"
    assert created[0]["request_id"].endswith("-g1")

    state = json.loads(
        (tmp_path / task_triage._STATE_FILENAME).read_text(encoding="utf-8")
    )
    assert state["projects"]["sase"]["gates"] == {
        "sase-task.1": created[0]["request_id"]
    }
    assert state["projects"]["sase"]["generations"] == {"sase-task.1": 1}


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
    monkeypatch.setattr(task_triage, "_gate_state", lambda _request_id: "pending")
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda request_id: canceled.append(request_id) or True,
    )

    task_triage._run(_runtime(tmp_path))
    ready.clear()
    stale = task_triage._run(_runtime(tmp_path))
    ready.append(_task())
    raised_again = task_triage._run(_runtime(tmp_path))

    assert stale.counters == {"gated": 0, "canceled": 1, "skipped": 0}
    assert canceled == [created[0]]
    assert raised_again.counters == {"gated": 1, "canceled": 0, "skipped": 0}
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
    monkeypatch.setattr(task_triage, "_gate_state", lambda _request_id: "terminal")

    task_triage._run(_runtime(tmp_path))
    result = task_triage._run(_runtime(tmp_path))

    assert result.counters == {"gated": 1, "canceled": 0, "skipped": 0}
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

    monkeypatch.setattr(task_triage, "_ready_tasks", read)
    created: list[str] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs["request_id"]),
    )

    result = task_triage._run(_runtime(tmp_path))

    assert result.counters == {"gated": 1, "canceled": 0, "skipped": 0}
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
        lambda _request_id: (_ for _ in ()).throw(OSError("unreadable gate")),
    )
    result = task_triage._run(_runtime(tmp_path))

    assert result.reason == "no_triage_changes"
    assert result.counters == {"gated": 0, "canceled": 0, "skipped": 0}
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
    assert result.counters == {"gated": 0, "canceled": 0, "skipped": 0}
    assert not (tmp_path / task_triage._STATE_FILENAME).exists()


def test_request_ids_are_deterministic_project_scoped_and_bounded() -> None:
    bead_id = "sase-" + ("x" * 120)

    first = task_triage._request_id("gh_sase-org__sase", bead_id, 1)
    repeated = task_triage._request_id("gh_sase-org__sase", bead_id, 1)
    other_project = task_triage._request_id("other", bead_id, 1)

    assert first == repeated
    assert first != other_project
    assert first.endswith("-g1")
    assert len(first) <= 128
