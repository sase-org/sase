"""CLI start validation for versioned monitor outcome policies."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.main.monitor_handler_helpers import dispatch, monitor_home

__all__ = ["monitor_home"]


def _none_policy(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "completed": {"action": "none"},
        "failed": {"action": "continue", "next_action": "repair the failure"},
        "timeout": {"action": "none"},
    }
    payload.update(overrides)
    return payload


def test_start_rejects_simultaneous_profile_and_policy(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    policy = tmp_path / "policy.json"
    policy.write_text("{}", encoding="utf-8")
    assert (
        dispatch(
            [
                "monitor",
                "start",
                "-c",
                "true",
                "-p",
                "verify",
                "-P",
                str(policy),
            ]
        )
        == 2
    )
    assert "mutually exclusive" in capsys.readouterr().err


def test_start_rejects_invalid_json_and_yaml_policy_shapes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invalid_json = tmp_path / "policy.json"
    invalid_json.write_text("{not json", encoding="utf-8")
    assert (
        dispatch(
            [
                "monitor",
                "start",
                "-c",
                "true",
                "-s",
                "TESTING",
                "-S",
                "TESTED",
                "-P",
                str(invalid_json),
            ]
        )
        == 2
    )
    assert "not JSON or YAML" in capsys.readouterr().err

    not_object = tmp_path / "list.yaml"
    not_object.write_text("- just a list\n", encoding="utf-8")
    assert (
        dispatch(
            [
                "monitor",
                "start",
                "-c",
                "true",
                "-s",
                "TESTING",
                "-S",
                "TESTED",
                "-P",
                str(not_object),
            ]
        )
        == 2
    )
    assert "JSON/YAML object" in capsys.readouterr().err


def test_start_rejects_incomplete_policy_before_start_monitor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        "sase.main.monitor_handler.start_monitor",
        lambda request: calls.append(request),
    )
    policy = tmp_path / "policy.yaml"
    policy.write_text("completed:\n  action: continue\n", encoding="utf-8")
    assert (
        dispatch(
            [
                "monitor",
                "start",
                "-c",
                "true",
                "-a",
                "acme",
                "-s",
                "TESTING",
                "-S",
                "TESTED",
                "-P",
                str(policy),
            ]
        )
        == 2
    )
    err = capsys.readouterr().err
    assert "not a valid outcome policy" in err
    assert calls == []


def test_start_loads_yaml_policy_before_calling_start_monitor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[Any] = []

    class _Record:
        monitor_id = "abc123def456"
        member_agent_name = "acme--mon"
        artifacts_dir = str(tmp_path)

    monkeypatch.setattr(
        "sase.main.monitor_handler.start_monitor",
        lambda request: captured.append(request) or _Record(),
    )
    monkeypatch.setattr(
        "sase.main.monitor_handler.will_handoff_monitor_to_agent_runner",
        lambda: False,
    )
    monkeypatch.setattr(
        "sase.main.monitor_handler.maybe_handoff_monitor_from_agent",
        lambda _record: None,
    )
    monkeypatch.setattr(
        "sase.main.monitor_handler._infer_project_name",
        lambda _cwd: "proj",
    )
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        "completed:\n  action: none\n"
        "failed:\n  action: continue\n  next_action: repair the failure\n"
        "  model: opus@high\n"
        "timeout:\n  action: none\n",
        encoding="utf-8",
    )

    assert (
        dispatch(
            [
                "monitor",
                "start",
                "-c",
                "true",
                "-a",
                "acme",
                "-s",
                "TESTING",
                "-S",
                "TESTED",
                "-n",
                "shared follow-up",
                "-o",
                "none",
                "-P",
                str(policy),
            ]
        )
        == 0
    )
    assert len(captured) == 1
    request = captured[0]
    assert request.next_action == "shared follow-up"
    assert request.cli_evidence == "none"
    assert request.outcome_policy is not None
    assert request.outcome_policy["completed"]["action"] == "none"
    assert request.outcome_policy["failed"]["next_action"] == "repair the failure"


def test_start_allows_model_without_next_when_profile_selects_continuation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        dispatch(
            [
                "monitor",
                "start",
                "-c",
                "true",
                "-p",
                "verify",
                "-m",
                "@small",
            ]
        )
        == 2
    )
    err = capsys.readouterr().err
    assert "-m/--model requires -n/--next" not in err
    assert "SASE_AGENT_NAME is unset" in err
