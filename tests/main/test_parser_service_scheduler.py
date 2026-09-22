"""Parser and handler coverage for service-host and scheduler command surfaces."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.main.parser import _DEFAULT_LIST_GROUP_DEST, create_parser
from sase.main.service_handler import handle_service_command
from sase.procs.service_meta import (
    SERVICE_PROC_MODE_ONESHOT,
    SERVICE_PROC_SOURCE_TRANSIENT,
)
from tests.main.parser_cli_helpers import parse_sase_args
from tests.main.parser_help_helpers import flat_help, help_subcommand_rows, parser_for


def test_service_help_lists_sorted_subcommands() -> None:
    parser = parser_for(("sase", "service"))
    help_text = parser.format_help()
    expected = {
        "init",
        "logs",
        "proc",
        "restart",
        "run",
        "start",
        "status",
        "stop",
        "uninstall",
    }

    assert help_subcommand_rows(help_text, expected) == sorted(expected)
    assert "Bare `sase service` is harmless" in flat_help(help_text)


def test_service_proc_bare_defaults_to_list() -> None:
    parser = create_parser()

    bare = parser.parse_args(["service", "proc"])

    assert bare.command == "service"
    assert bare.service_subcommand == "proc"
    assert bare.service_proc_subcommand == "list"
    assert getattr(bare, _DEFAULT_LIST_GROUP_DEST) == "sase service proc"


def test_service_proc_run_parser_carries_transient_options() -> None:
    args = create_parser().parse_args(
        [
            "service",
            "proc",
            "run",
            "-c",
            "/tmp",
            "-l",
            "One shot",
            "-p",
            "sase",
            "-w",
            "17",
            "--",
            "echo",
            "ok",
        ]
    )

    assert args.cwd == "/tmp"
    assert args.label == "One shot"
    assert args.project == "sase"
    assert args.workspace == 17
    assert args.proc_command == ["--", "echo", "ok"]


def test_service_init_and_uninstall_parser_flags() -> None:
    init_args = create_parser().parse_args(
        ["service", "init", "-a", "-c", "-d", "-f", "-y"]
    )
    uninstall_args = create_parser().parse_args(
        ["service", "uninstall", "-c", "-d", "-f", "-y"]
    )
    alias_args = create_parser().parse_args(["init", "service", "-a", "-c", "-d", "-f"])

    assert init_args.check is True
    assert init_args.diff is True
    assert init_args.force is True
    assert init_args.yes is True
    assert init_args.allow_agent_env is True
    assert uninstall_args.check is True
    assert uninstall_args.diff is True
    assert uninstall_args.force is True
    assert uninstall_args.yes is True
    assert getattr(uninstall_args, "allow_agent_env", False) is False
    assert alias_args.init_subcommand == "service"
    assert alias_args.check is True
    assert alias_args.diff is True
    assert alias_args.force is True
    assert alias_args.allow_agent_env is True
    uninstall_help = parser_for(("sase", "service", "uninstall")).format_help()
    assert "-f, --force" in uninstall_help
    assert "-c, --check" in uninstall_help
    assert "-d, --diff" in uninstall_help
    assert "-y, --yes" in uninstall_help
    init_help = parser_for(("sase", "service", "init")).format_help()
    assert "-a, --allow-agent-env" in init_help


def test_scheduler_help_lists_sorted_subcommands() -> None:
    parser = parser_for(("sase", "scheduler"))
    help_text = parser.format_help()
    expected = {"restart", "run", "start", "status", "stop"}

    assert help_subcommand_rows(help_text, expected) == sorted(expected)
    flat = flat_help(help_text)
    assert "`scheduler` service proc on the SASE service host" in flat
    assert "legacy" not in flat
    assert "beta flag" not in flat


def test_scheduler_legacy_lifecycle_options_are_gone() -> None:
    restart_help = flat_help(parser_for(("sase", "scheduler", "restart")).format_help())
    stop_help = flat_help(parser_for(("sase", "scheduler", "stop")).format_help())

    assert "--verify-timeout" not in restart_help
    assert "--force" not in stop_help


def test_scheduler_service_path_ignores_no_overrides() -> None:
    for command in ("start", "restart"):
        help_text = flat_help(parser_for(("sase", "scheduler", command)).format_help())
        for flag in (
            "--max-agent-runners",
            "--max-hook-runners",
            "--query",
            "--zombie-timeout",
        ):
            assert flag not in help_text
    for command in ("start", "restart"):
        help_text = flat_help(parser_for(("sase", "axe", command)).format_help())
        for flag in (
            "--max-agent-runners",
            "--max-hook-runners",
            "--query",
            "--zombie-timeout",
        ):
            assert flag not in help_text

    restart_help = flat_help(parser_for(("sase", "scheduler", "restart")).format_help())
    assert "--json" not in restart_help
    axe_restart_help = flat_help(parser_for(("sase", "axe", "restart")).format_help())
    assert "--json" not in axe_restart_help

    # The overrides stay on `run`, and `-j` stays on `status`.
    run_help = flat_help(parser_for(("sase", "scheduler", "run")).format_help())
    for flag in (
        "--max-agent-runners",
        "--max-hook-runners",
        "--query",
        "--zombie-timeout",
    ):
        assert flag in run_help
    status_help = flat_help(parser_for(("sase", "scheduler", "status")).format_help())
    assert "--json" in status_help
    axe_status_help = flat_help(parser_for(("sase", "axe", "status")).format_help())
    assert "--json" in axe_status_help

    # Removed flags are argparse errors, not silently ignored options.
    parser = create_parser()
    for argv in (
        ["scheduler", "start", "--query", "x"],
        ["scheduler", "restart", "-A", "2"],
        ["scheduler", "restart", "--json"],
        ["axe", "start", "-z", "5"],
        ["axe", "restart", "--json"],
    ):
        with pytest.raises(SystemExit):
            parser.parse_args(argv)


def test_scheduler_lifecycle_help_names_service_host() -> None:
    for command in ("start", "stop", "restart"):
        help_text = flat_help(parser_for(("sase", "scheduler", command)).format_help())
        assert "service host" in help_text
        assert "request is recorded" in help_text


def test_service_proc_run_submits_transient_oneshot_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, Any] = {}

    class _Proc:
        proc_id = "svc123456789"

    def fake_submit(request: object) -> _Proc:
        captured["request"] = request
        return _Proc()

    # ``proc run`` and the TUI's ``!`` share ``submit_oneshot``, which picks the
    # ``#n`` index from the store and then submits the detached proc request.
    monkeypatch.setattr("sase.procs.oneshot.submit_proc_request", fake_submit)
    monkeypatch.setattr("sase.procs.oneshot._choose_store_slot", lambda: 4)
    args = parse_sase_args(
        [
            "service",
            "proc",
            "run",
            "-c",
            str(tmp_path),
            "-l",
            "Transient",
            "-p",
            "sase",
            "-w",
            "17",
            "--",
            "true",
        ]
    )

    with pytest.raises(SystemExit) as exit_info:
        handle_service_command(args)

    assert exit_info.value.code == 0
    request = captured["request"]
    assert request.cwd == tmp_path
    assert request.label == "Transient"
    assert request.project == "sase"
    assert request.workspace_num == 17
    assert request.service is not None
    assert request.service.name is None
    assert request.service.mode == SERVICE_PROC_MODE_ONESHOT
    assert request.service.source == SERVICE_PROC_SOURCE_TRANSIENT
    assert list(request.concurrency_keys) == ["bgcmd-slot:4"]
    assert list(request.argv) == ["true"]
    assert capsys.readouterr().out == "svc123456789\n"


def test_service_run_loads_captured_env_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[object] = []

    def load(*, override_existing: bool = False, **_kwargs: object) -> tuple[str, ...]:
        order.append(("load", override_existing))
        return ()

    def dispatch(_args: object) -> int:
        order.append("dispatch")
        return 0

    monkeypatch.setattr("sase.main.service_handler.load_service_environment", load)
    monkeypatch.setattr("sase.main.service_handler._handle_service_command", dispatch)

    with pytest.raises(SystemExit) as exit_info:
        handle_service_command(parse_sase_args(["service", "run"]))

    assert exit_info.value.code == 0
    assert order == [("load", True), "dispatch"]


def test_service_status_does_not_override_interactive_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[object] = []
    monkeypatch.setattr(
        "sase.main.service_handler.load_service_environment",
        lambda **kwargs: called.append(kwargs),
    )
    monkeypatch.setattr(
        "sase.main.service_handler._handle_service_command", lambda args: 0
    )

    with pytest.raises(SystemExit):
        handle_service_command(parse_sase_args(["service", "status"]))

    assert called == []


def test_service_uninstall_handler_threads_force(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, bool] = {}

    def fake_uninstall(*, force: bool = False, **_kwargs: object) -> object:
        captured["force"] = force
        return SimpleNamespace(
            ok=True,
            changed=True,
            message="uninstalled sase.service",
            plan=None,
        )

    monkeypatch.setattr(
        "sase.main.service_handler.apply_service_uninstall", fake_uninstall
    )

    with pytest.raises(SystemExit) as exit_info:
        handle_service_command(parse_sase_args(["service", "uninstall", "-f", "-y"]))

    assert exit_info.value.code == 0
    assert captured["force"] is True
    assert "uninstalled sase.service" in capsys.readouterr().out


def test_service_init_handler_threads_allow_agent_env(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def fake_apply(
        *, force: bool = False, allow_agent_env: bool = False, **_kwargs: object
    ) -> object:
        captured["force"] = force
        captured["allow_agent_env"] = allow_agent_env
        return SimpleNamespace(
            ok=True,
            changed=True,
            message="installed sase.service",
            plan=None,
        )

    monkeypatch.setattr("sase.main.service_handler.apply_service_init", fake_apply)

    with pytest.raises(SystemExit) as exit_info:
        handle_service_command(parse_sase_args(["service", "init", "-y", "-a"]))

    assert exit_info.value.code == 0
    assert captured["allow_agent_env"] is True


def _proc_request_seams(
    monkeypatch: pytest.MonkeyPatch,
    *,
    old_pid: int | None = 111,
    generation: int | None = 4,
    nudged: bool = True,
    completed: Any | None = None,
    stop_timeout: float = 0.5,
) -> dict[str, Any]:
    """Stub the proc start/restart confirmation seams; return the spies."""
    import sase.main.service_handler as service_handler

    calls: dict[str, Any] = {"wait": []}
    entry = SimpleNamespace(name="scheduler", stop_timeout_seconds=stop_timeout)
    config = SimpleNamespace(get=lambda name: entry)
    monkeypatch.setattr(service_handler, "load_service_config", lambda: config)
    row = SimpleNamespace(name="scheduler", pid=old_pid)
    snapshot = SimpleNamespace(procs=[row])
    monkeypatch.setattr(service_handler, "current_service_status", lambda: snapshot)

    def _outcome(
        name: str, *, actor: str, reason: str | None = None
    ) -> SimpleNamespace:
        action = "restart" if reason == "restart" else "start"
        return SimpleNamespace(
            action=action,
            name=name,
            mutations=(),
            nudged=nudged,
            message=f"requested service proc {name} {action}",
            generation=generation,
        )

    monkeypatch.setattr(service_handler, "restart_service_proc", _outcome)
    monkeypatch.setattr(service_handler, "start_service_proc", _outcome)

    def _wait(name: str, gen: int, *, timeout: float, poll: float = 0.2) -> Any:
        calls["wait"].append((name, gen, timeout))
        return completed

    monkeypatch.setattr(service_handler, "wait_for_service_proc_request", _wait)
    return calls


def _completed(
    *, outcome: str = "restarted", pid: int | None = 222, error: str | None = None
) -> SimpleNamespace:
    return SimpleNamespace(outcome=outcome, pid=pid, error=error)


def test_service_proc_restart_waits_and_prints_pid_transition(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = _proc_request_seams(monkeypatch, completed=_completed())

    with pytest.raises(SystemExit) as exit_info:
        handle_service_command(
            parse_sase_args(["service", "proc", "restart", "scheduler"])
        )

    assert exit_info.value.code == 0
    assert "service proc scheduler restarted: pid 111 -> pid 222" in (
        capsys.readouterr().out
    )
    assert calls["wait"] == [("scheduler", 4, 15.0)]


def test_service_proc_start_no_wait_returns_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = _proc_request_seams(monkeypatch, completed=_completed())

    with pytest.raises(SystemExit) as exit_info:
        handle_service_command(
            parse_sase_args(["service", "proc", "start", "scheduler", "--no-wait"])
        )

    assert exit_info.value.code == 0
    assert "requested service proc scheduler start" in capsys.readouterr().out
    assert calls["wait"] == []


def test_service_proc_restart_timeout_exits_1(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _proc_request_seams(monkeypatch, completed=None)

    with pytest.raises(SystemExit) as exit_info:
        handle_service_command(
            parse_sase_args(["service", "proc", "restart", "scheduler", "-t", "0.5"])
        )

    assert exit_info.value.code == 1
    assert "did not confirm within 0.5s" in capsys.readouterr().err


def test_service_proc_restart_host_down_exits_1_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = _proc_request_seams(monkeypatch, nudged=False, completed=_completed())

    with pytest.raises(SystemExit) as exit_info:
        handle_service_command(
            parse_sase_args(["service", "proc", "restart", "scheduler"])
        )

    assert exit_info.value.code == 1
    assert "not running" in capsys.readouterr().err
    assert calls["wait"] == []


def test_service_proc_restart_not_desired_exits_1(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _proc_request_seams(
        monkeypatch,
        completed=_completed(outcome="not_desired", pid=None, error="is disabled"),
    )

    with pytest.raises(SystemExit) as exit_info:
        handle_service_command(
            parse_sase_args(["service", "proc", "restart", "scheduler"])
        )

    assert exit_info.value.code == 1
    assert "is disabled" in capsys.readouterr().err


def test_service_proc_restart_delay_flag_is_gone_and_wait_flags_parse() -> None:
    parser = create_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["service", "proc", "restart", "scheduler", "--delay", "1"])
    with pytest.raises(SystemExit):
        parser.parse_args(["service", "proc", "restart", "scheduler", "-d", "1"])

    restart_args = parser.parse_args(["service", "proc", "restart", "scheduler"])
    assert restart_args.no_wait is False
    assert restart_args.timeout is None
    assert (
        parser.parse_args(
            ["service", "proc", "restart", "scheduler", "-n", "-t", "3"]
        ).timeout
        == 3.0
    )
    start_args = parser.parse_args(["service", "proc", "start", "scheduler", "-n"])
    assert start_args.no_wait is True
    scheduler_args = parser.parse_args(["scheduler", "restart", "--no-wait"])
    assert scheduler_args.no_wait is True
    scheduler_start = parser.parse_args(["scheduler", "start", "-t", "7"])
    assert scheduler_start.timeout == 7.0


def test_scheduler_restart_routes_through_confirmed_transition(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main.scheduler_handler import handle_scheduler_command

    _proc_request_seams(monkeypatch, completed=_completed())

    with pytest.raises(SystemExit) as exit_info:
        handle_scheduler_command(parse_sase_args(["scheduler", "restart"]))

    assert exit_info.value.code == 0
    assert "service proc scheduler restarted: pid 111 -> pid 222" in (
        capsys.readouterr().out
    )


def test_service_init_yes_agent_refusal_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_refused(**_kwargs: object) -> object:
        return SimpleNamespace(
            ok=False,
            changed=False,
            message=(
                "refusing to capture an agent shell's environment: run "
                "`sase service init --yes` from a login shell instead, or pass "
                "-a/--allow-agent-env to capture this environment deliberately"
            ),
            plan=None,
        )

    monkeypatch.setattr("sase.main.service_handler.apply_service_init", fake_refused)

    with pytest.raises(SystemExit) as exit_info:
        handle_service_command(parse_sase_args(["service", "init", "--yes"]))

    assert exit_info.value.code == 2
