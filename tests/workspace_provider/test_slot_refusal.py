"""Durable nested-preservation refusals quarantine a workspace slot."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.agent.launch_executor_types import LaunchExecutionContext
from sase.agent.launch_executor_workspace import spawn_slot_with_workspace_retry
from sase.axe.runner_workspace_errors import WorkspacePreparationError
from sase.axe.runner_workspace_protection import prepare_launch_workspace_repos
from sase.core.agent_launch_wire import LaunchFanoutSlotWire
from sase.notifications.store import load_notifications
from sase.running_field import (
    WorkspaceClaimError,
    claim_next_axe_workspace,
    get_first_available_workspace,
)
from sase.workspace_provider import (
    _snapshot_capture_payload_objects as payload_objects_module,
)
from sase.workspace_provider.slot_refusal import (
    _DIRTY_PATHS_LIMIT,
    _SLOT_REFUSAL_SENDER,
    _active_refusal,
    bounded_dirty_paths,
    clear_refusal,
    format_actionable_message,
    list_refusals,
    raise_if_workspace_quarantined,
    record_slot_refusal,
    skip_workspace_nums_for_project,
)
from tests.workspace_provider.test_rescue._helpers import (
    git,
    init_repo,
    redirect_state,
)


WORKSPACE_NUM = 10
PROJECT = "demo"


def _isolate_git(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_NAMESPACE",
    ):
        monkeypatch.delenv(key, raising=False)


def _sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, list[tuple[object, ...]]]:
    _isolate_git(monkeypatch)
    return redirect_state(tmp_path, monkeypatch)


def _project_file(tmp_path: Path, name: str = PROJECT) -> Path:
    path = tmp_path / f"{name}.sase"
    path.write_text("# Test Project\n\nNAME: Demo\nSTATUS: Ready\n", encoding="utf-8")
    return path


def _dirty_nested(path: Path) -> Path:
    init_repo(path)
    (path / "tracked.txt").write_text("base\n", encoding="utf-8")
    git(path, "add", "--", "tracked.txt")
    git(path, "commit", "-m", "base")
    (path / "tracked.txt").write_text("dirty-working\n", encoding="utf-8")
    (path / "untracked.bin").write_bytes(b"x" * 200)
    return path


def _workspace_with_dirty_nested(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    nested = _dirty_nested(workspace / "sase" / "repos" / "linked" / "plugin")
    return workspace, nested


def _configure_launch(monkeypatch: pytest.MonkeyPatch, workspace: Path) -> None:
    monkeypatch.setattr(
        "sase.axe.runner_workspace_protection.protect_unpushed_sidecar_commits",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.sdd._paths.get_primary_workspace_dir", lambda *_args: str(workspace)
    )
    monkeypatch.setattr(
        "sase.sdd._store_records.is_materialized_record", lambda _r: False
    )
    monkeypatch.setattr(
        "sase.sdd._store_records.read_sdd_store_record", lambda _p: None
    )
    monkeypatch.setattr("sase.sdd.store.auto_connect_sdd_store", lambda *_args: False)
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone", lambda *_a, **_k: None
    )


def _refusal_notifications() -> list[object]:
    return [
        note for note in load_notifications() if note.sender == _SLOT_REFUSAL_SENDER
    ]


def test_record_slot_refusal_notifies_once_and_skips_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sandbox(tmp_path, monkeypatch)
    nested = _dirty_nested(tmp_path / "nested")
    first = record_slot_refusal(
        project=PROJECT,
        workspace_num=WORKSPACE_NUM,
        nested_repo=nested,
        reason="cap exceeded",
    )
    second = record_slot_refusal(
        project=PROJECT,
        workspace_num=WORKSPACE_NUM,
        nested_repo=nested,
        reason="cap exceeded again",
    )
    assert first == second
    assert first.reason == "cap exceeded"
    notes = _refusal_notifications()
    assert len(notes) == 1
    assert "quarantined" in notes[0].notes[0]
    assert f"repair -C {WORKSPACE_NUM} -p {PROJECT}" in notes[0].notes[0]


def test_skip_list_and_pin_fail_fast_while_nested_is_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sandbox(tmp_path, monkeypatch)
    nested = _dirty_nested(tmp_path / "nested")
    record_slot_refusal(
        project=PROJECT,
        workspace_num=WORKSPACE_NUM,
        nested_repo=nested,
        reason="cap exceeded",
        notify=False,
    )
    project_file = _project_file(tmp_path)
    assert skip_workspace_nums_for_project(PROJECT) == frozenset({WORKSPACE_NUM})
    assert get_first_available_workspace(str(project_file)) == 11
    with pytest.raises(WorkspaceClaimError, match="quarantined") as exc_info:
        raise_if_workspace_quarantined(PROJECT, WORKSPACE_NUM)
    assert exc_info.value.workspace_num == WORKSPACE_NUM
    raise_if_workspace_quarantined(PROJECT, 11)


def test_claim_next_forwards_quarantined_slots_to_allocator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sandbox(tmp_path, monkeypatch)
    nested = _dirty_nested(tmp_path / "nested")
    record_slot_refusal(
        project=PROJECT,
        workspace_num=WORKSPACE_NUM,
        nested_repo=nested,
        reason="cap exceeded",
        notify=False,
    )
    project_file = _project_file(tmp_path)
    forwarded: list[tuple[int, ...]] = []
    import sase.running_field._claim as claim_mod

    real = claim_mod.allocate_and_claim_workspace_from_content

    def capture(
        content: str,
        min_workspace: int,
        max_workspace: int,
        request: object,
    ) -> object:
        forwarded.append(tuple(request.skip_workspaces))
        return real(content, min_workspace, max_workspace, request)

    monkeypatch.setattr(claim_mod, "allocate_and_claim_workspace_from_content", capture)
    claim_next_axe_workspace(str(project_file), "spy-demo", 12345, cl_name="demo")
    assert forwarded == [(WORKSPACE_NUM,)]


def test_auto_clear_when_nested_repo_is_clean_or_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sandbox(tmp_path, monkeypatch)
    nested = _dirty_nested(tmp_path / "nested")
    record_slot_refusal(
        project=PROJECT,
        workspace_num=WORKSPACE_NUM,
        nested_repo=nested,
        reason="cap exceeded",
        notify=False,
    )
    git(nested, "checkout", "--", ".")
    git(nested, "clean", "-fd")
    assert _active_refusal(PROJECT, WORKSPACE_NUM) is None
    assert skip_workspace_nums_for_project(PROJECT) == frozenset()

    gone = tmp_path / "gone-nested"
    record_slot_refusal(
        project=PROJECT,
        workspace_num=11,
        nested_repo=gone,
        reason="cap exceeded",
        notify=False,
        dirty_paths=("tracked.txt",),
    )
    assert _active_refusal(PROJECT, 11) is None


def test_bounded_dirty_paths_cap_and_clean_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sandbox(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    init_repo(repo)
    assert bounded_dirty_paths(repo) == ()
    for index in range(_DIRTY_PATHS_LIMIT + 5):
        (repo / f"dirty-{index}.txt").write_text("x\n", encoding="utf-8")
    listed = bounded_dirty_paths(repo)
    assert listed is not None
    assert len(listed) == _DIRTY_PATHS_LIMIT


def test_preservation_refusal_quarantines_slot_and_second_launch_skips_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sandbox(tmp_path, monkeypatch)
    workspace, nested = _workspace_with_dirty_nested(tmp_path)
    _configure_launch(monkeypatch, workspace)
    monkeypatch.setattr(payload_objects_module, "SNAPSHOT_MAX_BYTES", 16)
    project_file = _project_file(tmp_path)

    with pytest.raises(WorkspacePreparationError) as first:
        prepare_launch_workspace_repos(str(workspace), WORKSPACE_NUM, project=PROJECT)
    assert first.value.step == "sidecar-protection"
    assert first.value.reclone_eligible is False
    message = str(first.value)
    assert "quarantined" in message
    assert str(nested.resolve()) in message
    assert f"repair -C {WORKSPACE_NUM} -p {PROJECT}" in message
    assert nested.is_dir()

    with pytest.raises(WorkspacePreparationError):
        prepare_launch_workspace_repos(str(workspace), WORKSPACE_NUM, project=PROJECT)
    notes = _refusal_notifications()
    assert len(notes) == 1
    standing = list_refusals(PROJECT)
    assert len(standing) == 1
    assert standing[0].workspace_num == WORKSPACE_NUM
    assert skip_workspace_nums_for_project(PROJECT) == frozenset({WORKSPACE_NUM})
    assert get_first_available_workspace(str(project_file)) == 11

    spawned: list[object] = []
    with pytest.raises(WorkspaceClaimError, match="quarantined"):
        spawn_slot_with_workspace_retry(
            slot=LaunchFanoutSlotWire(
                prompt="do work", launch_kind="single", slot_index=0
            ),
            context=LaunchExecutionContext(
                cl_name="change",
                project_file=str(project_file),
                project_name=PROJECT,
                workspace_num=WORKSPACE_NUM,
                workspace_dir=str(workspace),
                use_preallocated_workspace=True,
            ),
            workflow_name="run",
            timestamp="ts",
            extra_env=None,
            local_macros_file=None,
            spawn=lambda request: spawned.append(request),
        )
    assert spawned == []

    git(nested, "checkout", "--", ".")
    git(nested, "clean", "-fd")
    monkeypatch.setattr(payload_objects_module, "SNAPSHOT_MAX_BYTES", 16)
    prepare_launch_workspace_repos(str(workspace), WORKSPACE_NUM, project=PROJECT)
    assert list_refusals(PROJECT) == []
    assert skip_workspace_nums_for_project(PROJECT) == frozenset()


def test_manual_clear_unquarantines_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sandbox(tmp_path, monkeypatch)
    nested = _dirty_nested(tmp_path / "nested")
    record = record_slot_refusal(
        project=PROJECT,
        workspace_num=WORKSPACE_NUM,
        nested_repo=nested,
        reason="cap exceeded",
        notify=False,
    )
    assert "Force-clear" in format_actionable_message(record)
    removed = clear_refusal(PROJECT, WORKSPACE_NUM)
    assert removed is not None
    assert skip_workspace_nums_for_project(PROJECT) == frozenset()
    assert clear_refusal(PROJECT, WORKSPACE_NUM) is None
