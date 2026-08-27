"""Behavior tests for the ``sase gate list`` handler."""

from __future__ import annotations

import json

import pytest

from tests.gate_shell._cli_fixtures import (
    dispatch,
    gate_shell_home,
    make_gate_shell,
    patch_gate_shell_project_records,
)

__all__ = ["gate_shell_home"]


def test_list_shows_only_pending_gate_shells_by_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A settled gate shell is hidden unless ``-a/--all`` is passed."""
    pending = make_gate_shell(
        "proj", "20260812120000", "acme--gate", lane="acme", gate_id="custom-1"
    )
    answered = make_gate_shell(
        "proj",
        "20260812130000",
        "beta--gate",
        lane="beta",
        gate_id="custom-2",
        gate_state="answered",
    )
    patch_gate_shell_project_records(monkeypatch, [pending, answered])

    assert dispatch(["gate", "list"]) == 0

    out = capsys.readouterr().out
    assert "acme" in out
    assert "beta" not in out


def test_list_all_includes_settled_gate_shells(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pending = make_gate_shell(
        "proj", "20260812120000", "acme--gate", lane="acme", gate_id="custom-1"
    )
    failed = make_gate_shell(
        "proj",
        "20260812130000",
        "beta--gate",
        lane="beta",
        gate_id="custom-2",
        gate_state="failed",
    )
    patch_gate_shell_project_records(monkeypatch, [pending, failed])

    assert dispatch(["gate", "list", "--all"]) == 0

    out = capsys.readouterr().out
    assert "acme" in out
    assert "beta" in out


def test_list_filters_by_state_and_agent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    failed = make_gate_shell(
        "proj",
        "20260812120000",
        "acme--gate",
        lane="acme",
        gate_id="custom-1",
        gate_state="failed",
    )
    timed_out = make_gate_shell(
        "proj",
        "20260812130000",
        "beta--gate",
        lane="beta",
        gate_id="custom-2",
        gate_state="timeout",
    )
    patch_gate_shell_project_records(monkeypatch, [failed, timed_out])

    assert dispatch(["gate", "list", "-s", "failed"]) == 0
    out = capsys.readouterr().out
    assert "acme" in out and "beta" not in out

    assert dispatch(["gate", "list", "--all", "-l", "beta"]) == 0
    out = capsys.readouterr().out
    assert "beta" in out and "acme" not in out


def test_list_surfaces_a_claim_holding_pending_gate_shell(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """R2: a pending, workspace-inheriting gate shell is flagged in the list."""
    holding = make_gate_shell(
        "proj",
        "20260812120000",
        "acme--gate",
        lane="acme",
        gate_id="custom-1",
        workspace_policy="inherit",
    )
    released = make_gate_shell(
        "proj",
        "20260812130000",
        "beta--gate",
        lane="beta",
        gate_id="custom-2",
        workspace_policy="release",
    )
    patch_gate_shell_project_records(monkeypatch, [holding, released])

    assert dispatch(["gate", "list", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    by_lane = {row["lane"]: row for row in payload["gate_shells"]}
    assert by_lane["acme"]["holds_workspace_claim"] is True
    assert by_lane["beta"]["holds_workspace_claim"] is False

    assert dispatch(["gate", "list"]) == 0
    out = capsys.readouterr().out
    # The table's CLAIM column may ellipsize a narrow test terminal's width.
    assert "workspa" in out


def test_list_empty_pending_result_renders_the_all_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answered = make_gate_shell(
        "proj",
        "20260812120000",
        "acme--gate",
        lane="acme",
        gate_id="custom-1",
        gate_state="answered",
    )
    patch_gate_shell_project_records(monkeypatch, [answered])

    assert dispatch(["gate", "list"]) == 0

    out = capsys.readouterr().out
    assert "-a/--all" in out


def test_list_json_envelope_is_stable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pending = make_gate_shell(
        "proj",
        "20260812120000",
        "acme--gate",
        lane="acme",
        gate_id="custom-1",
        reason="wait for cleanup",
        label="Reclaim disk space",
    )
    patch_gate_shell_project_records(monkeypatch, [pending])

    assert dispatch(["gate", "list", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["count"] == 1
    assert payload["scope"] == {
        "all": False,
        "project": None,
        "agent": None,
        "state": None,
    }
    gate_shell = payload["gate_shells"][0]
    assert gate_shell["gate_id"] == "custom-1"
    assert gate_shell["lane"] == "acme"
    assert gate_shell["member_agent_name"] == "acme--gate"
    assert gate_shell["reason"] == "wait for cleanup"
    assert gate_shell["label"] == "Reclaim disk space"
    assert gate_shell["gate_state"] == "pending"
    assert gate_shell["is_terminal"] is False


def test_list_markdown_format_renders_a_pipe_table(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pending = make_gate_shell(
        "proj", "20260812120000", "acme--gate", lane="acme", gate_id="custom-1"
    )
    patch_gate_shell_project_records(monkeypatch, [pending])

    assert dispatch(["gate", "list", "--format", "markdown"]) == 0

    out = capsys.readouterr().out
    assert out.startswith("| State | Id |")
