"""Behavior tests for the ``sase monitor list`` handler."""

from __future__ import annotations

import json

import pytest

from tests.main.monitor_handler_helpers import (
    dispatch,
    make_monitor,
    monitor_home,
    patch_project_records,
)

__all__ = ["monitor_home"]


def test_list_shows_only_active_monitors_by_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A finished monitor is hidden unless ``-a/--all`` is passed."""
    running = make_monitor(
        "proj", "20260812120000", "acme--mon", lane="acme", monitor_id="aaabbbcccddd"
    )
    done = make_monitor(
        "proj",
        "20260812130000",
        "beta--mon",
        lane="beta",
        monitor_id="eeefffggghhh",
        monitor_state="completed",
        exit_code=0,
    )
    patch_project_records(monkeypatch, [running, done])

    assert dispatch(["monitor", "list"]) == 0

    out = capsys.readouterr().out
    assert "acme" in out
    assert "beta" not in out


def test_list_all_includes_finished_monitors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--all`` surfaces both running and terminal monitors."""
    running = make_monitor(
        "proj", "20260812120000", "acme--mon", lane="acme", monitor_id="aaabbbcccddd"
    )
    done = make_monitor(
        "proj",
        "20260812130000",
        "beta--mon",
        lane="beta",
        monitor_id="eeefffggghhh",
        monitor_state="failed",
        exit_code=1,
    )
    patch_project_records(monkeypatch, [running, done])

    assert dispatch(["monitor", "list", "--all"]) == 0

    out = capsys.readouterr().out
    assert "acme" in out
    assert "beta" in out


