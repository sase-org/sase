"""Tests for ``sase agent hold`` CLI subcommand handlers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.agents import cli_hold
from sase.core.agent_hold_facade import (
    AgentHoldArmResult,
    list_current_agent_holds,
)

from tests._runner_slot_fixtures import artifact as make_artifact


def _create_args(**overrides: object) -> argparse.Namespace:
    base = {
        "names": [],
        "tribes": [],
        "hoods": [],
        "future": False,
        "pending": False,
        "scope": "project",
        "ttl": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _run_args(**overrides: object) -> argparse.Namespace:
    base = {
        "names": [],
        "tribes": [],
        "hoods": [],
        "future": False,
        "pending": False,
        "scope": "project",
        "ttl": None,
        "hold_run_command_words": [],
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def test_create_requires_at_least_one_selector_flag(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli_hold._handle_create(_create_args()) == 2
    assert "at least one of -n/-t/-H/-f/-p" in capsys.readouterr().err


def test_create_rejects_ttl_above_configured_maximum(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli_hold._handle_create(_create_args(future=True, ttl="999h"))
    assert exit_code == 2
    assert "exceeds the configured maximum" in capsys.readouterr().err


def test_create_rejects_a_kin_selector_naming_the_armers_own_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifacts_dir = make_artifact(tmp_path, "20260910150000", 4242)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"pid": 4242, "name": "worker.a--code"})
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    exit_code = cli_hold._handle_create(_create_args(names=["worker.a--code"]))

    assert exit_code == 1
    assert "sase agent hold create:" in capsys.readouterr().err


def test_create_arms_a_hold_end_to_end(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sase.core.agent_hold_facade._project_for_cwd", lambda: "scratch"
    )
    exit_code = cli_hold._handle_create(_create_args(future=True, scope="host"))
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Armed hold" in out

    holds = list_current_agent_holds()
    assert len(holds) == 1
    assert holds[0]["selectors"]["future"] is True


def test_list_json_outputs_current_holds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sase.core.agent_hold_facade._project_for_cwd", lambda: "scratch"
    )
    cli_hold._handle_create(_create_args(future=True, scope="host"))
    capsys.readouterr()

    exit_code = cli_hold._handle_list(argparse.Namespace(json=True))
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["selectors"]["future"] is True


def test_show_unknown_key_exits_with_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli_hold._handle_show(argparse.Namespace(key="nope", json=False))
    assert exit_code == 2
    assert "no active hold for nope" in capsys.readouterr().err


def test_show_json_outputs_raw_record(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sase.core.agent_hold_facade._project_for_cwd", lambda: "scratch"
    )
    exit_code = cli_hold._handle_create(_create_args(future=True, scope="host"))
    assert exit_code == 0
    key = list_current_agent_holds()[0]["armer"]["key"]
    capsys.readouterr()

    exit_code = cli_hold._handle_show(argparse.Namespace(key=key, json=True))
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["armer"]["key"] == key


def test_release_removes_current_agents_own_hold_by_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sase.core.agent_hold_facade._project_for_cwd", lambda: "scratch"
    )
    cli_hold._handle_create(_create_args(future=True, scope="host"))
    capsys.readouterr()

    exit_code = cli_hold._handle_release(argparse.Namespace(key=None))
    assert exit_code == 0
    assert list_current_agent_holds() == []


def test_release_reports_no_active_hold(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli_hold._handle_release(argparse.Namespace(key="agent:missing"))
    assert exit_code == 1
    assert "no active hold" in capsys.readouterr().err


def test_run_requires_a_command(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli_hold._handle_run(_run_args())
    assert exit_code == 2
    assert "provide a command after --" in capsys.readouterr().err


def test_run_defaults_to_future_and_pending_when_no_selector_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_arm(**kwargs: object) -> AgentHoldArmResult:
        captured.update(kwargs)
        return AgentHoldArmResult(
            record={"armer": {"key": "cli:host:1"}, "expires_at": 0.0},
            capture=None,
        )

    monkeypatch.setattr(cli_hold, "_arm_agent_hold", fake_arm)
    monkeypatch.setattr(cli_hold, "release_agent_hold", lambda *_a, **_k: True)

    exit_code = cli_hold._handle_run(_run_args(hold_run_command_words=["--", "true"]))

    assert exit_code == 0
    assert captured["future"] is True
    assert captured["pending"] is True


def test_run_preserves_explicit_selectors_over_the_quiesce_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_arm(**kwargs: object) -> AgentHoldArmResult:
        captured.update(kwargs)
        return AgentHoldArmResult(
            record={"armer": {"key": "cli:host:1"}, "expires_at": 0.0},
            capture=None,
        )

    monkeypatch.setattr(cli_hold, "_arm_agent_hold", fake_arm)
    monkeypatch.setattr(cli_hold, "release_agent_hold", lambda *_a, **_k: True)

    exit_code = cli_hold._handle_run(
        _run_args(names=["a.b--code"], hold_run_command_words=["--", "true"])
    )

    assert exit_code == 0
    assert captured["names"] == ["a.b--code"]
    assert captured["future"] is False
    assert captured["pending"] is False


def test_run_preserves_nonzero_exit_status_and_releases_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    released: list[str] = []

    def fake_arm(**_kwargs: object) -> AgentHoldArmResult:
        return AgentHoldArmResult(
            record={"armer": {"key": "cli:host:1"}, "expires_at": 0.0},
            capture=None,
        )

    def fake_release(armer_key: str, **_kwargs: object) -> bool:
        released.append(armer_key)
        return True

    monkeypatch.setattr(cli_hold, "_arm_agent_hold", fake_arm)
    monkeypatch.setattr(cli_hold, "release_agent_hold", fake_release)

    exit_code = cli_hold._handle_run(
        _run_args(future=True, hold_run_command_words=["--", "sh", "-c", "exit 7"])
    )

    assert exit_code == 7
    assert released == ["cli:host:1"]


def test_run_releases_hold_even_when_command_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    released: list[str] = []

    def fake_arm(**_kwargs: object) -> AgentHoldArmResult:
        return AgentHoldArmResult(
            record={"armer": {"key": "cli:host:1"}, "expires_at": 0.0},
            capture=None,
        )

    def fake_release(armer_key: str, **_kwargs: object) -> bool:
        released.append(armer_key)
        return True

    def fake_subprocess_run(*_args: object, **_kwargs: object):
        raise FileNotFoundError("no such command")

    monkeypatch.setattr(cli_hold, "_arm_agent_hold", fake_arm)
    monkeypatch.setattr(cli_hold, "release_agent_hold", fake_release)
    monkeypatch.setattr(cli_hold.subprocess, "run", fake_subprocess_run)

    with pytest.raises(FileNotFoundError):
        cli_hold._handle_run(
            _run_args(future=True, hold_run_command_words=["--", "does-not-exist"])
        )

    assert released == ["cli:host:1"]
