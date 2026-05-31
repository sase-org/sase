"""Tests for CLI parser help rendering."""

from __future__ import annotations

import argparse

import pytest

from sase.main.parser import create_parser


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
