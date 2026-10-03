"""Coverage for ``sase final status``: parsing, output, and exit codes."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from sase.core.finalizer_run_view import FinalizerNodeView, _RunViewUnselected
from sase.finalizers.cli import handle_final_status
from sase.finalizers.cli_status import _render_status_pretty
from sase.finalizers.config import (
    ConfiguredFinalizerInstance,
    FinalizerConfig,
    FinalizerFieldProvenance,
)
from sase.finalizers.controller import run_finalizers
from sase.llm_provider.commit_finalizer_types import DirtyState
from sase.llm_provider.types import InvokeResult
from sase.main.parser import create_parser
from sase.macro.directives import PromptDirectives


def _config(command: list[str]) -> FinalizerConfig:
    return FinalizerConfig(
        defaults=("local-check",),
        required=(),
        instances={
            "local-check": ConfiguredFinalizerInstance(
                instance_id="local-check",
                provider_ref="builtin@command",
                max_attempts=1,
                config={
                    "command": command,
                    "cwd": "primary",
                    "timeout": "30s",
                    "submission": "none",
                },
                provenance={
                    "use": FinalizerFieldProvenance("test", None),
                },
            )
        },
        provenance={},
    )


def _run_controller_fixture(monkeypatch: pytest.MonkeyPatch, artifacts: Path) -> None:
    """Drive the real controller into *artifacts* with a trivial command."""

    artifacts.mkdir(parents=True, exist_ok=True)
    config = _config([sys.executable, "-c", "print('checked')"])
    monkeypatch.setattr("sase.finalizers.plan.load_finalizer_config", lambda: config)
    monkeypatch.setattr("sase.finalizers.config.load_finalizer_config", lambda: config)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: DirtyState(project_dir=str(artifacts), repos=(), details=""),
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv("SASE_FINAL_TURN_NONCE", "nonce-1")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(artifacts))
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")
    from sase.finalizers.plan import resolve_and_persist_finalizer_plan

    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    result = run_finalizers(
        provider=MagicMock(),
        original_prompt="do work",
        invoke_result=InvokeResult(content="done"),
        model_tier="small",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )
    assert result.content == "done"


def _pretty_console() -> tuple[Console, io.StringIO]:
    buffer = io.StringIO()
    return Console(file=buffer, width=120, force_terminal=True), buffer


def test_status_parser_defaults_and_options() -> None:
    parser = create_parser()
    args = parser.parse_args(["final", "status"])
    assert args.final_subcommand == "status"
    assert args.agent is None
    assert args.artifacts_dir is None
    assert args.format == "pretty"

    args = parser.parse_args(
        ["final", "status", "my-agent", "-d", "/tmp/x", "-f", "json"]
    )
    assert args.agent == "my-agent"
    assert args.artifacts_dir == "/tmp/x"
    assert args.format == "json"


def test_status_help_lists_subcommands_alphabetically(
    capsys: pytest.CapsysFixture,
) -> None:
    parser = create_parser()
    with pytest.raises(SystemExit, match="^0$"):
        parser.parse_args(["final", "-h"])
    listing = capsys.readouterr().out
    show_at = listing.index("\n    show ")
    status_at = listing.index("\n    status ")
    submit_at = listing.index("\n    submit ")
    assert show_at < status_at < submit_at


def test_status_pretty_renders_e2e_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    _run_controller_fixture(monkeypatch, artifacts)
    console, buffer = _pretty_console()

    code = handle_final_status(
        artifacts_dir=str(artifacts), format_name="pretty", console=console
    )

    assert code == 0
    output = buffer.getvalue()
    assert "FINAL" in output
    assert "local-check" in output
    assert "success" in output
    assert "attempt 1" in output
    assert "finalizers/local-check/attempt-1.stdout" in output
    # Colored output in the shared vocabulary, not plain text.
    assert "\x1b[" in output


def test_status_json_matches_projection_verbatim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CapsysFixture,
) -> None:
    artifacts = tmp_path / "artifacts"
    _run_controller_fixture(monkeypatch, artifacts)

    code = handle_final_status(artifacts_dir=str(artifacts), format_name="json")

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"
    assert payload["runs"][0]["disposition"] == "ran"
    # The JSON output is the projection response verbatim: a sentinel
    # binding payload must reach stdout untransformed.
    sentinel: dict[str, Any] = {"schema_version": 1, "custom": ["x"]}
    monkeypatch.setattr(
        "sase.finalizers.cli_status.require_rust_binding",
        lambda _name: lambda _request: dict(sentinel),
    )
    code = handle_final_status(artifacts_dir=str(artifacts), format_name="json")

    assert code == 0
    assert json.loads(capsys.readouterr().out) == sentinel


def test_status_defaults_to_calling_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    _run_controller_fixture(monkeypatch, artifacts)
    monkeypatch.setenv("SASE_AGENT_NAME", "calling-turn")
    console, buffer = _pretty_console()

    code = handle_final_status(format_name="pretty", console=console)

    assert code == 0
    assert "calling-turn" in buffer.getvalue()


def test_status_missing_argument_outside_turn_is_usage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    console, buffer = _pretty_console()

    code = handle_final_status(format_name="pretty", console=console)

    assert code == 2
    assert "SASE_ARTIFACTS_DIR" in buffer.getvalue()


def test_status_unknown_agent_reports_exit_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.agent.names.find_agent_session", lambda _name: None)
    monkeypatch.setattr("sase.agent.names.find_named_agent", lambda _name: None)
    monkeypatch.setattr(
        "sase.scripts._agent_chat_from_name_common.find_agent_session_member",
        lambda _name: None,
    )
    console, buffer = _pretty_console()

    code = handle_final_status("no-such-agent", format_name="pretty", console=console)

    assert code == 1
    assert "unknown agent" in buffer.getvalue()


def test_status_pretty_renders_unselected_section() -> None:
    view = FinalizerNodeView(
        schema_version=1,
        status="idle",
        glyph="○",
        unselected=[
            _RunViewUnselected(
                instance_id="sidecar", reason="not selected for this run"
            )
        ],
    )
    console, buffer = _pretty_console()

    _render_status_pretty(view, label="agent-1", console=console)

    output = buffer.getvalue()
    assert "NOT SELECTED" in output
    assert "sidecar" in output
    assert "not selected for this run" in output


def test_status_artifacts_dir_without_data_reports_exit_1(
    tmp_path: Path,
) -> None:
    console, buffer = _pretty_console()

    code = handle_final_status(
        artifacts_dir=str(tmp_path), format_name="pretty", console=console
    )

    assert code == 1
    assert "no finalizer data" in buffer.getvalue()
