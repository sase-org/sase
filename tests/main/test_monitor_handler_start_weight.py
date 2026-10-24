"""Weight override validation and output for ``sase monitor start``."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agent.handoff_inflight import HANDOFF_INFLIGHT_MARKER
from sase.main.monitor.start import handle_monitor_start
from tests.main.monitor_handler_helpers import dispatch, monitor_home, pin_project
from tests.main.parser_cli_helpers import parse_sase_args

__all__ = ["monitor_home"]


@pytest.mark.parametrize("weight", ["1", "0.5", "-1", "nan", "inf", "abc"])
def test_start_rejects_nonzero_or_invalid_weight(
    weight: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert dispatch(["monitor", "start", "-w", weight]) == 2
    assert "-w/--weight accepts only 0" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["-p", "verify", "--", "true"], "with -p/--profile verify"),
        (["-f", "REF", "--", "true"], "with -f/--completion"),
        (["--", "sase", "tool", "run", "check"], "with a `sase tool run` command"),
        (
            ["--", "sleep 5 && sase tool run check"],
            "with a `sase tool run` command",
        ),
    ],
)
def test_start_rejects_weight_for_verification_commands(
    arguments: list[str],
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert dispatch(["monitor", "start", "-w", "0", *arguments]) == 2
    assert message in capsys.readouterr().err


def test_join_rejects_weight_before_inspecting_the_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_AGENT", "acme")
    monkeypatch.setenv("SASE_AGENT_NAME", "acme")
    monkeypatch.setattr(
        "sase.monitor.join.inspect_join_target",
        lambda *_args, **_kwargs: pytest.fail("join target must not be inspected"),
    )

    assert dispatch(["monitor", "start", "-w", "0", "-J", "RUN"]) == 2
    assert "-J cannot be used with -w/--weight" in capsys.readouterr().err


def test_rejected_agent_start_does_not_write_inflight_marker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    marker_dir = tmp_path / "starter"
    marker_dir.mkdir()
    monkeypatch.setenv("SASE_AGENT", "acme")
    monkeypatch.setenv("SASE_AGENT_NAME", "acme")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(marker_dir))

    args = parse_sase_args(["monitor", "start", "-w", "1", "--", "sleep 5"])
    assert handle_monitor_start(args) == 2
    assert not (marker_dir / HANDOFF_INFLIGHT_MARKER).exists()


def _valid_start_args(tmp_path: Path, weight: str | None):
    argv = [
        "monitor",
        "start",
        "-a",
        "acme",
        "-C",
        str(tmp_path),
        "-s",
        "WATCHING",
        "-S",
        "WATCHED",
        "--",
        "sleep 5",
    ]
    if weight is not None:
        argv[2:2] = ["-w", weight]
    return parse_sase_args(argv)


@pytest.mark.parametrize(
    ("weight", "expected"), [("0", 0.0), ("0.0", 0.0), (None, None)]
)
def test_start_passes_weight_override_to_monitor_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    weight: str | None,
    expected: float | None,
) -> None:
    pin_project(monkeypatch)
    captured: dict[str, object] = {}

    def fake_start(request):  # type: ignore[no-untyped-def]
        captured["request"] = request
        return SimpleNamespace(
            monitor_id="m" * 40,
            member_agent_name="acme--mon",
            artifacts_dir=str(tmp_path / "monitor"),
            lane="acme",
            project_name="proj",
            command=request.command,
            cwd=request.cwd,
            next_action=request.next_action,
            next_model=None,
            next_output=request.next_output,
            tool_run_id=None,
        )

    monkeypatch.setattr("sase.main.monitor.start.start_monitor", fake_start)

    assert handle_monitor_start(_valid_start_args(tmp_path, weight)) == 0
    request = captured["request"]
    assert request.queue_weight_override == expected
    summary = capsys.readouterr().out
    weight_line = "queue weight: 0 (holds no runner capacity)"
    assert (weight_line in summary) is (weight is not None)


def test_weight_zero_and_negative_zero_are_accepted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The numeric rule accepts both canonical and negative zero spellings."""
    pin_project(monkeypatch)
    captured: list[float | None] = []

    def fake_start(request):  # type: ignore[no-untyped-def]
        captured.append(request.queue_weight_override)
        return SimpleNamespace(
            monitor_id="m" * 40,
            member_agent_name="acme--mon",
            artifacts_dir=str(tmp_path / "monitor"),
            lane="acme",
            project_name="proj",
            command=request.command,
            cwd=request.cwd,
            next_action=request.next_action,
            next_model=None,
            next_output=request.next_output,
            tool_run_id=None,
        )

    monkeypatch.setattr("sase.main.monitor.start.start_monitor", fake_start)
    args = _valid_start_args(tmp_path, "-0")

    assert handle_monitor_start(args) == 0
    assert captured == [0.0]
