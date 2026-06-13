"""Tests for CLI parser help rendering."""

from __future__ import annotations

import argparse
import re
from io import StringIO

import pytest

from sase.main.parser import (
    _format_compact_root_help,
    _print_compact_root_help,
    create_parser,
)


_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


def _walk_subparser_actions(
    parser: argparse.ArgumentParser, path: tuple[str, ...] = ("sase",)
) -> list[tuple[tuple[str, ...], argparse._SubParsersAction]]:
    actions: list[tuple[tuple[str, ...], argparse._SubParsersAction]] = []
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue

        actions.append((path, action))
        seen_child_parsers: set[int] = set()
        for name, child_parser in action.choices.items():
            child_id = id(child_parser)
            if child_id in seen_child_parsers:
                continue
            seen_child_parsers.add(child_id)
            actions.extend(_walk_subparser_actions(child_parser, (*path, name)))
    return actions


def _parser_for(path: tuple[str, ...]) -> argparse.ArgumentParser:
    parser = create_parser()
    for command in path[1:]:
        subparser_action = next(
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        parser = subparser_action.choices[command]
    return parser


def _help_subcommand_rows(help_text: str, expected_commands: set[str]) -> list[str]:
    commands: list[str] = []
    for line in help_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        command = stripped.split(maxsplit=1)[0]
        if command in expected_commands:
            commands.append(command)
    return commands


def _flat_help(help_text: str) -> str:
    return " ".join(help_text.split())


def _root_subparser_action(
    parser: argparse.ArgumentParser,
) -> argparse._SubParsersAction:
    return next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )


