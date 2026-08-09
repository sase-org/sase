"""Artifact identity tests for the wait_checks chop script."""

import json
from pathlib import Path

import pytest

from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent, run_wait_checks


def _identity_dep(artifact_dir: Path, *, name: str = "foo") -> dict[str, str]:
    return {
        "project_name": "proj",
        "timestamp": artifact_dir.name,
        "artifact_dir": str(artifact_dir),
        "name": name,
    }


def test_identity_wait_running_parent_stays_unresolved(
    tmp_path: Path, monkeypatch
) -> None:
    parent_dir = make_agent(tmp_path, "proj", "20260506010101", "foo")
    waiter_dir = make_waiting_agent(
        tmp_path,
        "foo",
        wait_for_artifacts=[_identity_dep(parent_dir)],
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_identity_wait_completed_parent_writes_ready(
    tmp_path: Path, monkeypatch
) -> None:
    parent_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="completed",
    )
    waiter_dir = make_waiting_agent(
        tmp_path,
        "foo",
        wait_for_artifacts=[_identity_dep(parent_dir)],
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["foo"]}


def test_identity_wait_epic_approved_parent_writes_ready(
    tmp_path: Path, monkeypatch
) -> None:
    parent_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="epic_approved",
    )
    waiter_dir = make_waiting_agent(
        tmp_path,
        "foo",
        wait_for_artifacts=[_identity_dep(parent_dir)],
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["foo"]}


def test_identity_wait_ignores_newer_same_named_agent(
    tmp_path: Path, monkeypatch
) -> None:
    parent_dir = make_agent(tmp_path, "proj", "20260506010101", "foo")
    make_agent(
        tmp_path,
        "proj",
        "20260506020202",
        "foo",
        done=True,
        outcome="completed",
    )
    waiter_dir = make_waiting_agent(
        tmp_path,
        "foo",
        wait_for_artifacts=[_identity_dep(parent_dir)],
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


@pytest.mark.parametrize(
    "outcome",
    ["failed", "killed", "stopped", "epic_launch_failed"],
)
def test_identity_wait_failed_parent_keeps_waiting(
    tmp_path: Path, monkeypatch, outcome: str
) -> None:
    parent_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome=outcome,
    )
    waiter_dir = make_waiting_agent(
        tmp_path,
        "foo",
        wait_for_artifacts=[_identity_dep(parent_dir)],
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_identity_wait_repeat_stopped_parent_keeps_waiting(
    tmp_path: Path, monkeypatch
) -> None:
    parent_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="completed",
    )
    done = json.loads((parent_dir / "done.json").read_text(encoding="utf-8"))
    done["repeat_stopped"] = True
    done["stopped_by"] = "foo.1"
    (parent_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")
    waiter_dir = make_waiting_agent(
        tmp_path,
        "foo",
        wait_for_artifacts=[_identity_dep(parent_dir)],
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


@pytest.mark.parametrize(
    "outcome", ["failed", "killed", "stopped", "epic_launch_failed"]
)
def test_identity_wait_resolves_after_failed_parent_is_relaunched(
    tmp_path: Path, monkeypatch, outcome: str
) -> None:
    parent_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome=outcome,
    )
    waiter_dir = make_waiting_agent(
        tmp_path,
        "foo",
        wait_for_artifacts=[_identity_dep(parent_dir)],
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506020202",
        "foo",
        done=True,
        outcome="completed",
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["foo"]}
