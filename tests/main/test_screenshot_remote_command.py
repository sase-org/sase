"""Remote ``sase screenshot`` command tests."""

from __future__ import annotations

from pathlib import Path
import shlex
import subprocess

import pytest

from sase.dispatch.ssh_target import RemoteSshTarget
from sase.main import screenshot_handler
from sase.main.screenshot_handler import handle_screenshot_command
from sase.screenshot import local as screenshot_local
from sase.screenshot import remote as screenshot_remote
from sase.screenshot.local import ScreenshotOptions, ScreenshotScriptStep
from sase.screenshot.remote import capture_remote_screenshot
from tests.main.parser_cli_helpers import parse_sase_args
from tests.main.screenshot_remote_fixtures import (
    _FakeRemoteResult,
    _FakeSshRunner,
    _version_payload,
)


def _script(*steps: tuple[str, str]) -> tuple[ScreenshotScriptStep, ...]:
    return tuple(ScreenshotScriptStep(kind, value) for kind, value in steps)


def _options(
    *,
    output: Path,
    svg_only: bool = False,
    keep: bool = False,
    window: str | None = None,
    presses: tuple[str, ...] = ("j", "k"),
    wait_for: tuple[str, ...] = ("Ready",),
    script: tuple[ScreenshotScriptStep, ...] | None = None,
    settle_ms: int = 1,
    timeout: float = 5,
    tui_args: tuple[str, ...] = ("--", "-t", "axe"),
) -> ScreenshotOptions:
    if script is None:
        script = _script(
            *(("press", key) for key in presses),
            *(("wait", pattern) for pattern in wait_for),
        )
    return ScreenshotOptions(
        output=output,
        size=(80, 24),
        script=script,
        settle_ms=settle_ms,
        svg_only=svg_only,
        keep=keep,
        window=window,
        timeout=timeout,
        tui_args=tui_args,
    )


def _route_fake_remote_tmp(
    monkeypatch: pytest.MonkeyPatch,
    runner: _FakeSshRunner,
) -> None:
    monkeypatch.setattr(screenshot_remote, "_REMOTE_BASE", str(runner.remote_root))


def test_remote_capture_runs_svg_leg_over_ssh_and_rasterizes_locally(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(
        tmp_path,
        remote_tmux_window="duplicate display",
        remote_tmux_target="@42",
    )
    output = tmp_path / "remote.png"
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(
            host="apollo.tailnet",
            requested_machine=host,
            enrolled_alias=host,
            enrolled=True,
        ),
    )

    from sase.ace.tui import visual_render

    monkeypatch.setattr(visual_render, "render_svg_to_png", lambda svg: b"PNG")

    result = capture_remote_screenshot(
        "apollo",
        _options(
            output=output,
            script=_script(
                ("press", "j"),
                ("type", 'query "apollo" $HOME | cat'),
                ("press", "literal key's $HOME | echo; true"),
                ("wait", "Agents Ready|Loading"),
                ("wait", 'quote " and $dollar; noop | cat'),
            ),
            tui_args=(
                "--",
                "-t",
                "axe panel",
                "--query",
                "owner=$USER|status:open",
            ),
        ),
        runner=runner,
    )

    assert output.read_bytes() == b"PNG"
    assert result.host == "apollo.tailnet"
    assert result.remote_sase_version == "sase 0.17.1+861.g3fb42fa11"
    assert result.svg.read_text(encoding="utf-8") == (
        "<svg><text>Remote Ready</text></svg>"
    )
    assert result.tmux_window == "duplicate display"
    assert result.tmux_target == "@42"
    assert runner.cleanup_count == 1
    assert runner.remote_svg is not None
    assert not Path(runner.remote_svg).exists()
    assert len(runner.calls[1]) == 6

    remote_capture = next(
        command
        for command in runner.remote_invocations
        if command[:3] == ["sase", "screenshot", "--svg"]
    )
    remote_argv = remote_capture
    assert "--host" not in remote_argv
    assert remote_argv[:4] == ["sase", "screenshot", "--svg", "-o"]
    assert "-s" in remote_argv
    assert remote_argv[remote_argv.index("-s") + 1] == "80x24"
    assert "-d" in remote_argv
    assert remote_argv[remote_argv.index("-d") + 1] == "1"
    script_start = remote_argv.index("-p")
    assert remote_argv[script_start:-5] == [
        "-p",
        "j",
        "-T",
        'query "apollo" $HOME | cat',
        "-p",
        "literal key's $HOME | echo; true",
        "-w",
        "Agents Ready|Loading",
        "-w",
        'quote " and $dollar; noop | cat',
    ]
    assert remote_argv[-5:] == [
        "--",
        "-t",
        "axe panel",
        "--query",
        "owner=$USER|status:open",
    ]
    assert ["sase", "version", "--json"] in runner.remote_invocations
    assert ["sase", "--version"] not in runner.remote_invocations
    assert any(
        command[:2] == ["login-shell", "-lc"]
        and command[2].startswith("exec sase screenshot --contract")
        for command in runner.remote_invocations
    )


