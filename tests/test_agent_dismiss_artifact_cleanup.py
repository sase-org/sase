"""Tests for artifact cleanup performed while dismissing agents."""

from __future__ import annotations

import json
from unittest.mock import patch

from tests._agent_dismiss_helpers import make_agent


def test_dismiss_side_effects_delete_artifact_index_row(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Marker deletion also removes the stale SQLite index row best-effort."""
    from sase.ace.tui.actions.agents._dismiss_persistence import (
        persist_dismiss_side_effects,
    )

    agent = make_agent(
        raw_suffix="20240101120000",
        artifacts_dir=str(tmp_path / "artifacts"),
    )

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_bundle"),
        patch(
            "sase.ace.tui.actions.agents._dismiss_persistence."
            "delete_agent_artifact_index_artifacts"
        ) as mock_delete_index,
        patch(
            "sase.ace.tui.actions.agents._dismiss_persistence.delete_agent_artifacts"
        ) as mock_delete_artifacts,
    ):
        persist_dismiss_side_effects(agent, [agent])

    mock_delete_index.assert_called_once_with([str(tmp_path / "artifacts")])
    mock_delete_artifacts.assert_called_once_with(str(tmp_path / "artifacts"))


def test_dismiss_side_effects_register_expected_delete_before_artifact_cleanup(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    """Dismiss persistence can notify the watcher before deleting artifacts."""
    from sase.ace.tui.actions.agents._dismiss_persistence import (
        persist_dismiss_side_effects,
    )

    agent = make_agent(
        raw_suffix="20240101120000",
        artifacts_dir=str(tmp_path / "artifacts"),
    )
    registered: list[str | None] = []

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_bundle"),
        patch(
            "sase.ace.tui.actions.agents._dismiss_persistence."
            "delete_agent_artifact_index_artifacts"
        ),
        patch(
            "sase.ace.tui.actions.agents._dismiss_persistence.delete_agent_artifacts"
        ) as mock_delete_artifacts,
    ):
        persist_dismiss_side_effects(
            agent,
            [agent],
            register_expected_deletion=registered.append,
        )

    mock_delete_artifacts.assert_called_once_with(
        str(tmp_path / "artifacts"),
        before_delete=registered.append,
    )


def test_delete_agent_artifacts_deletes_artifact_index_row(  # type: ignore[no-untyped-def]
    tmp_path,
) -> None:
    """Shared marker cleanup deletes the stale SQLite index row itself."""
    from sase.ace.tui.actions.agents._killing_utils import delete_agent_artifacts

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    done_marker = artifacts_dir / "done.json"
    done_marker.write_text("{}", encoding="utf-8")

    with (
        patch(
            "sase.ace.tui.actions.agents._killing_utils."
            "delete_agent_artifact_index_artifacts"
        ) as mock_delete_index,
        patch(
            "sase.ace.tui.actions.agents._killing_utils.try_delete_agent_artifacts",
            return_value=False,
        ),
    ):
        delete_agent_artifacts(str(artifacts_dir))

    mock_delete_index.assert_called_once_with([str(artifacts_dir)])
    assert not done_marker.exists()


def test_delete_agent_artifacts_resolves_waiters_before_deleting_done_marker(  # type: ignore[no-untyped-def]
    tmp_path,
    monkeypatch,
) -> None:
    """Dismissing a completed dependency should not strand active waiters."""
    from sase.ace.tui.actions.agents._killing_utils import delete_agent_artifacts

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    parent_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/20260706130831"
    waiter_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/20260706131004"
    parent_dir.mkdir(parents=True)
    waiter_dir.mkdir(parents=True)
    (parent_dir / "agent_meta.json").write_text(
        json.dumps({"name": "b"}),
        encoding="utf-8",
    )
    (parent_dir / "done.json").write_text(
        json.dumps({"outcome": "completed"}),
        encoding="utf-8",
    )
    (waiter_dir / "agent_meta.json").write_text(
        json.dumps({"name": "b--launch"}),
        encoding="utf-8",
    )
    (waiter_dir / "waiting.json").write_text(
        json.dumps(
            {
                "waiting_for": ["b"],
                "wait_for_artifacts": [
                    {
                        "project_name": "proj",
                        "timestamp": parent_dir.name,
                        "artifact_dir": str(parent_dir),
                        "name": "b",
                    }
                ],
                "cl_name": "waiter-cl",
                "timestamp": waiter_dir.name,
            }
        ),
        encoding="utf-8",
    )

    with (
        patch(
            "sase.ace.tui.actions.agents._killing_utils."
            "delete_agent_artifact_index_artifacts"
        ) as mock_delete_index,
        patch(
            "sase.ace.tui.actions.agents._killing_utils.try_delete_agent_artifacts",
            return_value=False,
        ),
    ):
        delete_agent_artifacts(str(parent_dir))

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["b"]}
    mock_delete_index.assert_called_once_with([str(parent_dir)])
    assert not (parent_dir / "done.json").exists()


def test_delete_agent_artifacts_keeps_waiter_with_other_unresolved_dependency(  # type: ignore[no-untyped-def]
    tmp_path,
    monkeypatch,
) -> None:
    """Dismissing one completed dep must not unblock a multi-dep waiter early."""
    from sase.ace.tui.actions.agents._killing_utils import delete_agent_artifacts

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    parent_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/20260706130831"
    waiter_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/20260706131004"
    parent_dir.mkdir(parents=True)
    waiter_dir.mkdir(parents=True)
    (parent_dir / "agent_meta.json").write_text(
        json.dumps({"name": "b"}),
        encoding="utf-8",
    )
    (parent_dir / "done.json").write_text(
        json.dumps({"outcome": "completed"}),
        encoding="utf-8",
    )
    (waiter_dir / "agent_meta.json").write_text(
        json.dumps({"name": "multi-waiter"}),
        encoding="utf-8",
    )
    (waiter_dir / "waiting.json").write_text(
        json.dumps(
            {
                "waiting_for": ["b", "c"],
                "wait_for_artifacts": [
                    {
                        "project_name": "proj",
                        "timestamp": parent_dir.name,
                        "artifact_dir": str(parent_dir),
                        "name": "b",
                    }
                ],
                "cl_name": "waiter-cl",
                "timestamp": waiter_dir.name,
            }
        ),
        encoding="utf-8",
    )

    with (
        patch(
            "sase.ace.tui.actions.agents._killing_utils."
            "delete_agent_artifact_index_artifacts"
        ),
        patch(
            "sase.ace.tui.actions.agents._killing_utils.try_delete_agent_artifacts",
            return_value=False,
        ),
    ):
        delete_agent_artifacts(str(parent_dir))

    assert not (waiter_dir / "ready.json").exists()
    waiting = json.loads((waiter_dir / "waiting.json").read_text(encoding="utf-8"))
    assert waiting["resolved_deps"] == [
        "b",
        {
            "name": "b",
            "project_name": "proj",
            "timestamp": parent_dir.name,
            "artifact_dir": str(parent_dir),
        },
    ]
    assert not (parent_dir / "done.json").exists()

    c_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/20260706131105"
    c_dir.mkdir()
    (c_dir / "agent_meta.json").write_text(json.dumps({"name": "c"}), encoding="utf-8")
    (c_dir / "done.json").write_text(
        json.dumps({"outcome": "completed"}), encoding="utf-8"
    )
    from sase.core.wait_dependency_resolution import (
        build_wait_dependency_index,
        dependency_resolution_status,
    )

    index = build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )
    assert dependency_resolution_status(
        index,
        waiting["waiting_for"],
        waiting["wait_for_artifacts"],
        waiting["resolved_deps"],
        self_artifact_dir=waiter_dir,
    ).resolved


def test_delete_failed_dependency_leaves_waiter_untouched(  # type: ignore[no-untyped-def]
    tmp_path,
    monkeypatch,
) -> None:
    from sase.ace.tui.actions.agents._killing_utils import delete_agent_artifacts

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    parent_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/20260706130831"
    waiter_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/20260706131004"
    parent_dir.mkdir(parents=True)
    waiter_dir.mkdir(parents=True)
    (parent_dir / "agent_meta.json").write_text(
        json.dumps({"name": "b"}), encoding="utf-8"
    )
    (parent_dir / "done.json").write_text(
        json.dumps({"outcome": "killed"}), encoding="utf-8"
    )
    (waiter_dir / "agent_meta.json").write_text(
        json.dumps({"name": "b--launch"}), encoding="utf-8"
    )
    original_waiting = {
        "waiting_for": ["b"],
        "wait_for_artifacts": [
            {
                "project_name": "proj",
                "timestamp": parent_dir.name,
                "artifact_dir": str(parent_dir),
                "name": "b",
            }
        ],
        "cl_name": "waiter-cl",
        "timestamp": waiter_dir.name,
    }
    (waiter_dir / "waiting.json").write_text(
        json.dumps(original_waiting), encoding="utf-8"
    )

    with (
        patch(
            "sase.ace.tui.actions.agents._killing_utils."
            "delete_agent_artifact_index_artifacts"
        ),
        patch(
            "sase.ace.tui.actions.agents._killing_utils.try_delete_agent_artifacts",
            return_value=False,
        ),
    ):
        delete_agent_artifacts(str(parent_dir))

    assert not (waiter_dir / "ready.json").exists()
    assert json.loads((waiter_dir / "waiting.json").read_text()) == original_waiting


def test_bulk_dismiss_fallback_batches_artifact_index_deletes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Per-agent fallback should issue a *single* artifact-index delete call."""
    from sase.ace.tui.actions.agents._dismiss_persistence import (
        persist_bulk_dismiss_side_effects,
    )

    a1 = make_agent(
        cl_name="a",
        raw_suffix="20240101120000",
        artifacts_dir=str(tmp_path / "a1"),
    )
    a2 = make_agent(
        cl_name="b",
        raw_suffix="20240101130000",
        artifacts_dir=str(tmp_path / "a2"),
    )
    a3 = make_agent(
        cl_name="c",
        raw_suffix="20240101140000",
        artifacts_dir=str(tmp_path / "a3"),
    )

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_bundle"),
        patch(
            "sase.ace.tui.actions.agents._dismiss_persistence."
            "delete_agent_artifact_index_artifacts"
        ) as mock_delete_index,
        patch(
            "sase.ace.tui.actions.agents._dismiss_persistence.delete_agent_artifacts"
        ) as mock_delete_artifacts,
    ):
        persist_bulk_dismiss_side_effects([a1, a2, a3], [a1, a2, a3])

    mock_delete_index.assert_called_once()
    assert mock_delete_index.call_args[0][0] == [
        str(tmp_path / "a1"),
        str(tmp_path / "a2"),
        str(tmp_path / "a3"),
    ]
    assert mock_delete_artifacts.call_count == 3
