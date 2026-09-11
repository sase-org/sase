"""Parser and handler contract tests for ``sase axe restart``."""

from __future__ import annotations

import argparse
import json

import pytest

import sase.main.axe_handler as axe_handler
from sase.axe._config_types import AxeConfigDiagnostic
from sase.axe.config import AxeConfig, AxeConfigError
from sase.axe.process import AxeStartResult
from sase.main.parser import create_parser


def _restart_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "json": False,
        "max_hook_runners": None,
        "max_agent_runners": None,
        "zombie_timeout": None,
        "query": "",
        "verify_timeout": 15.0,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_parser_accepts_every_restart_option() -> None:
    ns = create_parser().parse_args(
        [
            "axe",
            "restart",
            "-A",
            "2",
            "-H",
            "2",
            "-q",
            "@p",
            "-t",
            "30",
            "-z",
            "600",
            "-j",
        ]
    )

    assert ns.axe_subcommand == "restart"
    assert ns.max_agent_runners == 2
    assert ns.max_hook_runners == 2
    assert ns.query == "@p"
    assert ns.verify_timeout == 30.0
    assert ns.zombie_timeout == 600
    assert ns.json is True


def test_parser_rejects_non_positive_verify_timeout() -> None:
    with pytest.raises(SystemExit):
        create_parser().parse_args(["axe", "restart", "--verify-timeout", "0"])


def test_handle_restart_exits_0_on_verified_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sase.axe.config.load_axe_config", lambda: AxeConfig())
    seen: dict[str, object] = {}

    def fake_restart(config: AxeConfig, **kwargs: object) -> AxeStartResult:
        seen["config"] = config
        seen["kwargs"] = kwargs
        return AxeStartResult(status="started", pid=123, message="ok", verified=True)

    with pytest.raises(SystemExit) as exc_info:
        axe_handler._handle_restart(
            _restart_args(json=True), restart_axe_fn=fake_restart
        )

    assert exc_info.value.code == 0
    assert seen["kwargs"]["verification_timeout"] == 15.0
    assert "on_event" not in seen["kwargs"]
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "started"
    assert payload["pid"] == 123
    assert payload["verified"] is True


def test_handle_restart_json_mode_prints_only_the_json_object(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sase.axe.config.load_axe_config", lambda: AxeConfig())

    def fake_restart(config: AxeConfig, **kwargs: object) -> AxeStartResult:
        return AxeStartResult(status="started", pid=1, message="ok", verified=True)

    with pytest.raises(SystemExit):
        axe_handler._handle_restart(
            _restart_args(json=True), restart_axe_fn=fake_restart
        )

    out = capsys.readouterr().out
    # A stray progress line before/after the object would break this parse.
    payload = json.loads(out)
    assert payload["status"] == "started"


def test_handle_restart_exits_1_on_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sase.axe.config.load_axe_config", lambda: AxeConfig())

    def fake_restart(config: AxeConfig, **kwargs: object) -> AxeStartResult:
        return AxeStartResult(status="failed", message="boom")

    with pytest.raises(SystemExit) as exc_info:
        axe_handler._handle_restart(
            _restart_args(json=True), restart_axe_fn=fake_restart
        )

    assert exc_info.value.code == 1


def test_handle_restart_exits_2_on_config_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    diagnostic = AxeConfigDiagnostic(code="bad_axe_config", message="boom")
    monkeypatch.setattr(
        "sase.axe.config.load_axe_config",
        lambda: (_ for _ in ()).throw(AxeConfigError([diagnostic])),
    )

    def fake_restart(config: AxeConfig, **kwargs: object) -> AxeStartResult:
        raise AssertionError("restart_axe_fn must not run after a config error")

    with pytest.raises(SystemExit) as exc_info:
        axe_handler._handle_restart(
            _restart_args(json=True), restart_axe_fn=fake_restart
        )

    assert exc_info.value.code == 2
    assert "boom" in capsys.readouterr().err


def test_handle_restart_plain_mode_renders_progress_and_exits_0(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.axe.process import RestartFinished, StopBegan

    monkeypatch.setattr("sase.axe.config.load_axe_config", lambda: AxeConfig())

    def fake_restart(config: AxeConfig, **kwargs: object) -> AxeStartResult:
        on_event = kwargs["on_event"]
        result = AxeStartResult(status="started", pid=77, message="ok", verified=True)
        on_event(StopBegan())  # type: ignore[operator]
        on_event(RestartFinished(result=result, elapsed_seconds=1.0))  # type: ignore[operator]
        return result

    with pytest.raises(SystemExit) as exc_info:
        axe_handler._handle_restart(
            _restart_args(json=False), restart_axe_fn=fake_restart
        )

    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "Stopping AXE" in out
    assert "AXE restarted and verified (pid 77)" in out
