"""Integration-style tests for the Phase 4 index-maintenance hooks.

Asserts the lifecycle, dismiss, and revive paths call the adapter
defined in :mod:`sase.core.agent_artifact_index_maintenance` with the
correct artifact directories. The adapter itself is unit-tested
separately; these tests verify the wiring at each touchpoint.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from sase.core import agent_artifact_index_maintenance as maintenance


def _reset_module_state() -> None:
    maintenance._last_upsert_time.clear()
    maintenance._last_dismissed_signature = maintenance._DISMISSED_SIGNATURE_UNSET


@pytest.fixture(autouse=True)
def _reset_state() -> Iterator[None]:
    _reset_module_state()
    yield
    _reset_module_state()


def _make_artifact_dir(tmp_path: Path) -> Path:
    artifact_dir = tmp_path / "proj" / "artifacts" / "ace-run" / "20260516120000"
    artifact_dir.mkdir(parents=True)
    return artifact_dir


def test_record_run_started_at_triggers_index_upsert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.axe import run_agent_markers

    artifact_dir = _make_artifact_dir(tmp_path)

    upsert_calls: list[str] = []

    def fake_upsert(artifact_dir_arg: str, *args: Any, **kwargs: Any) -> bool:
        upsert_calls.append(str(artifact_dir_arg))
        return True

    monkeypatch.setattr(
        maintenance,
        "upsert_artifact_dir",
        fake_upsert,
    )

    agent_meta: dict[str, Any] = {}
    run_agent_markers.record_run_started_at(str(artifact_dir), agent_meta)

    assert str(artifact_dir) in upsert_calls


def test_record_stop_time_triggers_index_upsert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.axe import run_agent_markers

    artifact_dir = _make_artifact_dir(tmp_path)
    (artifact_dir / "agent_meta.json").write_text("{}")

    upsert_calls: list[str] = []
    monkeypatch.setattr(
        maintenance,
        "upsert_artifact_dir",
        lambda artifact_dir_arg, *a, **k: (
            upsert_calls.append(str(artifact_dir_arg)) or True
        ),
    )

    run_agent_markers.record_stop_time(str(artifact_dir))

    assert str(artifact_dir) in upsert_calls


def test_waiting_marker_writes_trigger_index_upsert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each ``waiting.json`` write path in run_agent_wait upserts the dir."""
    from sase.axe import run_agent_wait

    artifact_dir = _make_artifact_dir(tmp_path)

    upsert_calls: list[str] = []
    monkeypatch.setattr(
        maintenance,
        "upsert_artifact_dir",
        lambda artifact_dir_arg, *a, **k: (
            upsert_calls.append(str(artifact_dir_arg)) or True
        ),
    )
    # Sidestep the actual sleep/poll loop by faking ``was_killed`` true so the
    # wait helper returns straight after writing the marker.
    monkeypatch.setattr(run_agent_wait, "was_killed", lambda: True)

    with pytest.raises(SystemExit):
        run_agent_wait.wait_for_dependencies(
            [],
            str(artifact_dir),
            "cl",
            "20260516120000",
            {},
            duration=1.0,
        )

    assert str(artifact_dir) in upsert_calls


def test_running_marker_write_triggers_index_upsert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.axe import run_agent_runner_setup

    artifact_dir = _make_artifact_dir(tmp_path)

    upsert_calls: list[str] = []
    monkeypatch.setattr(
        maintenance,
        "upsert_artifact_dir",
        lambda artifact_dir_arg, *a, **k: (
            upsert_calls.append(str(artifact_dir_arg)) or True
        ),
    )

    run_agent_runner_setup.write_home_running_marker(
        artifacts_dir=str(artifact_dir),
        cl_name="cl",
        timestamp="20260516120000",
        prompt="p",
        agent_model="m",
        agent_llm_provider="anthropic",
        agent_vcs_provider=None,
        workspace_dir=str(tmp_path / "workspace"),
    )

    assert str(artifact_dir) in upsert_calls


def test_workflow_state_write_triggers_index_upsert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.xprompt.workflow_executor import WorkflowExecutor
    from sase.xprompt.workflow_models import Workflow

    artifact_dir = _make_artifact_dir(tmp_path)
    upsert_calls: list[str] = []
    monkeypatch.setattr(
        maintenance,
        "upsert_artifact_dir",
        lambda artifact_dir_arg, *a, **k: (
            upsert_calls.append(str(artifact_dir_arg)) or True
        ),
    )

    executor = WorkflowExecutor(
        workflow=Workflow(name="wf", steps=[]),
        args={},
        artifacts_dir=str(artifact_dir),
    )
    executor._save_state()

    assert str(artifact_dir) in upsert_calls


