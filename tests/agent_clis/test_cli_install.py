"""Parser and presentation tests for ``sase agent-cli install``."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from sase.agent_clis.cli_install import (
    INSTALL_AGENT_CLI_JSON_SCHEMA_VERSION,
    handle_agent_cli_install_command,
)
from sase.agent_clis.install import (
    AgentCliInstallEntry,
    AgentCliInstallsPlanned,
    InstallScript,
)
from sase.agent_clis.models import (
    AgentCliStatus,
    AgentCliUnknownName,
    AgentCliUpdateResult,
    InstallMethod,
    UpdateResultStatus,
)
from sase.main.parser import create_parser

DIGEST = "a" * 64
SCRIPT_URL = "https://dev.example.test/install.sh"


def _status(name: str = "muse") -> AgentCliStatus:
    return AgentCliStatus(
        name=name,
        display_name="Muse Code",
        binary=name,
        executable=None,
        installed_version=None,
        latest_version=None,
        install_method=InstallMethod.NOT_INSTALLED,
        update_available=False,
        docs_url="https://example.test/muse",
        install_hint=f"run `sase agent-cli install {name}`",
        install_manager=InstallMethod.SCRIPT,
        install_script_url=SCRIPT_URL,
        install_env=(("MUSE_UPGRADE_MODE", "1"),),
    )


def _ready_plan(tmp_path: Path) -> AgentCliInstallsPlanned:
    path = tmp_path / "install.sh"
    path.write_text("echo hi\n")
    return AgentCliInstallsPlanned(
        entries=(
            AgentCliInstallEntry(
                _status(),
                argv=("bash", str(path)),
                env_overlay=(("MUSE_UPGRADE_MODE", "1"),),
                script=InstallScript(
                    url=SCRIPT_URL, path=path, digest=DIGEST, size_bytes=8
                ),
                install_dir="/home/user/.local/bin",
            ),
        )
    )


def _args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "names": ["muse"],
        "force": False,
        "json": False,
        "dry_run": False,
        "offline": False,
        "refresh": False,
        "yes": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _console() -> Console:
    return Console(file=io.StringIO(), width=180, no_color=True)


def _output(console: Console) -> str:
    return console.file.getvalue()  # type: ignore[attr-defined]


def _never_execute(*_args: object, **_kwargs: object) -> tuple[()]:
    raise AssertionError("must not execute an install script")


def test_parser_accepts_short_and_long_install_flags() -> None:
    short = create_parser().parse_args(
        ["agent-cli", "install", "muse", "-f", "-j", "-n", "-o", "-r", "-y"]
    )
    long = create_parser().parse_args(
        [
            "agent-cli",
            "install",
            "muse",
            "--force",
            "--json",
            "--dry-run",
            "--offline",
            "--refresh",
            "--yes",
        ]
    )

    for args in (short, long):
        assert args.agent_cli_subcommand == "install"
        assert args.names == ["muse"]
        assert (args.force, args.json, args.dry_run, args.offline, args.refresh) == (
            True,
            True,
            True,
            True,
            True,
        )
        assert args.yes is True


def test_install_without_names_is_a_usage_error() -> None:
    err = _console()

    code = handle_agent_cli_install_command(
        _args(names=[]),
        err_console=err,
        plan_fn=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("must not plan")
        ),
    )

    assert code == 2
    assert "Specify one or more agent CLIs to install" in _output(err)


def test_unknown_name_is_a_usage_error_with_a_docs_pointer() -> None:
    err = _console()
    plan = AgentCliUnknownName(
        query="mus3", known_names=("codex", "muse"), suggestions=("muse",)
    )

    code = handle_agent_cli_install_command(
        _args(names=["mus3"]), err_console=err, plan_fn=lambda *_a, **_k: plan
    )

    rendered = _output(err)
    assert code == 2
    assert "Unknown agent CLI: mus3" in rendered
    assert "Did you mean: muse?" in rendered
    assert "sase agent-cli list -v" in rendered


def test_dry_run_shows_url_digest_command_and_target_without_executing(
    tmp_path: Path,
) -> None:
    plan = _ready_plan(tmp_path)
    console = _console()

    code = handle_agent_cli_install_command(
        _args(dry_run=True),
        console=console,
        plan_fn=lambda *_a, **_k: plan,
        execute_fn=_never_execute,
    )

    rendered = _output(console)
    assert code == 0
    assert SCRIPT_URL in rendered
    assert DIGEST in rendered
    assert f"MUSE_UPGRADE_MODE=1 bash {tmp_path / 'install.sh'}" in rendered
    assert "/home/user/.local/bin" in rendered
    assert "nothing executed" in rendered
    assert "SASE never edits your shell startup files." in rendered


def test_dry_run_cleans_up_the_fetched_script(tmp_path: Path) -> None:
    plan = _ready_plan(tmp_path)
    script = plan.entries[0].script
    assert script is not None

    handle_agent_cli_install_command(
        _args(dry_run=True),
        console=_console(),
        plan_fn=lambda *_a, **_k: plan,
        execute_fn=_never_execute,
    )

    assert not script.path.exists()


def test_a_failing_execution_still_cleans_up_the_fetched_script(
    tmp_path: Path,
) -> None:
    plan = _ready_plan(tmp_path)
    script = plan.entries[0].script
    assert script is not None

    def explode(*_a: object, **_k: object) -> tuple[()]:
        raise RuntimeError("runner exploded")

    code = handle_agent_cli_install_command(
        _args(yes=True),
        console=_console(),
        err_console=_console(),
        plan_fn=lambda *_a, **_k: plan,
        execute_fn=explode,
    )

    assert code == 1
    assert not script.path.exists()


def test_dry_run_json_carries_the_plan_and_forwards_the_load_flags(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = _ready_plan(tmp_path)
    calls: list[tuple[tuple[str, ...], dict[str, bool]]] = []

    def planner(names: tuple[str, ...], **kwargs: bool) -> AgentCliInstallsPlanned:
        calls.append((names, kwargs))
        return plan

    code = handle_agent_cli_install_command(
        _args(dry_run=True, json=True, force=True, offline=True, refresh=True),
        plan_fn=planner,
        execute_fn=_never_execute,
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert calls == [
        (("muse",), {"force": True, "refresh": True, "offline": True}),
    ]
    assert payload["schema_version"] == INSTALL_AGENT_CLI_JSON_SCHEMA_VERSION
    assert payload["dry_run"] is True
    assert payload["counts"] == {"ready": 1, "skipped": 0, "total": 1}
    entry = payload["agent_clis"][0]
    assert entry["install_script_url"] == SCRIPT_URL
    assert entry["script_sha256"] == DIGEST
    assert entry["env"] == {"MUSE_UPGRADE_MODE": "1"}
    assert entry["ready"] is True


def test_missing_yes_refuses_to_execute_without_a_tty(tmp_path: Path) -> None:
    console, err = _console(), _console()

    code = handle_agent_cli_install_command(
        _args(),
        console=console,
        err_console=err,
        plan_fn=lambda *_a, **_k: _ready_plan(tmp_path),
        execute_fn=_never_execute,
        is_tty_fn=lambda: False,
    )

    assert code == 2
    assert DIGEST in _output(console)
    assert "Re-run with -y|--yes" in _output(err)


def test_json_never_prompts_and_reports_the_confirmation_requirement(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = handle_agent_cli_install_command(
        _args(json=True),
        plan_fn=lambda *_a, **_k: _ready_plan(tmp_path),
        execute_fn=_never_execute,
        is_tty_fn=lambda: True,
        confirm_fn=lambda *_a: (_ for _ in ()).throw(
            AssertionError("must not prompt under --json")
        ),
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert "Re-run with -y|--yes" in payload["error"]
    assert payload["agent_clis"][0]["script_sha256"] == DIGEST


def test_declining_the_interactive_prompt_executes_nothing(tmp_path: Path) -> None:
    err = _console()

    code = handle_agent_cli_install_command(
        _args(),
        console=_console(),
        err_console=err,
        plan_fn=lambda *_a, **_k: _ready_plan(tmp_path),
        execute_fn=_never_execute,
        is_tty_fn=lambda: True,
        confirm_fn=lambda *_a: False,
    )

    assert code == 2
    assert "Aborted" in _output(err)


def test_accepting_the_interactive_prompt_executes_the_plan(tmp_path: Path) -> None:
    executed: list[Any] = []

    code = handle_agent_cli_install_command(
        _args(),
        console=_console(),
        plan_fn=lambda *_a, **_k: _ready_plan(tmp_path),
        execute_fn=lambda plan, **kwargs: executed.append((plan, kwargs)) or (),
        is_tty_fn=lambda: True,
        confirm_fn=lambda *_a: True,
    )

    assert code == 0
    assert executed


def test_a_plan_with_only_skips_needs_no_confirmation() -> None:
    plan = AgentCliInstallsPlanned(
        entries=(AgentCliInstallEntry(_status("codex"), skip_reason="npm-managed"),)
    )
    result = AgentCliUpdateResult(
        name="codex",
        display_name="Codex CLI",
        status=UpdateResultStatus.SKIPPED,
        old_version=None,
        new_version=None,
        command=None,
        docs_url=None,
        reason="npm-managed",
    )
    console = _console()

    code = handle_agent_cli_install_command(
        _args(names=["codex"]),
        console=console,
        plan_fn=lambda *_a, **_k: plan,
        execute_fn=lambda *_a, **_k: (result,),
        is_tty_fn=lambda: False,
    )

    assert code == 0
    assert "skipped" in _output(console)
    assert "npm-managed" in _output(console)


def test_results_report_the_location_path_state_and_digest(tmp_path: Path) -> None:
    result = AgentCliUpdateResult(
        name="muse",
        display_name="Muse Code",
        status=UpdateResultStatus.UPDATED,
        old_version=None,
        new_version="0.1.0-R708.1",
        command=("bash", "/tmp/install.sh"),
        docs_url="https://example.test/muse",
        reason='/home/user/.local/bin is not on PATH; add `export PATH="x"`',
        script_digest=DIGEST,
        install_dir="/home/user/.local/bin",
        install_dir_on_path=False,
    )
    console = _console()

    code = handle_agent_cli_install_command(
        _args(yes=True),
        console=console,
        plan_fn=lambda *_a, **_k: _ready_plan(tmp_path),
        execute_fn=lambda *_a, **_k: (result,),
    )

    rendered = _output(console)
    assert code == 0
    assert "installed" in rendered
    assert "0.1.0-R708.1" in rendered
    assert "/home/user/.local/bin" in rendered
    assert "(not on PATH)" in rendered
    assert DIGEST in rendered


def test_a_failed_install_exits_one_with_output_and_docs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = AgentCliUpdateResult(
        name="muse",
        display_name="Muse Code",
        status=UpdateResultStatus.FAILED,
        old_version=None,
        new_version=None,
        command=("bash", "/tmp/install.sh"),
        docs_url="https://example.test/muse",
        reason="install script failed with exit 3",
        output_tail="no space left on device",
        script_digest=DIGEST,
    )

    code = handle_agent_cli_install_command(
        _args(yes=True, json=True),
        plan_fn=lambda *_a, **_k: _ready_plan(tmp_path),
        execute_fn=lambda *_a, **_k: (result,),
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["schema_version"] == INSTALL_AGENT_CLI_JSON_SCHEMA_VERSION
    assert payload["dry_run"] is False
    assert payload["counts"]["failed"] == 1
    entry = payload["agent_clis"][0]
    assert entry["output_tail"] == "no space left on device"
    assert entry["script_sha256"] == DIGEST
    assert entry["reason"].endswith("https://example.test/muse")
