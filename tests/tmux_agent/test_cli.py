"""Dispatcher tests for ``sase tmux-agent``."""

from __future__ import annotations

import argparse
from dataclasses import replace
import io
import json
from pathlib import Path
from typing import Any

from rich.console import Console

from sase.config.tmux_agent import TmuxAgentConfig
from sase.llm_provider.types import LLMInvocationError
from sase.tmux_agent.cli import (
    OUTSIDE_TMUX_MESSAGE,
    TMUX_AGENT_JSON_SCHEMA_VERSION,
    TMUX_MISSING_MESSAGE,
    handle_tmux_agent_cli,
)
from sase.tmux_agent.launch import TmuxAgentLaunch, TmuxAgentLaunchError
from sase.tmux_agent.models import TmuxAgentCatalog

from .fakes import FakeTmuxRunner, completed, make_catalog, make_entry


def _args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "provider": None,
        "directory": None,
        "effort": None,
        "json": False,
        "list": False,
        "dry_run": False,
        "refresh": False,
        "safe": False,
        "verbose": False,
        "renumber": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _console() -> Console:
    return Console(file=io.StringIO(), width=180, no_color=True)


def _output(console: Console) -> str:
    return console.file.getvalue()  # type: ignore[attr-defined]


def _catalog(*entries: Any, directory: str = "/tmp/project") -> TmuxAgentCatalog:
    if not entries:
        entries = (
            make_entry(
                "claude",
                display_name="Claude Code",
                vendor="Anthropic",
                color="#D97757",
                argv=("claude", "--dangerously-skip-permissions"),
            ),
        )
    return make_catalog(entries, directory=directory)


def _run(
    args: argparse.Namespace,
    *,
    catalog: TmuxAgentCatalog | None = None,
    **kwargs: Any,
) -> int:
    built = catalog or _catalog()
    kwargs.setdefault("catalog_fn", lambda **_unused: built)
    kwargs.setdefault("config_fn", TmuxAgentConfig)
    kwargs.setdefault("runner", FakeTmuxRunner())
    kwargs.setdefault("tmux_available_fn", lambda: True)
    kwargs.setdefault("inside_tmux_fn", lambda env=None: True)
    kwargs.setdefault("cwd_fn", lambda: "/cwd")
    return handle_tmux_agent_cli(args, **kwargs)


def test_list_renders_accent_names_status_and_summary() -> None:
    console = _console()
    catalog = _catalog(
        make_entry(
            "claude",
            display_name="Claude Code",
            vendor="Anthropic",
            key="c",
        ),
        make_entry(
            "codex",
            display_name="Codex",
            vendor="OpenAI",
            key="x",
            installed=False,
            install_hint="npm i -g @openai/codex",
        ),
        directory="/work",
    )

    code = _run(_args(list=True), catalog=catalog, console=console)

    assert code == 0
    text = _output(console)
    assert "tmux Agent" in text
    assert "Claude Code" in text
    assert "Codex" in text
    assert "ready" in text
    assert "not installed" in text
    assert "1/2 installed" in text
    assert "default: claude" in text
    assert "/work" in text


def test_list_marks_hard_disable_as_routing_disabled_and_soft_as_soft() -> None:
    from sase.llm_provider.provider_disable import (
        PROVIDER_DISABLE_MODE_HARD,
        PROVIDER_DISABLE_MODE_SOFT,
        TemporaryProviderDisable,
    )

    console = _console()
    catalog = _catalog(
        make_entry(
            "claude",
            display_name="Claude Code",
            key="c",
            routing_disabled=TemporaryProviderDisable(
                version=2,
                provider="claude",
                created_at=0.0,
                expires_at=None,
                source="test",
                mode=PROVIDER_DISABLE_MODE_HARD,
            ),
        ),
        make_entry(
            "codex",
            display_name="Codex",
            key="x",
            routing_disabled=TemporaryProviderDisable(
                version=2,
                provider="codex",
                created_at=0.0,
                expires_at=None,
                source="test",
                mode=PROVIDER_DISABLE_MODE_SOFT,
            ),
        ),
        directory="/work",
    )

    code = _run(_args(list=True), catalog=catalog, console=console)

    assert code == 0
    text = _output(console)
    assert "routing disabled" in text
    assert "soft" in text
    assert "ready" not in text


def test_list_verbose_adds_path_command_and_hint() -> None:
    console = _console()
    catalog = _catalog(
        make_entry(
            "codex",
            display_name="Codex",
            installed=False,
            install_hint="npm i -g @openai/codex",
            argv=("codex",),
        )
    )

    code = _run(_args(list=True, verbose=True), catalog=catalog, console=console)

    assert code == 0
    text = _output(console)
    assert "npm i -g @openai/codex" in text
    assert "codex" in text


