"""Ready task-bead triage chop tests."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

import sase.scripts.sase_chop_bead_task_triage as task_triage
from sase.axe.chop_script_context import ChopScriptContext
from sase.bead.model import Issue, IssueType, PhaseSize, Status, TaskPlusOneEvidence
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

    assert result.counters == {"gated": 1, "canceled": 0, "skipped": 0}
    assert created[0]["created_by"] == ""


def test_missing_presentation_fingerprint_is_canceled_and_recreated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ready = [_task()]
    _patch_project(monkeypatch, tmp_path, ready)
    old_request_id = task_triage._request_id("sase", "sase-task.1", 1)
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
    monkeypatch.setattr(task_triage, "_gate_state", lambda _request_id: "pending")
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda request_id, *, reason: canceled.append((request_id, reason)) or True,
    )
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: created.append(kwargs),
    )

    result = task_triage._run(_runtime(tmp_path))

    assert result.counters == {"gated": 1, "canceled": 1, "skipped": 0}
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
    request_id = task_triage._request_id("sase", "sase-task.1", 1)
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
    monkeypatch.setattr(task_triage, "_gate_state", lambda _request_id: "pending")
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
    assert result.counters == {"gated": 0, "canceled": 0, "skipped": 1}


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
    monkeypatch.setattr(task_triage, "_gate_state", lambda _request_id: "pending")
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda request_id, *, reason: canceled.append((request_id, reason)) or True,
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

    assert refreshed.counters == {"gated": 1, "canceled": 1, "skipped": 0}
    assert canceled == [(created[0]["request_id"], "task_triage_presentation_changed")]
    assert created[1]["plus_one_evidence"] == task.plus_one_evidence
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