def _parse_and_capture_help(args: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(args)

    assert exc_info.value.code == 0
    return capsys.readouterr().out


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _compact_common_command_rows(help_text: str) -> list[str]:
    commands: list[str] = []
    in_common_commands = False
    for line in help_text.splitlines():
        if line == "Common commands:":
            in_common_commands = True
            continue
        if in_common_commands and not line:
            break
        if in_common_commands:
            commands.append(line.split(maxsplit=1)[0])
    return commands


def _compact_common_commands(help_text: str) -> set[str]:
    return set(_compact_common_command_rows(help_text))


def test_all_subparser_choices_are_sorted() -> None:
    """Every subcommand group keeps usage metavars sorted alphabetically."""
    parser = create_parser()

    for path, action in _walk_subparser_actions(parser):
        commands = list(action.choices)

        assert commands == sorted(commands), " ".join(path)


def test_all_visible_subparser_help_entries_are_sorted() -> None:
    """Every subcommand group renders its help rows sorted alphabetically."""
    parser = create_parser()

    for path, action in _walk_subparser_actions(parser):
        visible_commands = [
            choice_action.dest for choice_action in action._choices_actions
        ]

        assert visible_commands == sorted(visible_commands), " ".join(path)


def test_exact_list_subcommands_default_when_group_is_omitted() -> None:
    """Every command group with an exact ``list`` child parses bare as list."""
    parser = create_parser()
    expected_groups = {
        "sase agents tag",
        "sase amd",
        "sase axe chop",
        "sase axe lumberjack",
        "sase bead",
        "sase chats",
        "sase file",
        "sase file-history",
        "sase memory",
        "sase memory episodes",
        "sase notify",
        "sase plugin",
        "sase sdd",
        "sase skills",
        "sase telemetry",
        "sase workspace",
        "sase xprompt",
    }
    list_groups: set[str] = set()

    for path, action in _walk_subparser_actions(parser):
        if "list" not in action.choices:
            continue

        label = " ".join(path)
        list_groups.add(label)
        omitted_args = parser.parse_args([*path[1:]])
        explicit_args = parser.parse_args([*path[1:], "list"])

        assert getattr(omitted_args, action.dest) == "list", label
        for key, value in vars(explicit_args).items():
            assert hasattr(omitted_args, key), f"{label} missing {key}"
            assert getattr(omitted_args, key) == value, f"{label} default {key}"

    assert expected_groups <= list_groups
    assert "sase agents" not in list_groups


def test_agents_help_renders_sorted_subcommands() -> None:
    """A formerly unsorted help view renders its user-facing rows sorted."""
    agents_parser = _parser_for(("sase", "agents"))
    expected_commands = {"archive", "index", "kill", "names", "show", "status", "tag"}

    help_commands = _help_subcommand_rows(
        agents_parser.format_help(), expected_commands
    )

    assert help_commands == sorted(expected_commands)
    assert "{archive,index,kill,names,show,status,tag}" in agents_parser.format_help()


def test_plan_command_group_parses_subcommands() -> None:
    """``sase plan`` is a command group with list/propose/approve children."""
    parser = create_parser()

    bare_args = parser.parse_args(["plan"])
    list_args = parser.parse_args(["plan", "list"])
    propose_args = parser.parse_args(["plan", "propose", "file.md"])
    approve_args = parser.parse_args(
        [
            "plan",
            "approve",
            "abcdef12",
            "-k",
            "tale",
            "-m",
            "worker",
            "-p",
            "Focus tests",
        ]
    )

    assert bare_args.command == "plan"
    assert bare_args.plan_subcommand == "list"
    assert list_args.plan_subcommand == "list"
    assert propose_args.plan_subcommand == "propose"
    assert propose_args.plan_file == "file.md"
    assert approve_args.plan_subcommand == "approve"
    assert approve_args.selector == "abcdef12"
    assert approve_args.kind == "tale"
    assert approve_args.model == "worker"
    assert approve_args.prompt == "Focus tests"


def test_plan_command_rejects_old_root_plan_file(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``sase plan <file>`` is no longer accepted; use ``propose``."""
    parser = create_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["plan", "file.md"])

    assert exc_info.value.code == 2
    stderr = capsys.readouterr().err
    assert "invalid choice" in stderr
    assert "propose" in stderr


def test_plan_help_renders_sorted_subcommands() -> None:
    """``sase plan --help`` lists child commands alphabetically."""
    plan_parser = _parser_for(("sase", "plan"))
    expected_commands = {"approve", "list", "propose"}

    help_commands = _help_subcommand_rows(plan_parser.format_help(), expected_commands)
    help_text = plan_parser.format_help()

    assert help_commands == sorted(expected_commands)
    assert "With no subcommand, `sase plan` defaults to `sase plan list`." in help_text
    assert "sase plan propose sase_plan_feature.md" in help_text


def test_plan_subcommand_help_is_complete() -> None:
    """Plan child help documents public options and examples."""
    approve_help = _parser_for(("sase", "plan", "approve")).format_help()
    list_help = _parser_for(("sase", "plan", "list")).format_help()
    propose_help = _parser_for(("sase", "plan", "propose")).format_help()

    assert "{approve,commit,epic,legend,tale}" in approve_help
    assert "-k {approve,commit,epic,legend,tale}" in approve_help
    assert "--kind {approve,commit,epic,legend,tale}" in approve_help
    assert "-m MODEL" in approve_help
    assert "--model MODEL" in approve_help
    assert "-p PROMPT" in approve_help
    assert "--prompt PROMPT" in approve_help
    assert "sase plan approve abcdef12 --kind tale --prompt 'Focus tests'" in (
        approve_help
    )
    assert "-j" in list_help
    assert "--json" in list_help
    assert "sase plan list --json" in list_help
    assert "PLAN_FILE" in propose_help
    assert "sase plan propose sase_plan_feature.md" in propose_help


def test_plan_public_long_options_have_short_aliases() -> None:
    """Every public long option under ``sase plan`` has a short alias."""
    for path in (
        ("sase", "plan", "approve"),
        ("sase", "plan", "list"),
        ("sase", "plan", "propose"),
    ):
        parser = _parser_for(path)
        for action in parser._actions:
            long_options = [
                option for option in action.option_strings if option.startswith("--")
            ]
            public_long_options = [
                option for option in long_options if option != "--help"
            ]
            if not public_long_options:
                continue

            short_options = [
                option
                for option in action.option_strings
                if option.startswith("-") and not option.startswith("--")
            ]
            assert short_options, " ".join((*path, "/".join(public_long_options)))


def test_root_help_renders_compact_help(capsys: pytest.CaptureFixture[str]) -> None:
    """Root --help renders curated first-contact help."""
    help_text = _parse_and_capture_help(["--help"], capsys)
    common_command_rows = _compact_common_command_rows(help_text)
    common_commands = _compact_common_commands(help_text)

    assert help_text.startswith("usage: sase [-h] [-H] <command> [args...]\n")
    assert "SASE - Structured Agentic Software Engineering" in help_text
    assert "Common commands:" in help_text
    assert "Examples:" in help_text
    assert (
        'sase run "#cd:$(pwd) summarize this repository; do not change files"'
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
        "agents",
        "memory",
        "bead",
        "project",
        "workspace",
    }
    assert (
        "Run read-only install, config, provider, project, and state diagnostics."
        in help_text
    )
    assert "Check or initialize AGENTS.md, memory, SDD guides, and skills." in help_text
    assert (
        "Show the exact SASE host, Rust core, and plugin packages loaded by this process."
        in help_text
    )
    assert (
        "Open the interactive control surface for agents, projects, notifications, "
        "automation, and ChangeSpecs."
    ) in help_text
    assert (
        "Launch or resume a coding-agent run from a prompt, xprompt, workflow, or history."
        in help_text
    )
    assert (
        "Inspect loaded memory, review proposals, and audit long-term memory activity."
        in help_text
    )


def test_root_help_captured_output_is_plain(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Captured root --help output does not include ANSI escapes."""
    help_text = _parse_and_capture_help(["--help"], capsys)

    assert _ANSI_RE.search(help_text) is None


def test_root_compact_help_colors_tty_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TTY compact help uses ANSI styling without changing the stripped text."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    parser = create_parser()
    output = _TtyStringIO()

    _print_compact_root_help(parser, output)
    rendered_help = output.getvalue()

    assert _ANSI_RE.search(rendered_help) is not None
    assert _strip_ansi(rendered_help) == _format_compact_root_help(parser)


def test_root_compact_help_honors_no_color_on_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TTY compact help stays plain when color is explicitly disabled."""
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "xterm-256color")
    parser = create_parser()
    output = _TtyStringIO()

    _print_compact_root_help(parser, output)
    rendered_help = output.getvalue()

    assert _ANSI_RE.search(rendered_help) is None
    assert rendered_help == _format_compact_root_help(parser)


def test_root_short_help_matches_long_help(capsys: pytest.CaptureFixture[str]) -> None:
    """Root -h and --help render identical compact help."""
    long_help = _parse_and_capture_help(["--help"], capsys)
    short_help = _parse_and_capture_help(["-h"], capsys)

    assert short_help == long_help


def test_root_compact_help_omits_representative_secondary_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Compact root help leaves lower-level commands to --full-help."""
    help_text = _parse_and_capture_help(["--help"], capsys)
    common_commands = _compact_common_commands(help_text)

    assert {"artifact", "mobile", "telemetry", "questions", "var"}.isdisjoint(
        common_commands
    )


def test_root_full_help_renders_every_top_level_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Root --full-help preserves the exhaustive argparse command inventory."""
    parser = create_parser()
    expected_commands = set(_root_subparser_action(parser).choices)

    help_text = _parse_and_capture_help(["--full-help"], capsys)
    help_commands = set(_help_subcommand_rows(help_text, expected_commands))

    assert "-h, --help" in help_text
    assert "-H, --full-help" in help_text
    assert expected_commands <= help_commands


def test_root_short_full_help_matches_long_full_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Root -H and --full-help render identical exhaustive help."""
    long_help = _parse_and_capture_help(["--full-help"], capsys)
    short_help = _parse_and_capture_help(["-H"], capsys)

    assert short_help == long_help


def test_non_compact_root_commands_still_parse() -> None:
    """Commands omitted from compact help remain registered and parseable."""
    parser = create_parser()

    artifact_args = parser.parse_args(["artifact", "create", "--path", "out.txt"])
    mobile_args = parser.parse_args(["mobile", "agent-bridge", "list-agents"])
    telemetry_args = parser.parse_args(["telemetry", "status"])
    questions_args = parser.parse_args(["questions", "[]"])
    var_args = parser.parse_args(["var", "set", "answer=42"])

    assert artifact_args.command == "artifact"
    assert mobile_args.command == "mobile"
    assert telemetry_args.command == "telemetry"
    assert questions_args.command == "questions"
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


def test_run_help_shows_prompt_positional_and_beginner_examples() -> None:
    """``sase run --help`` advertises the prompt and first-run examples."""
    run_help = _parser_for(("sase", "run")).format_help()
    args = create_parser().parse_args(["run", "hello"])

    assert "usage: sase run [-h] [-d] [-l] [-r [CONTINUE_HISTORY]] [PROMPT]" in run_help
    assert "PROMPT" in run_help
    assert (
        'sase run "#cd:$(pwd) summarize what this repository does; do not change files"'
        in run_help
    )
    assert (
        'sase run -d "#cd:$(pwd) inspect pending work; do not change files"' in run_help
    )
    assert "sase agents status" in run_help
    assert args.prompt == "hello"


def test_memory_help_marks_primary_command_and_init_alias() -> None:
    """Memory help text points users to the new primary command surface."""
    memory_help = _flat_help(_parser_for(("sase", "memory")).format_help())
    memory_init_help = _flat_help(_parser_for(("sase", "memory", "init")).format_help())
    memory_list_help = _flat_help(_parser_for(("sase", "memory", "list")).format_help())
    memory_read_help = _flat_help(_parser_for(("sase", "memory", "read")).format_help())
    memory_write_help = _flat_help(
        _parser_for(("sase", "memory", "write")).format_help()
    )
    memory_review_help = _flat_help(
        _parser_for(("sase", "memory", "review")).format_help()
    )
    memory_log_help = _flat_help(_parser_for(("sase", "memory", "log")).format_help())
    memory_episodes_help = _flat_help(
        _parser_for(("sase", "memory", "episodes")).format_help()
    )
    init_alias_help = _flat_help(_parser_for(("sase", "init", "memory")).format_help())

    assert "`sase memory list`" in memory_help
    assert "{episodes,init,list,log,read,review,write}" in memory_help
    assert "sase memory episodes build -n <agent>" in memory_help
    assert "sase memory read long/generated_skills.md --reason" in memory_help
    assert "sase memory write --title" in memory_help
    assert "sase memory review --list" in memory_help
    assert "sase memory review mem-20260523-142233-a1b2c3d4 --edit" in memory_help
    assert "sase memory log --include proposals" in memory_help
    assert "sase memory log --path long/generated_skills.md" in memory_help
    assert "sase memory log --id <read-id>" in memory_help
    assert "loaded, referenced, available, and missing memory files" in memory_help
    assert "`sase init memory` is a compatibility alias" in memory_init_help
    assert "loaded @ references" in memory_list_help
    assert "referenced-only plain memory paths" in memory_list_help
    assert "memory/long markdown file" in memory_read_help
    assert "falling back to ~/memory/long" in memory_read_help
    assert "--reason REASON" in memory_read_help
    assert "Need generated skill context" in memory_read_help
    assert "--evidence EVIDENCE" in memory_write_help
    assert "--manual-author NAME" in memory_write_help
    assert "--notify" in memory_write_help
    assert "never modifies canonical memory/long files" in memory_write_help
    assert "--approve" in memory_review_help
    assert "--reject" in memory_review_help
    assert "--edited-file PATH" in memory_review_help
    assert "--path MEMORY_PATH" in memory_log_help
    assert "--agent AGENT_NAME" in memory_log_help
    assert "--id READ_ID" in memory_log_help
    assert "--include KIND" in memory_log_help
    assert "sase memory log --id <read-id>" in memory_log_help
    assert (
        "{auto,build,doctor,export,list,recall,show,status,verify}"
        in memory_episodes_help
    )
    assert "sase memory episodes export -s 2026-05-19" in memory_episodes_help
    assert 'sase memory episodes recall -q "retry feedback"' in memory_episodes_help
    assert "Compatibility alias for `sase memory init`" in init_alias_help


def test_init_and_git_namespace_parsers() -> None:
    """New init and git namespaces parse their migrated leaf commands."""
    parser = create_parser()

    amd_args = parser.parse_args(["init", "amd", "--check"])
    assert amd_args.command == "init"
    assert amd_args.init_subcommand == "amd"
    assert amd_args.check is True

    memory_args = parser.parse_args(["init", "memory"])
    assert memory_args.command == "init"
    assert memory_args.init_subcommand == "memory"
    assert memory_args.no_commit is False

    memory_no_commit_args = parser.parse_args(["init", "memory", "--no-commit"])
    assert memory_no_commit_args.command == "init"
    assert memory_no_commit_args.init_subcommand == "memory"
    assert memory_no_commit_args.no_commit is True

    sdd_args = parser.parse_args(["init", "sdd", "-p", "sdd"])
    assert sdd_args.command == "init"
    assert sdd_args.init_subcommand == "sdd"
    assert sdd_args.path == "sdd"

    init_args = parser.parse_args(
        ["init", "skills", "--dry-run", "--provider", "codex"]
    )
    assert init_args.command == "init"
    assert init_args.init_subcommand == "skills"
    assert init_args.dry_run is True
    assert init_args.provider == "codex"

    git_args = parser.parse_args(
        [
            "git",
            "init",
            "demo",
            "--bare-dir",
            "/tmp/demo.git",
            "--clone-dir",
            "/tmp/demo",
            "--existing",
            "/tmp/existing.git",
        ]
    )
    assert git_args.command == "git"
    assert git_args.git_subcommand == "init"
    assert git_args.project_name == "demo"
    assert git_args.bare_dir == "/tmp/demo.git"
    assert git_args.clone_dir == "/tmp/demo"
    assert git_args.existing == "/tmp/existing.git"


def test_legacy_init_commands_are_rejected() -> None:
    """The migrated legacy top-level commands are no longer accepted."""
    parser = create_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["init-skills", "--dry-run"])

    with pytest.raises(SystemExit):
        parser.parse_args(["init-git", "demo"])
