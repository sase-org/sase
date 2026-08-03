"""Parser and presentation tests for the ``sase agent-cli`` command group."""

from __future__ import annotations

import argparse
import io
import json
from dataclasses import replace
from typing import Any

from rich.console import Console

from sase.agent_clis.cli_list import (
    LIST_AGENT_CLI_JSON_SCHEMA_VERSION,
    handle_agent_cli_list_command,
)
from sase.agent_clis.cli_update import (
    UPDATE_AGENT_CLI_JSON_SCHEMA_VERSION,
    handle_agent_cli_update_command,
)
from sase.agent_clis.models import (
    AgentCliNothingToUpdate,
    AgentCliStatus,
    AgentCliUnknownName,
    AgentCliUpdateEntry,
    AgentCliUpdateResult,
    AgentCliUpdatesReady,
    InstallMethod,
    UpdateResultStatus,
    UpdateStrategy,
)
from sase.main.parser import create_parser, default_list_delegation_notice


def _status(
    name: str = "codex",
    *,
    display_name: str = "Codex CLI",
    method: InstallMethod = InstallMethod.NPM,
    executable: str | None = "/usr/local/bin/codex",
    installed_version: str | None = "1.0.0",
    latest_version: str | None = "2.0.0",
    update_available: bool = True,
    docs_url: str | None = "https://example.test/codex",
) -> AgentCliStatus:
    return AgentCliStatus(
        name=name,
        display_name=display_name,
        binary=name,
        executable=executable,
        installed_version=installed_version,
        latest_version=latest_version,
        install_method=method,
        update_available=update_available,
        docs_url=docs_url,
        install_hint=f"npm install -g {name}",
        package=f"@example/{name}",
        npm_root_writable=True,
    )


def _args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "names": ["codex"],
        "all": False,
        "json": False,
        "dry_run": False,
        "offline": False,
        "refresh": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _console() -> Console:
    return Console(file=io.StringIO(), width=180, no_color=True)


def _output(console: Console) -> str:
    return console.file.getvalue()  # type: ignore[attr-defined]


def test_bare_group_defaults_to_list_and_emits_notice() -> None:
    args = create_parser().parse_args(["agent-cli"])

    assert args.command == "agent-cli"
    assert args.agent_cli_subcommand == "list"
    assert args.json is False
    assert args.offline is False
    assert args.refresh is False
    assert args.verbose is False
    assert default_list_delegation_notice(args) == (
        "No subcommand provided for 'sase agent-cli'; delegating to "
        "'sase agent-cli list'."
    )


def test_parser_accepts_short_and_long_flags() -> None:
    list_short = create_parser().parse_args(
        ["agent-cli", "list", "-j", "-o", "-r", "-v"]
    )
    list_long = create_parser().parse_args(
        [
            "agent-cli",
            "list",
            "--json",
            "--offline",
            "--refresh",
            "--verbose",
        ]
    )
    update_short = create_parser().parse_args(
        ["agent-cli", "update", "-a", "-j", "-n", "-o", "-r"]
    )
    update_long = create_parser().parse_args(
        [
            "agent-cli",
            "update",
            "--all",
            "--json",
            "--dry-run",
            "--offline",
            "--refresh",
        ]
    )

    for args in (list_short, list_long):
        assert (args.json, args.offline, args.refresh, args.verbose) == (
            True,
            True,
            True,
            True,
        )
    for args in (update_short, update_long):
        assert (args.all, args.json, args.dry_run, args.offline, args.refresh) == (
            True,
            True,
            True,
            True,
            True,
        )


def test_list_renders_versions_hint_marker_and_verbose_details() -> None:
    installed = _status()
    missing = _status(
        "qwen",
        display_name="Qwen Code",
        method=InstallMethod.NOT_INSTALLED,
        executable=None,
        installed_version=None,
        latest_version="0.9.0",
        update_available=False,
        docs_url="https://example.test/qwen",
    )
    console = _console()

    code = handle_agent_cli_list_command(
        argparse.Namespace(json=False, offline=False, refresh=False, verbose=True),
        console=console,
        status_fn=lambda **_kwargs: (installed, missing),
    )

    rendered = _output(console)
    assert code == 0
    assert "Codex CLI" in rendered
    assert "1.0.0" in rendered
    assert "2.0.0" in rendered
    assert "↑" in rendered
    assert "not installed" in rendered
    assert "npm install -g qwen" in rendered
    assert "/usr/local/bin/codex" in rendered
    assert "https://example.test/qwen" in rendered


def test_list_json_is_versioned_and_forwards_offline_refresh(capsys: Any) -> None:
    calls: list[dict[str, bool]] = []

    def statuses(**kwargs: bool) -> tuple[AgentCliStatus, ...]:
        calls.append(kwargs)
        return (_status(),)

    code = handle_agent_cli_list_command(
        argparse.Namespace(json=True, offline=True, refresh=True, verbose=False),
        status_fn=statuses,
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert calls == [{"refresh": True, "offline": True}]
    assert payload["schema_version"] == LIST_AGENT_CLI_JSON_SCHEMA_VERSION
    assert payload["counts"] == {
        "installed": 1,
        "not_installed": 0,
        "total": 1,
        "updates_available": 1,
    }
    assert payload["agent_clis"][0]["executable"] == "/usr/local/bin/codex"
    assert payload["agent_clis"][0]["docs_url"] == "https://example.test/codex"


def test_update_without_names_or_all_is_usage_error() -> None:
    err = _console()

    code = handle_agent_cli_update_command(
        _args(names=[]),
        err_console=err,
        plan_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not plan")
        ),
    )

    assert code == 2
    assert "Specify one or more agent CLIs" in _output(err)