def test_remote_capture_keep_then_recapture_uses_printed_unique_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(
        tmp_path,
        remote_tmux_window="duplicate display",
        remote_tmux_target="@42",
    )
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(host=host, requested_machine=host),
    )

    from sase.ace.tui import visual_render

    monkeypatch.setattr(visual_render, "render_svg_to_png", lambda svg: b"PNG")

    first = capture_remote_screenshot(
        "apollo",
        _options(output=tmp_path / "first.png", keep=True),
        runner=runner,
    )
    capture_remote_screenshot(
        "apollo",
        _options(
            output=tmp_path / "second.png",
            window=first.tmux_target,
        ),
        runner=runner,
    )

    remote_captures = [
        command
        for command in runner.remote_invocations
        if command[:3] == ["sase", "screenshot", "--svg"]
    ]
    assert first.tmux_target == "@42"
    assert remote_captures[1][remote_captures[1].index("-W") + 1] == "@42"


def test_remote_send_keys_hint_survives_local_and_remote_shells(
    tmp_path: Path,
) -> None:
    runner = _FakeSshRunner(tmp_path)
    target = "@42 target 'single' \"quoted\" | ok; $literal"
    key = 'literal key\'s "quoted" $HOME | echo; true'
    result = _FakeRemoteResult(
        svg=tmp_path / "shot.svg",
        png=tmp_path / "shot.png",
        host="apollo.tailnet",
        remote_sase_version="sase 0.17.1",
        screenshot_dir="/tmp/sase-requests",
        tmux_session="sase_ace_agents",
        tmux_window="duplicate display",
        tmux_target=target,
        tmux_pid=9090,
    )

    completed = subprocess.run(
        ["/bin/sh", "-c", result.send_keys_hint.replace("<KEY>", shlex.quote(key))],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
        env=runner.shell_env(),
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    assert completed.stderr == ""
    assert ["tmux", "send-keys", "-t", target, key] in runner.remote_invocations


def test_remote_capture_missing_sase_after_login_reports_environment_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(tmp_path, login_provides_sase=False)
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(host=host, requested_machine=host),
    )

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_remote_screenshot(
            "bad-host", _options(output=tmp_path / "shot.png"), runner=runner
        )

    message = str(excinfo.value)
    assert "failed to probe remote screenshot contract" in message
    assert "exit 127" in message
    assert "remote login environment" in message
    assert runner.cleanup_count == 0


def test_remote_capture_contract_startup_failure_keeps_remote_detail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(
        tmp_path,
        probe_returncode=70,
        probe_stdout="",
        probe_stderr="ImportError: bad startup",
    )
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(host=host, requested_machine=host),
    )

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_remote_screenshot(
            "bad-host", _options(output=tmp_path / "shot.png"), runner=runner
        )

    message = str(excinfo.value)
    assert "exit 70" in message
    assert "ImportError: bad startup" in message
    assert "missing or too old" not in message
    assert runner.cleanup_count == 0