def test_json_catalog_envelope_keys_and_schema_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog = _catalog()

    code = _run(_args(json=True), catalog=catalog)
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["schema_version"] == TMUX_AGENT_JSON_SCHEMA_VERSION
    assert payload["default_provider"] == "claude"
    assert payload["counts"]["total"] == 1
    assert payload["entries"][0]["provider"] == "claude"
    assert payload["entries"][0]["command"].startswith("claude")
    assert "argv" in payload["entries"][0]
    assert "bypass" in payload["entries"][0]


def test_json_catalog_counts_only_hard_disables_as_routing_disabled(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.llm_provider.provider_disable import (
        PROVIDER_DISABLE_MODE_HARD,
        PROVIDER_DISABLE_MODE_SOFT,
        TemporaryProviderDisable,
    )

    catalog = _catalog(
        make_entry(
            "claude",
            routing_disabled=TemporaryProviderDisable(
                version=2,
                provider="claude",
                created_at=0.0,
                expires_at=None,
                source="test",
                mode=PROVIDER_DISABLE_MODE_HARD,
            ),
        ),
        make_entry(
            "codex",
            routing_disabled=TemporaryProviderDisable(
                version=2,
                provider="codex",
                created_at=0.0,
                expires_at=None,
                source="test",
                mode=PROVIDER_DISABLE_MODE_SOFT,
            ),
        ),
    )

    code = _run(_args(json=True), catalog=catalog)
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["counts"]["routing_disabled"] == 1
    by_provider = {entry["provider"]: entry for entry in payload["entries"]}
    assert by_provider["claude"]["routing_disabled"]["mode"] == "hard"
    assert by_provider["codex"]["routing_disabled"]["mode"] == "soft"


def test_dry_run_prints_window_directory_env_and_command() -> None:
    console = _console()
    catalog = _catalog(
        make_entry(
            "claude",
            argv=("claude", "--dangerously-skip-permissions"),
            env=(("EDITOR", "nvim"),),
        )
    )
    runner = FakeTmuxRunner(windows=((1, "ai"),))

    code = _run(
        _args(provider="claude", dry_run=True),
        catalog=catalog,
        console=console,
        runner=runner,
    )

    assert code == 0
    text = _output(console)
    assert "window: ai2" in text
    assert "directory: /tmp/project" in text
    assert "env: EDITOR=nvim" in text
    assert "command: claude --dangerously-skip-permissions" in text


def test_dry_run_json_plan(capsys: pytest.CaptureFixture[str]) -> None:
    catalog = _catalog(make_entry("claude", argv=("claude",)))

    code = _run(_args(provider="claude", dry_run=True, json=True), catalog=catalog)
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["schema_version"] == TMUX_AGENT_JSON_SCHEMA_VERSION
    assert payload["dry_run"] is True
    assert payload["provider"] == "claude"
    assert payload["window_name"] == "ai"
    assert payload["directory"] == "/tmp/project"
    assert payload["command"] == "claude"
    assert payload["argv"] == ["claude"]


def test_dry_run_uses_default_provider_when_omitted() -> None:
    console = _console()
    catalog = _catalog(make_entry("claude", argv=("claude", "--safe-default")))

    code = _run(_args(dry_run=True), catalog=catalog, console=console)

    assert code == 0
    assert "command: claude --safe-default" in _output(console)


def test_direct_launch_prints_scriptable_window_and_provider(
    capsys: pytest.CaptureFixture[str],
) -> None:
    launched: list[object] = []

    def launch_fn(entry: object, **_kwargs: object) -> TmuxAgentLaunch:
        launched.append(entry)
        return TmuxAgentLaunch(
            window_name="ai2",
            channel="ch",
            argv=("claude",),
            directory="/tmp/project",
        )

    code = _run(_args(provider="claude"), launch_fn=launch_fn)
    out = capsys.readouterr().out

    assert code == 0
    assert launched
    assert "sase_tmux_agent_window=ai2" in out
    assert "sase_tmux_agent_provider=claude" in out


def test_unknown_provider_lists_known_and_suggests_close_match(
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog = _catalog(make_entry("claude"), make_entry("codex"))

    code = _run(_args(provider="claud"), catalog=catalog)
    err = capsys.readouterr().err

    assert code == 2
    assert "unknown provider 'claud'" in err
    assert "known: claude, codex" in err
    assert "Did you mean: claude?" in err


def test_not_installed_provider_exits_one_with_hint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog = _catalog(
        make_entry(
            "claude",
            display_name="Claude Code",
            installed=False,
            install_hint="npm i -g @anthropic-ai/claude-code",
        )
    )

    code = _run(_args(provider="claude"), catalog=catalog)
    err = capsys.readouterr().err

    assert code == 1
    assert "Claude Code is not installed" in err
    assert "npm i -g @anthropic-ai/claude-code" in err


def test_outside_tmux_prints_actionable_error_and_the_list(
    capsys: pytest.CaptureFixture[str],
) -> None:
    console = _console()

    code = _run(
        _args(),
        console=console,
        inside_tmux_fn=lambda env=None: False,
    )
    err = capsys.readouterr().err

    assert code == 2
    assert err.strip() == OUTSIDE_TMUX_MESSAGE
    assert "tmux Agent" in _output(console)
    assert "Claude Code" in _output(console)


def test_tmux_missing_exits_two(capsys: pytest.CaptureFixture[str]) -> None:
    code = _run(_args(), tmux_available_fn=lambda: False)
    err = capsys.readouterr().err

    assert code == 2
    assert err.strip() == TMUX_MISSING_MESSAGE


def test_menu_path_uses_injected_runner() -> None:
    seen: list[object] = []

    def menu_fn(catalog: TmuxAgentCatalog, *, runner: object, title: str) -> object:
        seen.append((catalog, runner, title))
        return completed(["tmux", "display-menu"])

    runner = FakeTmuxRunner()
    code = _run(_args(), menu_fn=menu_fn, runner=runner)

    assert code == 0
    assert seen[0][1] is runner
    assert seen[0][2] == "tmux Agent"


def test_menu_failure_reports_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    def menu_fn(*_args: object, **_kwargs: object) -> object:
        return completed(["tmux", "display-menu"], returncode=1, stderr="no client\n")

    code = _run(_args(), menu_fn=menu_fn)
    err = capsys.readouterr().err

    assert code == 2
    assert "tmux display-menu failed: no client" in err


def test_renumber_is_silent_and_never_fails(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[object] = []

    def renumber_fn(**kwargs: object) -> int:
        calls.append(kwargs)
        raise RuntimeError("tmux vanished")

    code = _run(_args(renumber=True), renumber_fn=renumber_fn)
    captured = capsys.readouterr()

    assert code == 0
    assert calls
    assert captured.out == ""
    assert captured.err == ""


def test_refresh_runs_before_catalog_build() -> None:
    order: list[str] = []

    def refresh_fn() -> None:
        order.append("refresh")

    def catalog_fn(*, directory: str, **_unused: object) -> TmuxAgentCatalog:
        order.append("catalog")
        return replace(_catalog(), directory=directory)

    code = _run(
        _args(list=True, refresh=True),
        catalog_fn=catalog_fn,
        refresh_fn=refresh_fn,
    )

    assert code == 0
    assert order == ["refresh", "catalog"]


def test_safe_and_effort_are_applied_before_launch() -> None:
    seen: list[object] = []

    def override_fn(
        entry: object, *, explicit_effort: str | None, safe: bool
    ) -> object:
        assert explicit_effort == "max"
        assert safe is True
        return replace(
            entry,  # type: ignore[arg-type]
            argv=("claude", "--effort", "max"),
            bypass=False,
        )

    def launch_fn(entry: object, **_kwargs: object) -> TmuxAgentLaunch:
        seen.append(entry)
        return TmuxAgentLaunch(
            window_name="ai",
            channel="ch",
            argv=("claude", "--effort", "max"),
            directory="/tmp/project",
        )

    code = _run(
        _args(provider="claude", effort="max", safe=True),
        override_fn=override_fn,
        launch_fn=launch_fn,
    )

    assert code == 0
    assert seen[0].argv == ("claude", "--effort", "max")  # type: ignore[attr-defined]
    assert seen[0].bypass is False  # type: ignore[attr-defined]


def test_explicit_unsupported_effort_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def override_fn(*_args: object, **_kwargs: object) -> object:
        raise LLMInvocationError("claude does not support 'max'")

    code = _run(_args(provider="claude", effort="max"), override_fn=override_fn)
    err = capsys.readouterr().err

    assert code == 2
    assert "claude does not support 'max'" in err


def test_dir_flag_wins_over_pane_and_cwd() -> None:
    seen: list[str] = []

    def catalog_fn(*, directory: str, **_unused: object) -> TmuxAgentCatalog:
        seen.append(directory)
        return replace(_catalog(), directory=directory)

    runner = FakeTmuxRunner(pane_dir="/pane")
    code = _run(
        _args(list=True, directory="~/project"),
        catalog_fn=catalog_fn,
        runner=runner,
        cwd_fn=lambda: "/cwd",
    )

    assert code == 0
    assert seen == [str(Path("~/project").expanduser())]


def test_directory_defaults_to_pane_then_cwd() -> None:
    seen: list[str] = []

    def catalog_fn(*, directory: str, **_unused: object) -> TmuxAgentCatalog:
        seen.append(directory)
        return replace(_catalog(), directory=directory)

    runner = FakeTmuxRunner(pane_dir="/from-pane")
    _run(_args(list=True), catalog_fn=catalog_fn, runner=runner)
    _run(
        _args(list=True),
        catalog_fn=catalog_fn,
        runner=runner,
        inside_tmux_fn=lambda env=None: False,
        cwd_fn=lambda: "/from-cwd",
    )

    assert seen == ["/from-pane", "/from-cwd"]