def test_unknown_name_is_usage_error_with_docs_pointer() -> None:
    err = _console()
    plan = AgentCliUnknownName(
        query="codez",
        known_names=("claude", "codex"),
        suggestions=("codex",),
    )

    code = handle_agent_cli_update_command(
        _args(names=["codez"]), err_console=err, plan_fn=lambda *_args, **_kwargs: plan
    )

    rendered = _output(err)
    assert code == 2
    assert "Unknown agent CLI: codez" in rendered
    assert "Did you mean: codex?" in rendered
    assert "sase agent-cli list -v" in rendered


def test_dry_run_renders_exact_commands_and_docs_skips_without_execution() -> None:
    ready_status = _status()
    missing_status = replace(
        _status("qwen", display_name="Qwen Code"),
        executable=None,
        installed_version=None,
        install_method=InstallMethod.NOT_INSTALLED,
        update_available=False,
        docs_url="https://example.test/qwen",
    )
    plan = AgentCliUpdatesReady(
        entries=(
            AgentCliUpdateEntry(
                ready_status,
                UpdateStrategy.NPM,
                ("npm", "install", "-g", "@example/codex@latest"),
            ),
            AgentCliUpdateEntry(
                missing_status,
                UpdateStrategy.NONE,
                None,
                "not installed",
            ),
        ),
        all_clis=True,
    )
    console = _console()

    code = handle_agent_cli_update_command(
        _args(names=[], all=True, dry_run=True, offline=True),
        console=console,
        plan_fn=lambda names, **kwargs: plan,
        execute_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("dry run must not execute")
        ),
    )

    rendered = _output(console)
    assert code == 0
    assert "npm install -g @example/codex@latest" in rendered
    assert "not installed" in rendered
    assert "https://example.test/qwen" in rendered
    assert "no commands executed" in rendered


def test_dry_run_json_has_exact_plan_and_forwards_load_flags(capsys: Any) -> None:
    status = _status()
    plan = AgentCliUpdatesReady(
        entries=(
            AgentCliUpdateEntry(
                status,
                UpdateStrategy.NPM,
                ("npm", "install", "-g", "@example/codex@latest"),
            ),
        ),
        all_clis=False,
    )
    calls: list[tuple[tuple[str, ...], dict[str, bool]]] = []

    def planner(names: tuple[str, ...], **kwargs: bool) -> AgentCliUpdatesReady:
        calls.append((names, kwargs))
        return plan

    code = handle_agent_cli_update_command(
        _args(dry_run=True, json=True, offline=True, refresh=True),
        plan_fn=planner,
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert calls == [
        (("codex",), {"all_clis": False, "refresh": True, "offline": True})
    ]
    assert payload["schema_version"] == UPDATE_AGENT_CLI_JSON_SCHEMA_VERSION
    assert payload["dry_run"] is True
    assert payload["counts"] == {"ready": 1, "skipped": 0, "total": 1}
    assert payload["agent_clis"][0]["command"] == [
        "npm",
        "install",
        "-g",
        "@example/codex@latest",
    ]


def test_execute_failure_returns_one_and_renders_docs_and_output() -> None:
    status = _status()
    plan = AgentCliUpdatesReady(
        entries=(AgentCliUpdateEntry(status, UpdateStrategy.NPM, ("npm", "install")),),
        all_clis=False,
    )
    result = AgentCliUpdateResult(
        name="codex",
        display_name="Codex CLI",
        status=UpdateResultStatus.FAILED,
        old_version="1.0.0",
        new_version="1.0.0",
        command=("npm", "install"),
        docs_url=status.docs_url,
        reason="command failed",
        output_tail="permission denied",
    )
    console = _console()

    code = handle_agent_cli_update_command(
        _args(),
        console=console,
        plan_fn=lambda *_args, **_kwargs: plan,
        execute_fn=lambda _plan, **_kwargs: (result,),
    )

    rendered = _output(console)
    assert code == 1
    assert "failed" in rendered
    assert "permission denied" in rendered
    assert "https://example.test/codex" in rendered


def test_execute_json_reports_updated_current_and_skipped_as_success(
    capsys: Any,
) -> None:
    status = replace(_status(), update_available=False, latest_version="1.0.0")
    plan = AgentCliNothingToUpdate(
        entries=(
            AgentCliUpdateEntry(
                status,
                UpdateStrategy.NONE,
                None,
                "already up to date",
            ),
        ),
        all_clis=True,
    )
    result = AgentCliUpdateResult(
        name="codex",
        display_name="Codex CLI",
        status=UpdateResultStatus.ALREADY_CURRENT,
        old_version="1.0.0",
        new_version="1.0.0",
        command=None,
        docs_url=status.docs_url,
        reason="already up to date",
    )

    code = handle_agent_cli_update_command(
        _args(names=[], all=True, json=True),
        plan_fn=lambda *_args, **_kwargs: plan,
        execute_fn=lambda _plan, **_kwargs: (result,),
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["schema_version"] == UPDATE_AGENT_CLI_JSON_SCHEMA_VERSION
    assert payload["dry_run"] is False
    assert payload["counts"] == {
        "updated": 0,
        "already_current": 1,
        "failed": 0,
        "skipped": 0,
    }
    assert payload["agent_clis"][0]["reason"].endswith("https://example.test/codex")
