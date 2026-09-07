"""Tests for root CLI parser help rendering."""

from __future__ import annotations

import pytest

from sase.main.parser import (
    _format_compact_root_help,
    _print_compact_root_help,
    create_parser,
)
from tests.main.parser_help_helpers import (
    ANSI_RE,
    TtyStringIO,
    compact_common_command_rows,
    compact_common_commands,
    help_subcommand_rows,
    parse_and_capture_help,
    root_subparser_action,
    strip_ansi,
)


def test_root_help_renders_compact_help(capsys: pytest.CaptureFixture[str]) -> None:
    """Root --help renders curated first-contact help."""
    help_text = parse_and_capture_help(["--help"], capsys)
    common_command_rows = compact_common_command_rows(help_text)
    common_commands = compact_common_commands(help_text)

    assert help_text.startswith(
        "usage: sase [-h] [-H] [-f <flag>] [-F <flag>] <command> [args...]\n"
    )
    assert "SASE - Structured Agentic Software Engineering" in help_text
    assert "Global options:" in help_text
    assert "-f, --enable-feature <flag>" in help_text
    assert "-F, --disable-feature <flag>" in help_text
    assert 'sase -f ref_sync_gesture run "..."' in help_text
    assert "Common commands:" in help_text
    assert "Examples:" in help_text
    assert (
        'sase run "#git:home summarize this repository; do not change files"'
        in help_text
    )
    assert "Use `sase --full-help` to show every command." in help_text
    assert common_command_rows == sorted(common_command_rows)
    assert common_commands == {
        "doctor",
        "init",
        "version",
        "ace",
        "run",
        "prompt",
        "agent",
        "machine",
        "memory",
        "patch",
        "bead",
        "project",
        "stitch",
        "workspace",
    }
    assert (
        "Run read-only install, config, provider, project, and state diagnostics."
        in help_text
    )
    assert (
        "Check or initialize config, machines, memory, repositories, and skills."
        in help_text
    )
    assert (
        "Show the exact SASE host, Rust core, and plugin packages loaded by this process."
        in help_text
    )
    assert (
        "Open the interactive control surface for agents, projects, notifications, "
        "automation, and Patches."
    ) in help_text
    assert (
        "Launch or resume a coding-agent run from a prompt, xprompt, workflow, or history."
        in help_text
    )
    assert (
        "Inspect, search, replay, and curate previously submitted agent prompts."
        in help_text
    )
    assert (
        "Inspect loaded memory, review proposals, and audit reference memory activity."
        in help_text
    )


def test_root_help_captured_output_is_plain(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Captured root --help output does not include ANSI escapes."""
    help_text = parse_and_capture_help(["--help"], capsys)

    assert ANSI_RE.search(help_text) is None


def test_root_compact_help_colors_tty_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TTY compact help uses ANSI styling without changing the stripped text."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    parser = create_parser()
    output = TtyStringIO()

    _print_compact_root_help(parser, output)
    rendered_help = output.getvalue()

    assert ANSI_RE.search(rendered_help) is not None
    assert strip_ansi(rendered_help) == _format_compact_root_help(parser)


def test_root_compact_help_honors_no_color_on_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TTY compact help stays plain when color is explicitly disabled."""
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "xterm-256color")
    parser = create_parser()
    output = TtyStringIO()

    _print_compact_root_help(parser, output)
    rendered_help = output.getvalue()

    assert ANSI_RE.search(rendered_help) is None
    assert rendered_help == _format_compact_root_help(parser)


def test_root_short_help_matches_long_help(capsys: pytest.CaptureFixture[str]) -> None:
    """Root -h and --help render identical compact help."""
    long_help = parse_and_capture_help(["--help"], capsys)
    short_help = parse_and_capture_help(["-h"], capsys)

    assert short_help == long_help


def test_root_compact_help_omits_representative_secondary_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Compact root help leaves lower-level commands to --full-help."""
    help_text = parse_and_capture_help(["--help"], capsys)
    common_commands = compact_common_commands(help_text)

    assert {"artifact", "mobile", "telemetry", "questions", "var"}.isdisjoint(
        common_commands
    )


def test_root_full_help_renders_every_top_level_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Root --full-help preserves the exhaustive argparse command inventory."""
    parser = create_parser()
    expected_commands = set(root_subparser_action(parser).choices)

    help_text = parse_and_capture_help(["--full-help"], capsys)
    help_commands = set(help_subcommand_rows(help_text, expected_commands))

    assert "-h, --help" in help_text
    assert "-H, --full-help" in help_text
    assert "--enable-feature" in help_text
    assert "--disable-feature" in help_text
    assert expected_commands <= help_commands
    assert "commit" not in expected_commands
    assert "commit" not in help_commands


def test_root_short_full_help_matches_long_full_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Root -H and --full-help render identical exhaustive help."""
    long_help = parse_and_capture_help(["--full-help"], capsys)
    short_help = parse_and_capture_help(["-H"], capsys)

    assert short_help == long_help


def test_non_compact_root_commands_still_parse() -> None:
    """Commands omitted from compact help remain registered and parseable."""
    parser = create_parser()

    artifact_args = parser.parse_args(["artifact-file", "create", "--path", "out.txt"])
    mobile_args = parser.parse_args(["mobile", "agent-bridge", "list-agents"])
    telemetry_args = parser.parse_args(["telemetry", "status"])
    questions_args = parser.parse_args(["questions", "[]"])
    pipe_args = parser.parse_args(["pipe", "continue the work"])
    var_args = parser.parse_args(["var", "set", "answer=42"])

    assert artifact_args.command == "artifact-file"
    assert mobile_args.command == "mobile"
    assert telemetry_args.command == "telemetry"
    assert questions_args.command == "questions"
    assert pipe_args.command == "pipe"
    assert pipe_args.prompt == "continue the work"
    assert var_args.command == "var"


def test_root_full_help_short_flag_does_not_capture_subcommand_flags() -> None:
    """Subcommand -H flags keep their existing meaning after a subcommand."""
    args = create_parser().parse_args(
        ["mobile", "gateway", "start", "-H", "/tmp/sase-mobile-state"]
    )

    assert args.command == "mobile"
    assert args.mobile_subcommand == "gateway"
    assert args.mobile_gateway_subcommand == "start"
    assert args.state_dir == "/tmp/sase-mobile-state"