def test_remote_capture_malformed_contract_reports_protocol_problem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(tmp_path, probe_stdout="not json")
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(host=host, requested_machine=host),
    )

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_remote_screenshot(
            "bad-host", _options(output=tmp_path / "shot.png"), runner=runner
        )

    message = str(excinfo.value)
    assert "malformed protocol data" in message
    assert "not json" in message
    assert "upgrade" not in message
    assert runner.cleanup_count == 0


def test_remote_screenshot_argv_forwards_type_steps_in_order() -> None:
    argv = screenshot_remote._remote_screenshot_argv(
        "/tmp/remote.svg",
        _options(
            output=Path("/tmp/shot.png"),
            script=_script(
                ("press", "slash"),
                ("type", "machine:apollo"),
                ("press", "enter"),
                ("wait", "17/17"),
            ),
            settle_ms=0,
            tui_args=("--", "-t", "axe"),
        ),
    )

    assert argv[:3] == ["sase", "screenshot", "--svg"]
    assert "-p" in argv
    assert argv[argv.index("-p") :] == [
        "-p",
        "slash",
        "-T",
        "machine:apollo",
        "-p",
        "enter",
        "-w",
        "17/17",
        "--",
        "-t",
        "axe",
    ]


def test_remote_capture_rejects_pre_type_contract_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(tmp_path, probe_stdout='{"schema_version": 1}')
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(host=host, requested_machine=host),
    )

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_remote_screenshot(
            "old-host",
            _options(
                output=tmp_path / "shot.png",
                script=_script(("type", "machine:apollo")),
            ),
            runner=runner,
        )

    message = str(excinfo.value)
    assert "unsupported schema_version=1" in message
    assert "expected 2" in message
    assert "upgrade" in message
    assert runner.cleanup_count == 0


def test_remote_capture_incompatible_contract_schema_asks_for_upgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(tmp_path, probe_stdout='{"schema_version": 999}')
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(host=host, requested_machine=host),
    )

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_remote_screenshot(
            "old-host", _options(output=tmp_path / "shot.png"), runner=runner
        )

    message = str(excinfo.value)
    assert "unsupported schema_version=999" in message
    assert "upgrade" in message
    assert runner.cleanup_count == 0


def test_remote_capture_requires_retained_tmux_target_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(tmp_path, include_tmux_target=False)
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(host=host, requested_machine=host),
    )

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_remote_screenshot(
            "old-host", _options(output=tmp_path / "shot.png"), runner=runner
        )

    message = str(excinfo.value)
    assert "sase_tmux_target" in message
    assert "upgrade" in message
    assert runner.cleanup_count == 1


def test_remote_capture_ssh_failure_is_not_reported_as_upgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(tmp_path, probe_returncode=255)
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(host=host, requested_machine=host),
    )

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_remote_screenshot(
            "offline-host", _options(output=tmp_path / "shot.png"), runner=runner
        )

    message = str(excinfo.value)
    assert "SSH failed" in message
    assert "missing or too old" not in message
    assert runner.cleanup_count == 0


def test_remote_capture_cleans_remote_temp_file_after_capture_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(tmp_path, capture_returncode=2)
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(host=host, requested_machine=host),
    )

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_remote_screenshot(
            "bad-host", _options(output=tmp_path / "shot.png"), runner=runner
        )

    assert "remote screenshot capture" in str(excinfo.value)
    assert runner.cleanup_count == 1
    assert runner.remote_svg is not None
    assert not Path(runner.remote_svg).exists()


def test_remote_capture_cleans_remote_temp_file_after_fetch_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(tmp_path, fetch_returncode=1)
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(host=host, requested_machine=host),
    )

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_remote_screenshot(
            "bad-host", _options(output=tmp_path / "shot.png"), runner=runner
        )

    assert "failed to fetch remote SVG" in str(excinfo.value)
    assert runner.cleanup_count == 1
    assert runner.remote_svg is not None
    assert not Path(runner.remote_svg).exists()


