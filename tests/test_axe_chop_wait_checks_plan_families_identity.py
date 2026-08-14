"""Identity-aware plan-family wait_checks chop script tests."""

import json
from pathlib import Path

import pytest

from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import (
    make_waiting_agent,
    run_wait_checks,
    write_workflow_state,
)


def _identity_dep(artifact_dir: Path, *, name: str) -> dict[str, str]:
    return {
        "project_name": "proj",
        "timestamp": artifact_dir.name,
        "artifact_dir": str(artifact_dir),
        "name": name,
    }


def _write_waiting_marker(
    artifact_dir: Path,
    *waiting_for: str,
    wait_for_artifacts: list[dict[str, str]] | None = None,
) -> None:
    marker: dict[str, object] = {
        "waiting_for": list(waiting_for),
        "cl_name": "waiter-cl",
        "timestamp": artifact_dir.name,
    }
    if wait_for_artifacts is not None:
        marker["wait_for_artifacts"] = wait_for_artifacts
    (artifact_dir / "waiting.json").write_text(
        json.dumps(marker),
        encoding="utf-8",
    )


def test_identity_wait_successful_plan_family_generation_resolves(
    tmp_path: Path, monkeypatch
) -> None:
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "planfam",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="--plan",
    )
    write_workflow_state(root_dir)
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "planfam--code",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="--code",
        parent_timestamp="20260506010101",
        done=True,
        outcome="completed",
    )
    waiter_dir = make_waiting_agent(
        tmp_path,
        "planfam",
        wait_for_artifacts=[_identity_dep(root_dir, name="planfam")],
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["planfam"]}


def test_identity_wait_failed_plan_family_generation_keeps_waiting(
    tmp_path: Path, monkeypatch
) -> None:
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "planfam",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="--plan",
    )
    write_workflow_state(root_dir)
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "planfam--code",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="--code",
        parent_timestamp="20260506010101",
        done=True,
        outcome="failed",
    )
    waiter_dir = make_waiting_agent(
        tmp_path,
        "planfam",
        wait_for_artifacts=[_identity_dep(root_dir, name="planfam")],
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


@pytest.mark.parametrize("parent_has_family_meta", [False, True])
def test_queued_family_child_does_not_block_its_parent_dependency(
    tmp_path: Path,
    monkeypatch,
    parent_has_family_meta: bool,
) -> None:
    parent_dir = make_agent(
        tmp_path,
        "proj",
        "20260706130831",
        "b",
        workflow_name="b" if parent_has_family_meta else None,
        agent_family="b" if parent_has_family_meta else None,
        done=True,
        outcome="completed",
    )
    child_dir = make_agent(
        tmp_path,
        "proj",
        "20260706131004",
        "b--launch",
        workflow_name="b",
        agent_family="b",
        parent_timestamp=parent_dir.name,
    )
    _write_waiting_marker(
        child_dir,
        "b",
        wait_for_artifacts=[_identity_dep(parent_dir, name="b")],
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((child_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["b"]}


def test_queued_family_child_blocks_external_wait_on_whole_family(
    tmp_path: Path,
    monkeypatch,
) -> None:
    parent_dir = make_agent(
        tmp_path,
        "proj",
        "20260706130831",
        "b--plan",
        workflow_name="b",
        agent_family="b",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    child_dir = make_agent(
        tmp_path,
        "proj",
        "20260706131004",
        "b--launch",
        workflow_name="b",
        agent_family="b",
        role_suffix="--launch",
        parent_timestamp=parent_dir.name,
    )
    _write_waiting_marker(
        child_dir,
        "b",
        wait_for_artifacts=[_identity_dep(parent_dir, name="b")],
    )
    external_waiter = make_waiting_agent(tmp_path, "b", suffix="external-waiter")

    run_wait_checks(tmp_path, monkeypatch)

    assert not (external_waiter / "ready.json").exists()


def test_queued_family_siblings_do_not_mutually_block_parent_dependency(
    tmp_path: Path,
    monkeypatch,
) -> None:
    parent_dir = make_agent(
        tmp_path,
        "proj",
        "20260706130831",
        "b",
        done=True,
        outcome="completed",
    )
    first_child_dir = make_agent(
        tmp_path,
        "proj",
        "20260706131004",
        "b--launch",
        workflow_name="b",
        agent_family="b",
        parent_timestamp=parent_dir.name,
    )
    second_child_dir = make_agent(
        tmp_path,
        "proj",
        "20260706131105",
        "b--review",
        workflow_name="b",
        agent_family="b",
        parent_timestamp=parent_dir.name,
    )
    for child_dir in (first_child_dir, second_child_dir):
        _write_waiting_marker(
            child_dir,
            "b",
            wait_for_artifacts=[_identity_dep(parent_dir, name="b")],
        )

    run_wait_checks(tmp_path, monkeypatch)

    assert json.loads((first_child_dir / "ready.json").read_text()) == {
        "resolved_deps": ["b"]
    }
    assert json.loads((second_child_dir / "ready.json").read_text()) == {
        "resolved_deps": ["b"]
    }


def test_stale_waiting_marker_on_failed_family_member_keeps_waiting(
    tmp_path: Path,
    monkeypatch,
) -> None:
    parent_dir = make_agent(
        tmp_path,
        "proj",
        "20260706130831",
        "b",
        workflow_name="b",
        agent_family="b",
        done=True,
        outcome="completed",
    )
    failed_child_dir = make_agent(
        tmp_path,
        "proj",
        "20260706131004",
        "b--launch",
        workflow_name="b",
        agent_family="b",
        parent_timestamp=parent_dir.name,
        done=True,
        outcome="killed",
    )
    _write_waiting_marker(failed_child_dir, "old-dep")
    waiter_dir = make_waiting_agent(
        tmp_path,
        "b",
        wait_for_artifacts=[_identity_dep(parent_dir, name="b")],
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()
