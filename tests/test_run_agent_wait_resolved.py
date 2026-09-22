"""Tests for resolved/fast-path run-agent waits."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_wait import wait_for_dependencies

from tests._agent_names_fixtures import make_agent
from tests._run_agent_wait_helpers import (
    make_submitted_planner,
    make_waiter,
    patch_index_updates,
)


def test_resolved_named_wait_skips_waiting_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "dep",
        done=True,
        outcome="completed",
    )
    waiter_dir = make_waiter(tmp_path)
    agent_meta = {"pid": 123}
    index_updates: list[str] = []
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch_index_updates(lambda path: index_updates.append(path)),
        patch("sase.axe.run_agent_wait.time.sleep") as sleep_mock,
    ):
        blocked = wait_for_dependencies(
            ["dep"],
            str(waiter_dir),
            "cl",
            "20260513120000",
            agent_meta,
            project_name="proj",
        )

    sleep_mock.assert_not_called()
    assert blocked is False
    assert index_updates == []
    assert not (waiter_dir / "waiting.json").exists()
    assert not (waiter_dir / "ready.json").exists()
    assert isinstance(agent_meta.get("wait_completed_at"), str)
    disk_meta = json.loads((waiter_dir / "agent_meta.json").read_text())
    assert disk_meta["wait_completed_at"] == agent_meta["wait_completed_at"]


def test_submitted_plan_row_wait_skips_waiting_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_submitted_planner(tmp_path, "20260625184716", "planner")
    waiter_dir = make_waiter(tmp_path)
    agent_meta = {"pid": 123}
    index_updates: list[str] = []
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch_index_updates(lambda path: index_updates.append(path)),
        patch("sase.axe.run_agent_wait.time.sleep") as sleep_mock,
    ):
        wait_for_dependencies(
            ["planner--plan"],
            str(waiter_dir),
            "cl",
            "20260513120000",
            agent_meta,
            project_name="proj",
        )

    sleep_mock.assert_not_called()
    assert index_updates == []
    assert not (waiter_dir / "waiting.json").exists()
    assert isinstance(agent_meta.get("wait_completed_at"), str)


def test_initial_identity_wait_excludes_waiter_from_family_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_dir = make_agent(
        tmp_path,
        "proj",
        "20260706130831",
        "b",
        done=True,
        outcome="completed",
    )
    waiter_dir = make_agent(
        tmp_path,
        "proj",
        "20260706131004",
        "b--launch",
        workflow_name="b",
        agent_family="b",
        parent_timestamp=parent_dir.name,
    )
    agent_meta = {"pid": 123}
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch("sase.axe.run_agent_wait.time.sleep") as sleep_mock,
    ):
        wait_for_dependencies(
            ["b"],
            str(waiter_dir),
            "cl",
            "20260706131004",
            agent_meta,
            project_name="proj",
            wait_identity_deps=[
                {
                    "project_name": "proj",
                    "timestamp": parent_dir.name,
                    "artifact_dir": str(parent_dir),
                    "name": "b",
                }
            ],
        )

    sleep_mock.assert_not_called()
    assert not (waiter_dir / "waiting.json").exists()
    assert isinstance(agent_meta.get("wait_completed_at"), str)


def test_unresolved_named_wait_uses_slow_waiting_marker_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiter_dir = make_waiter(tmp_path)
    (waiter_dir / "ready.json").write_text("{}", encoding="utf-8")
    index_updates: list[str] = []
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch_index_updates(lambda path: index_updates.append(path)),
    ):
        wait_for_dependencies(
            ["missing"],
            str(waiter_dir),
            "cl",
            "20260513120000",
            {"pid": 123},
            project_name="proj",
        )

    assert index_updates == [str(waiter_dir), str(waiter_dir)]
    assert not (waiter_dir / "waiting.json").exists()
    assert not (waiter_dir / "ready.json").exists()


@pytest.mark.parametrize(
    "wait_kwargs",
    [
        {"duration": 0},
        {"wait_until": "2000-01-01T00:00:00"},
    ],
)
def test_named_wait_with_time_floor_uses_slow_waiting_marker_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    wait_kwargs: dict[str, float | str],
) -> None:
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "dep",
        done=True,
        outcome="completed",
    )
    waiter_dir = make_waiter(tmp_path)
    (waiter_dir / "ready.json").write_text("{}", encoding="utf-8")
    index_updates: list[str] = []
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch_index_updates(lambda path: index_updates.append(path)),
    ):
        wait_for_dependencies(
            ["dep"],
            str(waiter_dir),
            "cl",
            "20260513120000",
            {"pid": 123},
            project_name="proj",
            **wait_kwargs,
        )

    assert index_updates == [str(waiter_dir), str(waiter_dir)]
    assert not (waiter_dir / "waiting.json").exists()
    assert not (waiter_dir / "ready.json").exists()