def test_prompt_step_marker_write_triggers_index_upsert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.xprompt.workflow_executor import WorkflowExecutor
    from sase.xprompt.workflow_models import StepState, StepStatus, Workflow

    artifact_dir = _make_artifact_dir(tmp_path)
    upsert_calls: list[str] = []
    monkeypatch.setattr(
        maintenance,
        "upsert_artifact_dir",
        lambda artifact_dir_arg, *a, **k: (
            upsert_calls.append(str(artifact_dir_arg)) or True
        ),
    )

    executor = WorkflowExecutor(
        workflow=Workflow(name="wf", steps=[]),
        args={},
        artifacts_dir=str(artifact_dir),
    )
    executor._save_prompt_step_marker(
        "step",
        StepState(name="step", status=StepStatus.COMPLETED),
    )

    assert str(artifact_dir) in upsert_calls


def test_runner_utils_meta_and_done_writes_trigger_index_upsert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.axe.runner_utils import write_agent_meta, write_done_marker

    artifact_dir = _make_artifact_dir(tmp_path)
    upsert_calls: list[str] = []
    monkeypatch.setattr(
        maintenance,
        "upsert_artifact_dir",
        lambda artifact_dir_arg, *a, **k: (
            upsert_calls.append(str(artifact_dir_arg)) or True
        ),
    )

    write_agent_meta(str(artifact_dir), model="m")
    write_done_marker(
        str(artifact_dir),
        cl_name="cl",
        project_file="/tmp/project.sase",
        timestamp="260516_120000",
        exit_code=0,
    )

    assert upsert_calls.count(str(artifact_dir)) == 2


def test_delete_agent_artifacts_triggers_index_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.ace.tui.actions.agents import _killing_utils

    artifact_dir = _make_artifact_dir(tmp_path)
    (artifact_dir / "done.json").write_text("{}")

    delete_calls: list[str] = []
    monkeypatch.setattr(
        maintenance,
        "delete_artifact_dir",
        lambda artifact_dir_arg, *a, **k: (
            delete_calls.append(str(artifact_dir_arg)) or True
        ),
    )

    _killing_utils.delete_agent_artifacts(str(artifact_dir))

    assert str(artifact_dir) in delete_calls


def test_dismiss_persistence_syncs_dismissed_visibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The single-agent dismiss persistence transaction syncs the sidecar."""
    from sase.ace.tui.actions.agents._dismissing import (
        _persist_single_dismiss_transaction,
    )

    sync_calls: list[Any] = []
    monkeypatch.setattr(
        maintenance,
        "sync_dismissed_visibility",
        lambda dismissed, *a, **k: sync_calls.append(set(dismissed)) or True,
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.save_dismissed_agents",
        lambda dismissed: True,
    )

    class _FakeAgent:
        cl_name = "cl"
        raw_suffix = "20260516120000"
        agent_type = type("AT", (), {"value": "running"})()
        is_workflow_child = False
        _from_changespec = True
        artifacts_dir = None
        agent_name = ""
        identity = ("running", "cl", "20260516120000")

        def get_artifacts_dir(self) -> str:
            return ""

    dismissed_snapshot = {("running", "cl", "20260516120000")}
    _persist_single_dismiss_transaction(
        _FakeAgent(),  # type: ignore[arg-type]
        dismissed_snapshot,  # type: ignore[arg-type]
        [],
        cleanup_plan=None,
    )

    assert sync_calls == [dismissed_snapshot]


def test_inbox_loader_calls_maybe_sync_dismissed_from_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Tier 1 loader pre-syncs dismissed visibility before each query."""
    from sase.ace.tui.models import agent_loader
    from sase.core.agent_scan_facade import default_agent_artifact_index_path
    from sase.core.agent_scan_wire import (
        AGENT_SCAN_WIRE_SCHEMA_VERSION,
        AgentArtifactScanOptionsWire,
        AgentArtifactScanStatsWire,
        AgentArtifactScanWire,
    )

    # Use a real-ish home with a present sqlite file so the missing-index branch
    # is skipped and we exercise the sync hook.
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    sase_dir = fake_home / ".sase"
    sase_dir.mkdir()
    (sase_dir / "agent_artifact_index.sqlite").write_bytes(b"placeholder")

    assert (
        default_agent_artifact_index_path() == sase_dir / "agent_artifact_index.sqlite"
    )

    sync_called: list[Any] = []
    monkeypatch.setattr(
        maintenance,
        "maybe_sync_dismissed_from_file",
        lambda **kwargs: sync_called.append(kwargs) or True,
    )

    def fake_query(index_path, projects_root, query=None, options=None):  # type: ignore[no-untyped-def]
        return AgentArtifactScanWire(
            schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
            projects_root=str(projects_root),
            options=options or AgentArtifactScanOptionsWire(),
            stats=AgentArtifactScanStatsWire(),
            records=[],
        )

    monkeypatch.setattr(agent_loader, "query_agent_artifact_index", fake_query)

    result = agent_loader._query_artifact_index_for_loader(
        full_history=False, agent_search_active=False
    )

    assert result is not None
    assert sync_called, "loader should invoke maybe_sync_dismissed_from_file"
