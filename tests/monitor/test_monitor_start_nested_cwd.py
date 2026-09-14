"""Monitor start workspace resolution for cwds nested inside a checkout.

Covers plan ``202609/monitor_nested_cwd_workspace_resolution.md``: a monitor
started from a directory nested inside a managed checkout -- such as an
external repo clone opened with ``sase repo open`` from a numbered
workspace -- must keep its workspace identity instead of degrading to
workspace #0.
"""

from __future__ import annotations

import json
import os
import signal
from pathlib import Path

import pytest

from sase.monitor.claims import MONITOR_WORKSPACE_CLAIM_WORKFLOW
from sase.monitor.start import StartMonitorRequest, start_monitor
from sase.running_field import WorkspaceClaim, get_claimed_workspaces

from ._fixtures import (
    make_starter_agent,
    patch_project_records,
    register_workspace_checkout,
    wait_for_done,
    write_project_file,
)


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def _stop_and_wait(record) -> None:  # noqa: ANN001
    try:
        if record.pid is not None:
            try:
                os.kill(record.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    finally:
        wait_for_done(record.artifacts_dir, timeout=10.0)


def test_cwd_nested_inside_lane_workspace_inherits_claim_and_records_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_WORKSPACE_ROOT", str(tmp_path / "managed"))
    primary = tmp_path / "primary"
    primary.mkdir()
    workspace_dir = register_workspace_checkout(primary, 10)
    nested_cwd = (
        Path(workspace_dir) / "sase" / "repos" / "external" / "gh" / "sase-core"
    )
    nested_cwd.mkdir(parents=True)
    project_file = write_project_file(
        "proj",
        workspace_dir=str(primary),
        running_claims=[WorkspaceClaim(10, "ace-run", "acme", pid=os.getpid())],
    )
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme",
        model="claude-sonnet-5",
        workspace_dir=workspace_dir,
        workspace_num=10,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])

    record = start_monitor(
        StartMonitorRequest(
            command="sleep 30",
            reason="verify nested cwd inherits lane workspace",
            timeout_seconds=30.0,
            cwd=str(nested_cwd),
            project_name="proj",
            start_status="MONITORING",
            stop_status="MONITORED",
            lane="acme",
        )
    )

    try:
        assert record.cwd == str(nested_cwd)
        meta = json.loads((Path(record.artifacts_dir) / "agent_meta.json").read_text())
        assert meta["workspace_num"] == 10
        assert meta["workspace_dir"] == workspace_dir

        claims = get_claimed_workspaces(project_file)
        assert len(claims) == 1
        assert claims[0].workspace_num == 10
        assert claims[0].pid == record.pid
        assert claims[0].workflow == MONITOR_WORKSPACE_CLAIM_WORKFLOW
        assert claims[0].cl_name == "acme"
    finally:
        _stop_and_wait(record)


def test_cwd_nested_inside_a_different_workspace_records_its_number_without_transfer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_WORKSPACE_ROOT", str(tmp_path / "managed"))
    primary = tmp_path / "primary"
    primary.mkdir()
    lane_workspace_dir = register_workspace_checkout(primary, 10)
    other_workspace_dir = register_workspace_checkout(primary, 20)
    nested_cwd = Path(other_workspace_dir) / "sase" / "repos" / "external" / "gh" / "x"
    nested_cwd.mkdir(parents=True)
    project_file = write_project_file(
        "proj",
        workspace_dir=str(primary),
        running_claims=[WorkspaceClaim(10, "ace-run", "acme", pid=os.getpid())],
    )
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme",
        model="claude-sonnet-5",
        workspace_dir=lane_workspace_dir,
        workspace_num=10,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])

    record = start_monitor(
        StartMonitorRequest(
            command="sleep 30",
            reason="verify nested cwd in a different workspace",
            timeout_seconds=30.0,
            cwd=str(nested_cwd),
            project_name="proj",
            start_status="MONITORING",
            stop_status="MONITORED",
            lane="acme",
        )
    )

    try:
        assert record.cwd == str(nested_cwd)
        meta = json.loads((Path(record.artifacts_dir) / "agent_meta.json").read_text())
        assert meta["workspace_num"] == 20
        assert meta["workspace_dir"] == other_workspace_dir

        claims = {
            claim.workspace_num: claim for claim in get_claimed_workspaces(project_file)
        }
        assert claims[10].pid == os.getpid()
        assert claims[10].workflow == "ace-run"
        assert claims[20].pid == record.pid
        assert claims[20].workflow == MONITOR_WORKSPACE_CLAIM_WORKFLOW
    finally:
        _stop_and_wait(record)


def test_unmanaged_cwd_still_degrades_to_workspace_zero_with_raw_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_WORKSPACE_ROOT", str(tmp_path / "managed"))
    primary = tmp_path / "primary"
    primary.mkdir()
    lane_workspace_dir = register_workspace_checkout(primary, 10)
    unmanaged_cwd = tmp_path / "unrelated"
    unmanaged_cwd.mkdir()
    write_project_file(
        "proj",
        workspace_dir=str(primary),
        running_claims=[WorkspaceClaim(10, "ace-run", "acme", pid=os.getpid())],
    )
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme",
        model="claude-sonnet-5",
        workspace_dir=lane_workspace_dir,
        workspace_num=10,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])

    record = start_monitor(
        StartMonitorRequest(
            command="sleep 30",
            reason="verify unmanaged cwd still degrades to workspace 0",
            timeout_seconds=30.0,
            cwd=str(unmanaged_cwd),
            project_name="proj",
            start_status="MONITORING",
            stop_status="MONITORED",
            lane="acme",
        )
    )

    try:
        meta = json.loads((Path(record.artifacts_dir) / "agent_meta.json").read_text())
        assert meta["workspace_num"] == 0
        assert meta["workspace_dir"] == str(unmanaged_cwd)
    finally:
        _stop_and_wait(record)
