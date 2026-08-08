"""Tests for pre-run wait marker lifecycle."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.run_agent_wait import wait_for_dependencies

from tests._agent_names_fixtures import make_agent


@contextmanager
def _patch_index_updates(side_effect: Callable[[str], None]) -> Iterator[None]:
    """Observe Tier 1 index refreshes from both wait modules.

    ``waiting.json`` is published by ``run_agent_wait_markers`` while the wait
    barrier removes it inline, so both bindings must be intercepted.
    """
    with (
        patch(
            "sase.axe.run_agent_wait.update_agent_artifact_index_for_marker_mutation",
            side_effect=side_effect,
        ),
        patch(
            "sase.axe.run_agent_wait_markers."
            "update_agent_artifact_index_for_marker_mutation",
            side_effect=side_effect,
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def _disable_real_axe_ensure() -> Iterator[MagicMock]:
    """Keep wait-loop tests isolated from the host axe daemon."""
    with patch("sase.axe.run_agent_wait._opportunistic_ensure_axe") as ensure:
        yield ensure


def _make_waiter(base: Path, project: str = "proj") -> Path:
    artifact_dir = base / ".sase/projects" / project / "artifacts/ace-run/waiter"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps({"pid": 123}),
        encoding="utf-8",
    )
    return artifact_dir


def _make_submitted_planner(base: Path, timestamp: str, name: str) -> Path:
    """Create a submitted-and-waiting planner artifact (no done.json)."""
    artifact_dir = make_agent(
        base,
        "proj",
        timestamp,
        name,
        workflow_name=name,
        agent_family=name,
        role_suffix="--plan",
    )
    meta_path = artifact_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["plan"] = True
    meta["plan_submitted_at"] = ["2026-06-25T18:47:16+00:00"]
    meta["plan_path"] = "sdd/plans/202606/example.md"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    (artifact_dir / "plan_path.json").write_text(
        json.dumps({"plan_path": "sdd/plans/202606/example.md"}),
        encoding="utf-8",
    )
    return artifact_dir


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
    waiter_dir = _make_waiter(tmp_path)
    agent_meta = {"pid": 123}
    index_updates: list[str] = []
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        _patch_index_updates(lambda path: index_updates.append(path)),
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
    _make_submitted_planner(tmp_path, "20260625184716", "planner")
    waiter_dir = _make_waiter(tmp_path)
    agent_meta = {"pid": 123}
    index_updates: list[str] = []
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        _patch_index_updates(lambda path: index_updates.append(path)),
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
    waiter_dir = _make_waiter(tmp_path)
    (waiter_dir / "ready.json").write_text("{}", encoding="utf-8")
    index_updates: list[str] = []
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        _patch_index_updates(lambda path: index_updates.append(path)),
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


def test_bead_only_wait_writes_marker_and_names_only_beads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    waiter_dir = _make_waiter(tmp_path)
    ready_path = waiter_dir / "ready.json"
    marker_snapshots: list[dict[str, object]] = []
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    def publish_ready_after_poll(_seconds: float) -> None:
        marker_snapshots.append(
            json.loads((waiter_dir / "waiting.json").read_text(encoding="utf-8"))
        )
        ready_path.write_text("{}", encoding="utf-8")

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch(
            "sase.bead.store_locator.closed_bead_ids_for_project",
            return_value=frozenset(),
        ),
        patch(
            "sase.axe.run_agent_wait.time.sleep",
            side_effect=publish_ready_after_poll,
        ),
    ):
        blocked = wait_for_dependencies(
            [],
            str(waiter_dir),
            "cl",
            "20260720120000",
            {"pid": 123},
            project_name="proj",
            wait_beads=["sase-87.3"],
        )

    assert blocked is True
    assert marker_snapshots == [
        {
            "waiting_for": [],
            "patch_name": "cl",
            "cl_name": "cl",
            "timestamp": "20260720120000",
            "wait_for_beads": ["sase-87.3"],
        }
    ]
    output = capsys.readouterr().out
    assert "Waiting for beads: sase-87.3" in output
    assert "agents:" not in output


def test_unresolved_named_wait_opportunistically_ensures_axe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _disable_real_axe_ensure: MagicMock,
) -> None:
    waiter_dir = _make_waiter(tmp_path)
    ready_path = waiter_dir / "ready.json"
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    def resolve_after_poll(_seconds: float) -> None:
        ready_path.write_text("{}", encoding="utf-8")

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch(
            "sase.axe.run_agent_wait.time.sleep",
            side_effect=resolve_after_poll,
        ),
    ):
        wait_for_dependencies(
            ["missing"],
            str(waiter_dir),
            "cl",
            "20260513120000",
            {"pid": 123},
            project_name="proj",
        )

    _disable_real_axe_ensure.assert_called_once_with()


def test_stale_cancelled_ready_marker_is_removed_and_wait_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiter_dir = _make_waiter(tmp_path)
    (waiter_dir / "ready.json").write_text(
        json.dumps(
            {
                "cancelled": True,
                "reason": "dependency_failed",
                "failed_deps": [
                    {
                        "name": "foo",
                        "timestamp": "20260506010101",
                        "project_name": "proj",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    def resolve_after_stale_marker_is_removed(_seconds: float) -> None:
        assert not (waiter_dir / "ready.json").exists()
        (waiter_dir / "ready.json").write_text("{}", encoding="utf-8")

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch(
            "sase.axe.run_agent_wait.time.sleep",
            side_effect=resolve_after_stale_marker_is_removed,
        ) as sleep_mock,
    ):
        wait_for_dependencies(
            ["foo"],
            str(waiter_dir),
            "cl",
            "20260513120000",
            {"pid": 123},
            project_name="proj",
            wait_identity_deps=[
                {
                    "project_name": "proj",
                    "timestamp": "20260506010101",
                    "name": "foo",
                }
            ],
        )

    sleep_mock.assert_called_once_with(2)
    assert not (waiter_dir / "waiting.json").exists()
    assert not (waiter_dir / "ready.json").exists()


def test_failed_identity_dependency_waits_until_waiter_is_killed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="killed",
    )
    waiter_dir = _make_waiter(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    killed = False

    def was_killed() -> bool:
        return killed

    def kill_waiter_after_one_poll(_seconds: float) -> None:
        nonlocal killed
        assert (waiter_dir / "waiting.json").exists()
        assert not (waiter_dir / "ready.json").exists()
        killed = True

    with (
        patch("sase.axe.run_agent_wait.was_killed", side_effect=was_killed),
        patch(
            "sase.axe.run_agent_wait.time.sleep",
            side_effect=kill_waiter_after_one_poll,
        ) as sleep_mock,
        pytest.raises(SystemExit) as exc_info,
    ):
        wait_for_dependencies(
            ["foo"],
            str(waiter_dir),
            "cl",
            "20260513120000",
            {"pid": 123},
            project_name="proj",
            wait_identity_deps=[
                {
                    "project_name": "proj",
                    "timestamp": parent_dir.name,
                    "artifact_dir": str(parent_dir),
                    "name": "foo",
                }
            ],
        )

    assert exc_info.value.code == 143
    sleep_mock.assert_called_once_with(2)
    assert not (waiter_dir / "waiting.json").exists()


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
    waiter_dir = _make_waiter(tmp_path)
    (waiter_dir / "ready.json").write_text("{}", encoding="utf-8")
    index_updates: list[str] = []
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        _patch_index_updates(lambda path: index_updates.append(path)),
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


def test_successful_wait_records_completion_before_cleanup(tmp_path: Path) -> None:
    """wait_completed_at is durable before waiting.json is removed."""
    meta_path = tmp_path / "agent_meta.json"
    meta_path.write_text(json.dumps({"pid": 123}), encoding="utf-8")
    original_unlink = os.unlink
    saw_waiting_unlink = False

    def unlink(path: str) -> None:
        nonlocal saw_waiting_unlink
        if Path(path).name == "waiting.json":
            saw_waiting_unlink = True
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            assert isinstance(data.get("wait_completed_at"), str)
            assert data["wait_completed_at"]
        original_unlink(path)

    agent_meta = {"pid": 123}
    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch("sase.axe.run_agent_wait.os.unlink", side_effect=unlink),
    ):
        wait_for_dependencies(
            [],
            str(tmp_path),
            "cl",
            "20260513120000",
            agent_meta,
            duration=0,
        )

    assert saw_waiting_unlink is True
    assert isinstance(agent_meta.get("wait_completed_at"), str)
    assert not (tmp_path / "waiting.json").exists()


def test_completed_wait_is_idempotent_on_refreshed_pass(tmp_path: Path) -> None:
    """A refreshed pass keeps the first timestamp and writes no wait marker."""
    meta_path = tmp_path / "agent_meta.json"
    meta_path.write_text(json.dumps({"pid": 123}), encoding="utf-8")
    first_meta = {"pid": 123}

    with patch("sase.axe.run_agent_wait.was_killed", return_value=False):
        wait_for_dependencies(
            [],
            str(tmp_path),
            "cl",
            "20260513120000",
            first_meta,
            duration=0,
        )

    first_timestamp = first_meta["wait_completed_at"]
    refreshed_meta = {"pid": 123}
    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch("sase.axe.run_agent_wait.write_waiting_marker") as write_waiting,
        patch("sase.axe.run_agent_wait.time.sleep") as sleep_mock,
    ):
        blocked = wait_for_dependencies(
            ["dependency"],
            str(tmp_path),
            "cl",
            "20260513120000",
            refreshed_meta,
            duration=60,
        )

    assert blocked is False
    assert refreshed_meta["wait_completed_at"] == first_timestamp
    assert json.loads(meta_path.read_text())["wait_completed_at"] == first_timestamp
    write_waiting.assert_not_called()
    sleep_mock.assert_not_called()
    assert not (tmp_path / "waiting.json").exists()


def test_dependency_wait_updates_index_for_waiting_marker_only(
    tmp_path: Path,
) -> None:
    """waiting.json write/removal refreshes; ready.json removal does not."""
    (tmp_path / "agent_meta.json").write_text(json.dumps({"pid": 123}))
    (tmp_path / "ready.json").write_text("{}")
    calls: list[str] = []

    def write_agent_meta(artifacts_dir: str, agent_meta: dict) -> None:
        (Path(artifacts_dir) / "agent_meta.json").write_text(json.dumps(agent_meta))

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch("sase.axe.run_agent_wait_markers.write_agent_meta", write_agent_meta),
        _patch_index_updates(lambda path: calls.append(path)),
    ):
        wait_for_dependencies(
            ["dep"],
            str(tmp_path),
            "cl",
            "20260513120000",
            {"pid": 123},
        )

    assert calls == [str(tmp_path), str(tmp_path)]
    assert not (tmp_path / "waiting.json").exists()
    assert not (tmp_path / "ready.json").exists()


def test_named_duration_wait_starts_after_dependencies_are_ready(
    tmp_path: Path,
) -> None:
    """A relative duration is not consumed by time spent waiting on deps."""
    (tmp_path / "agent_meta.json").write_text(json.dumps({"pid": 123}))
    ready_path = tmp_path / "ready.json"
    sleep_calls: list[float] = []
    marker_snapshots: list[dict[str, object]] = []

    def update_index(artifacts_dir: str) -> None:
        waiting_path = Path(artifacts_dir) / "waiting.json"
        if waiting_path.exists():
            marker_snapshots.append(json.loads(waiting_path.read_text()))

    def sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        if len(sleep_calls) == 2:
            ready_path.write_text("{}", encoding="utf-8")

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        _patch_index_updates(update_index),
        patch("sase.axe.run_agent_wait.time.sleep", side_effect=sleep),
        patch(
            "sase.axe.run_agent_wait.remaining_until",
            side_effect=[3.0, 1.0, 0.0],
        ),
    ):
        wait_for_dependencies(
            ["dep"],
            str(tmp_path),
            "cl",
            "20260513120000",
            {"pid": 123},
            duration=3,
        )

    assert sleep_calls == [2, 2, 2, 1]
    assert len(marker_snapshots) == 2
    assert marker_snapshots[0]["waiting_for"] == ["dep"]
    assert marker_snapshots[0]["wait_duration"] == 3
    assert "wait_until" not in marker_snapshots[0]
    assert marker_snapshots[1]["wait_duration"] == 3
    assert isinstance(marker_snapshots[1].get("wait_until"), str)
    assert not (tmp_path / "waiting.json").exists()
    assert not ready_path.exists()


def test_killed_wait_does_not_record_completion(tmp_path: Path) -> None:
    """A kill during the wait does not mark the wait as successfully crossed."""
    meta_path = tmp_path / "agent_meta.json"
    meta_path.write_text(json.dumps({"pid": 123}), encoding="utf-8")

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=True),
        pytest.raises(SystemExit) as exc_info,
    ):
        wait_for_dependencies(
            [],
            str(tmp_path),
            "cl",
            "20260513120000",
            {"pid": 123},
            duration=1,
        )

    assert exc_info.value.code == 143
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    assert "wait_completed_at" not in data
    assert not (tmp_path / "waiting.json").exists()


def test_killed_wait_updates_index_for_write_and_cleanup(tmp_path: Path) -> None:
    calls: list[str] = []

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=True),
        _patch_index_updates(lambda path: calls.append(path)),
        pytest.raises(SystemExit) as exc_info,
    ):
        wait_for_dependencies(
            [],
            str(tmp_path),
            "cl",
            "20260513120000",
            {"pid": 123},
            duration=1,
        )

    assert exc_info.value.code == 143
    assert calls == [str(tmp_path), str(tmp_path)]
    assert not (tmp_path / "waiting.json").exists()