def test_remote_capture_cleans_remote_temp_file_after_version_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(
        tmp_path,
        version_returncode=1,
        version_stdout="",
        version_stderr="version inventory failed",
    )
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(host=host, requested_machine=host),
    )

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_remote_screenshot(
            "bad-host", _options(output=tmp_path / "shot.png"), runner=runner
        )

    message = str(excinfo.value)
    assert "failed to query remote sase version" in message
    assert "exit 1" in message
    assert "version inventory failed" in message
    assert runner.cleanup_count == 1
    assert runner.remote_svg is not None
    assert not Path(runner.remote_svg).exists()


@pytest.mark.parametrize(
    ("version_stdout", "expected"),
    [
        ("not json", "expected JSON from `sase version --json`"),
        (
            _version_payload(
                {
                    "name": "sase-core-rs",
                    "role": "core",
                    "display_version": "0.17.1",
                }
            ),
            "missing host package named `sase`",
        ),
        (
            _version_payload({"name": "sase", "role": "host", "display_version": ""}),
            "missing display_version",
        ),
    ],
)
def test_remote_capture_rejects_malformed_version_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version_stdout: str,
    expected: str,
) -> None:
    runner = _FakeSshRunner(tmp_path, version_stdout=version_stdout)
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(host=host, requested_machine=host),
    )

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_remote_screenshot(
            "bad-host", _options(output=tmp_path / "shot.png"), runner=runner
        )

    message = str(excinfo.value)
    assert "remote version query" in message
    assert expected in message
    assert runner.cleanup_count == 1
    assert runner.remote_svg is not None
    assert not Path(runner.remote_svg).exists()


def test_remote_capture_preserves_capture_error_when_cleanup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(
        tmp_path,
        capture_returncode=2,
        cleanup_returncode=1,
    )
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(host=host, requested_machine=host),
    )

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_remote_screenshot(
            "bad-host", _options(output=tmp_path / "shot.png"), runner=runner
        )

    message = str(excinfo.value)
    assert "remote screenshot capture" in message
    assert "cleanup failed" not in message
    assert runner.cleanup_count == 1


def test_remote_capture_timeouts_share_one_bounded_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(tmp_path)
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(host=host, requested_machine=host),
    )

    capture_remote_screenshot(
        "apollo",
        _options(output=tmp_path / "shot.png", timeout=0.25),
        runner=runner,
    )

    timeouts = [
        value
        for kwargs in runner.call_kwargs
        if isinstance((value := kwargs.get("timeout")), (int, float))
    ]
    assert timeouts
    assert all(0 < timeout <= 10.25 for timeout in timeouts)


def test_remote_handler_prints_version_and_keep_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = _FakeRemoteResult(
        svg=tmp_path / "shot.svg",
        png=tmp_path / "shot.png",
        host="apollo.tailnet",
        remote_sase_version="sase 0.17.1",
        screenshot_dir="/tmp/sase-requests",
        tmux_session="sase_ace_agents",
        tmux_window="sase_tmux_9",
        tmux_target="@42",
        tmux_pid=9090,
    )
    monkeypatch.setattr(
        screenshot_handler,
        "capture_remote_screenshot",
        lambda host, options: result,
    )
    args = parse_sase_args(
        ["screenshot", "--host", "apollo", "--keep", "-o", str(tmp_path / "shot.png")]
    )

    handle_screenshot_command(args)

    out = capsys.readouterr().out
    assert "host=apollo.tailnet\n" in out
    assert "remote_sase_version=sase 0.17.1\n" in out
    assert "png=" in out
    assert "svg=" in out
    assert "sase_tmux_target=@42\n" in out
    assert (
        "remote_send_keys_hint=printf '%s\\n' <KEY> | ssh apollo.tailnet "
        "'IFS= read -r key && tmux send-keys -t @42 \"$key\"'\n"
    ) in out


def test_real_parser_rejects_legacy_top_level_version_flag() -> None:
    with pytest.raises(SystemExit) as excinfo:
        parse_sase_args(["--version"])

    assert excinfo.value.code == 2
