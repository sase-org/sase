"""Tests for monitor discovery and listing in :mod:`sase.monitor.store`."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.monitor.models import MonitorLaneError
from sase.monitor.store import (
    active_monitor_for_lane,
    default_caller,
    default_lane,
    durable_lane_for_record,
    get_monitor,
    has_any_monitor,
    list_monitors,
    read_monitor_marker,
    resolve_exact_agent,
    resolve_lane,
)

from ._fixtures import make_starter_agent, patch_project_records


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


def test_default_caller_returns_exact_sase_agent_name() -> None:
    assert default_caller({"SASE_AGENT_NAME": "sase-m6.6.1.5"}) == "sase-m6.6.1.5"
    assert default_caller({"SASE_AGENT_NAME": "02i--code"}) == "02i--code"
    assert default_caller({}) is None


def test_default_lane_still_collapses_family_and_legacy_suffixes() -> None:
    assert default_lane({"SASE_AGENT_NAME": "sase-m6.6.1.5"}) == "sase-m6.6.1"
    assert default_lane({"SASE_AGENT_NAME": "02i--code"}) == "02i"
    assert default_lane({}) is None


def test_resolve_lane_picks_the_newest_family_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    older = make_starter_agent("proj", "20260812120000", "acme--0", agent_family="acme")
    newer = make_starter_agent(
        "proj", "20260812130000", "acme--mon", agent_family="acme"
    )
    patch_project_records(monkeypatch, [older, newer])

    ctx = resolve_lane("proj", "acme")

    assert ctx.record.artifact_dir == newer


def test_resolve_exact_agent_ignores_newer_sibling_and_family_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller = make_starter_agent(
        "proj",
        "20260812120000",
        "sase-m6.6.1.5",
        workspace_num=12,
        workspace_dir="/work/12",
    )
    sibling = make_starter_agent(
        "proj",
        "20260812125000",
        "sase-m6.6.1",
        workspace_num=7,
        workspace_dir="/work/7",
    )
    land = make_starter_agent(
        "proj",
        "20260812130000",
        "sase-m6.10",
        workspace_num=0,
        workspace_dir="/work/primary",
    )
    family_member = make_starter_agent(
        "proj",
        "20260812120500",
        "02i--code",
        agent_family="02i",
        workspace_num=12,
        workspace_dir="/work/12",
    )
    settled_monitor = make_starter_agent(
        "proj",
        "20260812140000",
        "02i--mon-6",
        agent_family="02i",
        agent_family_role="monitor",
        monitor_id="oldmon",
        monitor_state="completed",
        monitor_settled=True,
        workspace_num=0,
        workspace_dir="/work/primary",
    )
    patch_project_records(
        monkeypatch, [caller, sibling, land, family_member, settled_monitor]
    )

    phase = resolve_exact_agent("proj", "sase-m6.6.1.5")
    member = resolve_exact_agent("proj", "02i--code")
    collapsed_phase = resolve_lane("proj", "sase-m6.6.1")
    family_lane = resolve_lane("proj", "02i")

    assert phase.record.artifact_dir == caller
    assert member.record.artifact_dir == family_member
    assert collapsed_phase.record.artifact_dir == sibling
    assert family_lane.record.artifact_dir == settled_monitor


def test_durable_lane_for_record_prefers_agent_family_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bare = make_starter_agent("proj", "20260812120000", "sase-m6.6.1.5")
    member = make_starter_agent(
        "proj", "20260812121000", "02i--code", agent_family="02i"
    )
    patch_project_records(monkeypatch, [bare, member])

    bare_record = resolve_exact_agent("proj", "sase-m6.6.1.5").record
    member_record = resolve_exact_agent("proj", "02i--code").record

    assert durable_lane_for_record(bare_record, fallback="sase-m6.6.1.5") == (
        "sase-m6.6.1.5"
    )
    assert durable_lane_for_record(member_record, fallback="02i--code") == "02i"


def test_resolve_lane_raises_when_lane_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_project_records(monkeypatch, [])

    with pytest.raises(MonitorLaneError):
        resolve_lane("proj", "ghost")


def test_active_monitor_for_lane_ignores_other_lanes_and_terminal_monitors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running_other_lane = make_starter_agent(
        "proj",
        "20260812120000",
        "other--mon",
        agent_family="other",
        agent_family_role="monitor",
        monitor_id="aaa",
        monitor_state="running",
    )
    terminal_same_lane = make_starter_agent(
        "proj",
        "20260812121000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="bbb",
        monitor_state="completed",
        monitor_settled=True,
    )
    running_same_lane = make_starter_agent(
        "proj",
        "20260812122000",
        "acme--mon-0",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="ccc",
        monitor_state="running",
        monitor_command="sleep 60",
        pid=os.getpid(),
    )
    patch_project_records(
        monkeypatch, [running_other_lane, terminal_same_lane, running_same_lane]
    )

    found = active_monitor_for_lane("proj", "acme")

    assert found is not None
    assert found.artifact_dir == running_same_lane


def test_active_monitor_for_lane_keeps_unsettled_terminal_meta_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsettled_same_lane = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="aaa",
        monitor_state="completed",
        monitor_settled=False,
    )
    patch_project_records(monkeypatch, [unsettled_same_lane])

    found = active_monitor_for_lane("proj", "acme")

    assert found is not None
    assert found.artifact_dir == unsettled_same_lane


def test_has_any_monitor_is_true_once_any_monitor_member_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_project_records(monkeypatch, [])
    assert has_any_monitor("proj", "acme") is False

    monitor_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="aaa",
        monitor_state="completed",
    )
    patch_project_records(monkeypatch, [monitor_dir])
    assert has_any_monitor("proj", "acme") is True


def test_get_monitor_returns_none_for_an_unknown_artifacts_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_project_records(monkeypatch, [])
    assert get_monitor("proj", "/nowhere") is None


def test_read_monitor_marker_returns_none_for_a_missing_artifacts_dir(
    tmp_path: Path,
) -> None:
    assert read_monitor_marker("proj", str(tmp_path / "nowhere")) is None


def test_read_monitor_marker_does_not_query_the_artifact_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="aaa",
        monitor_state="running",
        monitor_command="sleep 60",
        monitor_stop_status="MONITORED",
    )

    def _fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("read_monitor_marker must not query the artifact index")

    monkeypatch.setattr("sase.monitor.store._project_records", _fail)

    record = read_monitor_marker("proj", monitor_dir)

    assert record is not None
    assert record.monitor_id == "aaa"
    assert record.monitor_state == "running"
    assert record.command == "sleep 60"


def test_read_monitor_marker_reflects_a_settled_done_marker() -> None:
    monitor_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="aaa",
        monitor_state="completed",
        monitor_settled=True,
        monitor_command="true",
    )
    done_path = Path(monitor_dir) / "done.json"
    done_path.write_text(
        json.dumps({"outcome": "monitored", "monitor_state": "completed"}),
        encoding="utf-8",
    )

    record = read_monitor_marker("proj", monitor_dir)

    assert record is not None
    assert record.monitor_state == "completed"
    assert record.is_terminal is True


def test_list_monitors_defaults_to_every_project_newest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    older = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="aaa",
        monitor_state="running",
    )
    newer = make_starter_agent(
        "other",
        "20260812130000",
        "beta--mon",
        agent_family="beta",
        agent_family_role="monitor",
        monitor_id="bbb",
        monitor_state="completed",
    )
    patch_project_records(monkeypatch, [older, newer])

    records = list_monitors()

    assert [record.monitor_id for record in records] == ["bbb", "aaa"]


def test_list_monitors_scopes_to_one_project(monkeypatch: pytest.MonkeyPatch) -> None:
    in_scope = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="aaa",
        monitor_state="running",
    )
    out_of_scope = make_starter_agent(
        "other",
        "20260812130000",
        "beta--mon",
        agent_family="beta",
        agent_family_role="monitor",
        monitor_id="bbb",
        monitor_state="running",
    )
    patch_project_records(monkeypatch, [in_scope, out_of_scope])

    records = list_monitors(project="proj")

    assert [record.monitor_id for record in records] == ["aaa"]
