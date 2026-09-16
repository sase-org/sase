"""Settlement re-evaluation for the monitor-settles-before-starter race.

Reproduces the sase-11o.1 failure class: result-capture publish stamps
``needs_recovery`` because the starter has not yet written its
``continuation_node_id`` (see ``test_persist_monitor_result_*`` in
``tests/continuation/test_capture.py`` for the capture-path bounded wait).
These tests cover settlement's own one-shot re-evaluation, which catches a
starter that settles in the gap between capture and settlement.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.continuation_capture import persist_monitor_result
from sase.continuation_capture.monitor import _MISSING_STARTER_PARENT_ERROR
from sase.continuation_capture.rollout import MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1
from sase.monitor.followup import FollowupLaunchResult
from sase.monitor.output import OutputCapture
from sase.monitor.settlement import settle_claim_and_followup
from sase.running_field import WorkspaceClaim

from ._fixtures import make_starter_agent, write_project_file


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def _make_settlement_monitor(
    tmp_path: Path, starter: Path, *, monitor_state: str = "completed"
) -> str:
    write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-monitor", "acme", pid=os.getpid())],
    )
    return make_starter_agent(
        "proj",
        "20260916094222",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="abc123def456",
        monitor_command="true",
        monitor_cwd=str(tmp_path),
        monitor_reason="test",
        monitor_next_action="shared follow-up",
        monitor_state=monitor_state,
        monitor_starter_agent="acme",
        monitor_starter_artifacts_dir=str(starter),
        monitor_continuation_protocol=MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1,
        cl_name="acme",
        workspace_dir=str(tmp_path),
        workspace_num=3,
        shell_kind="proc",
    )


def _publish_blocked_capture(artifacts_dir: str, meta: dict[str, Any]) -> None:
    """Publish a monitor result while the starter has not settled yet."""
    with (
        patch("sase.core.continuation_facade.validate_monitor_result"),
        patch("sase.core.continuation_facade.validate_continuation_node"),
    ):
        persist_monitor_result(
            artifacts_dir=artifacts_dir,
            meta=meta,
            monitor_state=str(meta["monitor_state"]),
            exit_code=0,
            elapsed_seconds=1.0,
            stopped_at="2026-09-16T09:42:26Z",
            diagnostic_manifest=None,
            retained_log={"log_ref": "local:log", "complete": True},
            project_name="proj",
            update_meta=True,
        )


def test_settlement_recovers_when_starter_settles_before_settlement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.shells.followup.DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS", 0.05
    )
    monkeypatch.setattr("sase.shells.followup.STARTER_SETTLE_POLL_SECONDS", 0.01)

    starter = tmp_path / "starter"
    starter.mkdir()
    (starter / "agent_meta.json").write_text(
        json.dumps({"name": "acme"}), encoding="utf-8"
    )
    artifacts_dir = _make_settlement_monitor(tmp_path, starter)
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    _publish_blocked_capture(artifacts_dir, meta)
    assert meta["continuation_capture_disposition"] == "needs_recovery"

    # The starter settles in the gap between capture and settlement.
    (starter / "agent_meta.json").write_text(
        json.dumps({"name": "acme", "continuation_node_id": "agent-delta:acme:1"}),
        encoding="utf-8",
    )
    (starter / "done.json").write_text("{}", encoding="utf-8")

    launches: list[str | None] = []

    def fake_launch(
        _artifacts_dir: str, launch_meta: dict[str, Any], **_kwargs: object
    ) -> FollowupLaunchResult:
        launches.append(str(launch_meta.get("monitor_next_action") or "") or None)
        return FollowupLaunchResult(launched=True, agent_name="acme--1")

    result = settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=fake_launch,
    )

    assert launches == ["shared follow-up"]
    assert result.launch_result is not None
    assert result.launch_result.launched is True
    assert meta["continuation_capture_disposition"] == "ok"

    node_id = meta["continuation_monitor_result_node_id"]
    node_path = Path(artifacts_dir) / "continuation" / "nodes" / f"{node_id}.json"
    assert json.loads(node_path.read_text())["parent_ids"] == ["agent-delta:acme:1"]
    manifest_path = (
        Path(artifacts_dir) / "continuation" / "monitor_result_manifest.json"
    )
    assert json.loads(manifest_path.read_text())["parent_node_ids"] == [
        "agent-delta:acme:1"
    ]
    on_disk = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert on_disk["continuation_capture_disposition"] == "ok"


def test_settlement_still_not_launchable_when_starter_never_settles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserves today's behavior when the starter never settles at all."""
    monkeypatch.setattr(
        "sase.shells.followup.DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS", 0.05
    )
    monkeypatch.setattr("sase.shells.followup.STARTER_SETTLE_POLL_SECONDS", 0.01)

    starter = tmp_path / "starter"
    starter.mkdir()
    (starter / "agent_meta.json").write_text(
        json.dumps({"name": "acme"}), encoding="utf-8"
    )
    artifacts_dir = _make_settlement_monitor(tmp_path, starter)
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    _publish_blocked_capture(artifacts_dir, meta)
    assert meta["continuation_capture_disposition"] == "needs_recovery"

    def fake_launch(
        _artifacts_dir: str, _meta: dict[str, Any], **_kwargs: object
    ) -> FollowupLaunchResult:
        raise AssertionError("follow-up must not launch while blocked")

    result = settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=fake_launch,
    )

    assert result.launch_result is not None
    assert result.launch_result.launched is False
    assert result.launch_result.error == _MISSING_STARTER_PARENT_ERROR
    assert meta["monitor_followup_outcome"] == "not-launchable"


def test_settlement_bypasses_starter_parent_check_for_stopped_monitors(
    tmp_path: Path,
) -> None:
    """A stopped monitor's stale blocking disposition must not be touched.

    Stopped monitors never auto-dispatch a follow-up regardless of
    ``monitor_next_action`` (a user explicitly stopped it), so the only thing
    to regress here is the *check itself*: settlement must not run the
    blocked-reason/repair machinery at all for ``stopped``/``lost`` states
    (``_missing_essential_starter_parent`` already exempts them upstream).
    """
    starter = tmp_path / "starter"
    starter.mkdir()
    (starter / "agent_meta.json").write_text(
        json.dumps({"name": "acme"}), encoding="utf-8"
    )
    artifacts_dir = _make_settlement_monitor(tmp_path, starter, monitor_state="stopped")
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    meta["continuation_capture_disposition"] = "needs_recovery"
    meta["continuation_capture_error"] = _MISSING_STARTER_PARENT_ERROR

    launches: list[str | None] = []

    def fake_launch(
        _artifacts_dir: str, launch_meta: dict[str, Any], **_kwargs: object
    ) -> FollowupLaunchResult:
        launches.append(str(launch_meta.get("monitor_next_action") or "") or None)
        return FollowupLaunchResult(launched=True, agent_name="acme--1")

    settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state="stopped",
        exit_code=None,
        elapsed_seconds=1.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=fake_launch,
    )

    # Stopped monitors never dispatch, and the blocked-reason short-circuit
    # (which would stamp not-launchable with the starter-parent error) must
    # never have run: the stale disposition is left exactly as it was.
    assert launches == []
    assert meta.get("monitor_followup_outcome") != "not-launchable"
    assert meta["continuation_capture_disposition"] == "needs_recovery"