def test_list_filters_by_status_and_lane(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``-s`` and ``-l`` narrow the result independently of ``--all``."""
    failed = make_monitor(
        "proj",
        "20260812120000",
        "acme--mon",
        lane="acme",
        monitor_id="aaabbbcccddd",
        monitor_state="failed",
        exit_code=1,
    )
    timed_out = make_monitor(
        "proj",
        "20260812130000",
        "beta--mon",
        lane="beta",
        monitor_id="eeefffggghhh",
        monitor_state="timeout",
    )
    patch_project_records(monkeypatch, [failed, timed_out])

    assert dispatch(["monitor", "list", "-s", "failed"]) == 0
    out = capsys.readouterr().out
    assert "acme" in out and "beta" not in out

    assert dispatch(["monitor", "list", "--all", "-l", "beta"]) == 0
    out = capsys.readouterr().out
    assert "beta" in out and "acme" not in out


def test_list_limit_trims_the_newest_first_result(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``-n`` caps the row count after newest-first sorting."""
    older = make_monitor(
        "proj", "20260812120000", "acme--mon", lane="acme", monitor_id="aaabbbcccddd"
    )
    newer = make_monitor(
        "proj", "20260812130000", "beta--mon", lane="beta", monitor_id="eeefffggghhh"
    )
    patch_project_records(monkeypatch, [older, newer])

    assert dispatch(["monitor", "list", "-n", "1"]) == 0

    out = capsys.readouterr().out
    assert "beta" in out
    assert "acme" not in out


def test_list_empty_active_result_renders_the_all_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No active monitors gets a friendly panel naming ``-a/--all``."""
    done = make_monitor(
        "proj",
        "20260812120000",
        "acme--mon",
        lane="acme",
        monitor_id="aaabbbcccddd",
        monitor_state="completed",
        exit_code=0,
    )
    patch_project_records(monkeypatch, [done])

    assert dispatch(["monitor", "list"]) == 0

    out = capsys.readouterr().out
    assert "-a/--all" in out


def test_list_json_envelope_is_stable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The JSON envelope carries schema, scope, count, and monitor fields."""
    running = make_monitor(
        "proj",
        "20260812120000",
        "acme--mon",
        lane="acme",
        monitor_id="aaabbbcccddd",
        command="just check-full",
        reason="verify the fix",
    )
    patch_project_records(monkeypatch, [running])

    assert dispatch(["monitor", "list", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["count"] == 1
    assert payload["scope"] == {
        "all": False,
        "project": None,
        "lane": None,
        "status": None,
    }
    monitor = payload["monitors"][0]
    assert monitor["monitor_id"] == "aaabbbcccddd"
    assert monitor["short_id"] == "aaabbb"
    assert monitor["lane"] == "acme"
    assert monitor["member_agent_name"] == "acme--mon"
    assert monitor["command"] == "just check-full"
    assert monitor["reason"] == "verify the fix"
    assert monitor["monitor_state"] == "running"
    assert monitor["status_bucket"] == "Running"
    assert monitor["is_terminal"] is False


def test_list_flags_a_dropped_followup_in_table_and_markdown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A stalled lane (dropped ``--next``) is visible without ``--json``."""
    stalled = make_monitor(
        "proj",
        "20260812120000",
        "acme--mon",
        lane="acme",
        monitor_id="aaabbbcccddd",
        monitor_state="completed",
        exit_code=0,
        monitor_followup_error="workspace #10 with pid 3333672 was not found",
        monitor_followup_outcome="not-launchable",
    )
    patch_project_records(monkeypatch, [stalled])

    assert dispatch(["monitor", "list", "--all"]) == 0
    out = capsys.readouterr().out
    assert "⚑" in out

    assert dispatch(["monitor", "list", "--all", "--format", "markdown"]) == 0
    out = capsys.readouterr().out
    assert "⚑" in out


def test_list_json_envelope_carries_followup_disposition(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The JSON envelope surfaces the follow-up outcome/error without ``--all-lines``."""
    stalled = make_monitor(
        "proj",
        "20260812120000",
        "acme--mon",
        lane="acme",
        monitor_id="aaabbbcccddd",
        monitor_state="completed",
        exit_code=0,
        monitor_followup_error="workspace #10 with pid 3333672 was not found",
        monitor_followup_outcome="not-launchable",
    )
    patch_project_records(monkeypatch, [stalled])

    assert dispatch(["monitor", "list", "--all", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    monitor = payload["monitors"][0]
    assert monitor["followup_outcome"] == "not-launchable"
    assert monitor["followup_error"] == "workspace #10 with pid 3333672 was not found"


def test_list_flags_a_degraded_followup_in_table_and_markdown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A degraded launch sets no error, so the outcome alone must raise the flag."""
    degraded = make_monitor(
        "proj",
        "20260812120000",
        "acme--mon",
        lane="acme",
        monitor_id="aaabbbcccddd",
        monitor_state="completed",
        exit_code=0,
        monitor_followup_outcome="launched-degraded",
        monitor_followup_degraded_reason="relaunched against workspace 0",
    )
    patch_project_records(monkeypatch, [degraded])

    assert dispatch(["monitor", "list", "--all"]) == 0
    assert "⚑" in capsys.readouterr().out

    assert dispatch(["monitor", "list", "--all", "--format", "markdown"]) == 0
    assert "⚑" in capsys.readouterr().out


def test_list_does_not_flag_a_cleanly_launched_followup(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    launched = make_monitor(
        "proj",
        "20260812120000",
        "acme--mon",
        lane="acme",
        monitor_id="aaabbbcccddd",
        monitor_state="completed",
        exit_code=0,
        monitor_followup_outcome="launched",
    )
    patch_project_records(monkeypatch, [launched])

    assert dispatch(["monitor", "list", "--all"]) == 0
    assert "⚑" not in capsys.readouterr().out


def test_list_markdown_format_renders_a_pipe_table(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--format markdown`` renders a real markdown table, not a rich panel."""
    running = make_monitor(
        "proj", "20260812120000", "acme--mon", lane="acme", monitor_id="aaabbbcccddd"
    )
    patch_project_records(monkeypatch, [running])

    assert dispatch(["monitor", "list", "--format", "markdown"]) == 0

    out = capsys.readouterr().out
    assert out.startswith("| State | Id |")
    assert "| running |" in out
