"""Parser contract coverage for ``sase prompt``."""

from __future__ import annotations

from sase.main.parser import create_parser

from ._helpers import _prompt_subparsers


def test_prompt_subcommands_parse_with_short_flags() -> None:
    parser = create_parser()

    list_args = parser.parse_args(
        ["prompt", "list", "-a", "-c", "-j", "-l", "5", "-q", "auth"]
    )
    assert list_args.command == "prompt"
    assert list_args.prompt_subcommand == "list"
    assert list_args.all is True
    assert list_args.cancelled is True
    assert list_args.json is True
    assert list_args.limit == 5
    assert list_args.query == "auth"

    show_args = parser.parse_args(["prompt", "show", "ph_abc123", "-f", "markdown"])
    assert show_args.prompt_subcommand == "show"
    assert show_args.id == "ph_abc123"
    assert show_args.format == "markdown"

    stats_args = parser.parse_args(["prompt", "stats", "-j"])
    assert stats_args.prompt_subcommand == "stats"
    assert stats_args.json is True


def test_prompt_replay_subcommands_parse_with_short_flags() -> None:
    parser = create_parser()

    copy_args = parser.parse_args(["prompt", "copy", "ph_abc123"])
    assert copy_args.prompt_subcommand == "copy"
    assert copy_args.id == "ph_abc123"

    run_args = parser.parse_args(
        ["prompt", "run", "ph_abc123", "-e", "-P", "#gh:bob-cli"]
    )
    assert run_args.prompt_subcommand == "run"
    assert run_args.id == "ph_abc123"
    assert run_args.edit is True
    assert run_args.prefix == "#gh:bob-cli"

    edit_args = parser.parse_args(["prompt", "edit", "ph_abc123"])
    assert edit_args.prompt_subcommand == "edit"
    assert edit_args.id == "ph_abc123"

    select_args = parser.parse_args(
        ["prompt", "select", "-a", "-c", "-e", "-P", "#gh:bob-cli", "-q", "auth"]
    )
    assert select_args.prompt_subcommand == "select"
    assert select_args.all is True
    assert select_args.cancelled is True
    assert select_args.edit is True
    assert select_args.prefix == "#gh:bob-cli"
    assert select_args.query == "auth"


def test_prompt_maintenance_subcommands_parse_with_short_flags() -> None:
    parser = create_parser()

    delete_args = parser.parse_args(["prompt", "delete", "ph_abc123", "-y"])
    assert delete_args.prompt_subcommand == "delete"
    assert delete_args.id == "ph_abc123"
    assert delete_args.yes is True

    doctor_args = parser.parse_args(["prompt", "doctor", "-j"])
    assert doctor_args.prompt_subcommand == "doctor"
    assert doctor_args.json is True

    prune_args = parser.parse_args(
        ["prompt", "prune", "-b", "2026-01-01", "-c", "-d", "-k", "50", "-y"]
    )
    assert prune_args.prompt_subcommand == "prune"
    assert prune_args.before == "2026-01-01"
    assert prune_args.cancelled is True
    assert prune_args.dry_run is True
    assert prune_args.keep == 50
    assert prune_args.yes is True


def test_prompt_export_save_subcommands_parse_with_short_flags() -> None:
    parser = create_parser()

    export_args = parser.parse_args(
        ["prompt", "export", "ph_abc123", "-F", "-m", "-o", "/tmp/p.md"]
    )
    assert export_args.prompt_subcommand == "export"
    assert export_args.id == "ph_abc123"
    assert export_args.force is True
    assert export_args.metadata is True
    assert export_args.out == "/tmp/p.md"
    assert export_args.sdd is False

    save_args = parser.parse_args(
        [
            "prompt",
            "save",
            "ph_abc123",
            "-D",
            "desc",
            "-F",
            "-g",
            "-n",
            "fix-auth",
            "-t",
            "review",
            "-t",
            "auth",
        ]
    )
    assert save_args.prompt_subcommand == "save"
    assert save_args.id == "ph_abc123"
    assert save_args.description == "desc"
    assert save_args.force is True
    assert save_args.global_ is True
    assert save_args.name == "fix-auth"
    assert save_args.tag == ["review", "auth"]

    project_args = parser.parse_args(["prompt", "save", "ph_abc123", "-p", "bob"])
    assert project_args.project == "bob"


def test_prompt_search_subcommand_parses_with_short_flags() -> None:
    parser = create_parser()

    search_args = parser.parse_args(
        [
            "prompt",
            "search",
            "auth",
            "-a",
            "30d",
            "-b",
            "2026-01-01",
            "-c",
            "never",
            "-f",
            "json",
            "-n",
            "5",
            "-s",
            "archive",
            "-t",
            "review",
            "-t",
            "auth",
            "-x",
        ]
    )
    assert search_args.prompt_subcommand == "search"
    assert search_args.query == "auth"
    assert search_args.after == "30d"
    assert search_args.before == "2026-01-01"
    assert search_args.color == "never"
    assert search_args.format == "json"
    assert search_args.limit == 5
    assert search_args.source == "archive"
    assert search_args.tag == ["review", "auth"]
    assert search_args.cancelled is True

    deprecated_alias = parser.parse_args(
        ["prompt", "search", "auth", "--source", "sdd"]
    )
    assert deprecated_alias.source == "sdd"


def test_prompt_search_defaults() -> None:
    parser = create_parser()
    args = parser.parse_args(["prompt", "search", "tui"])
    assert args.color == "auto"
    assert args.format == "compact"
    assert args.limit == 20
    assert args.source == "all"
    assert args.tag is None
    assert args.cancelled is False


def test_prompt_subcommands_are_sorted() -> None:
    assert list(_prompt_subparsers()) == sorted(_prompt_subparsers())


def test_prompt_public_long_options_have_short_aliases() -> None:
    for name, subparser in _prompt_subparsers().items():
        for action in subparser._actions:
            public_long_options = [
                option
                for option in action.option_strings
                if option.startswith("--") and option != "--help"
            ]
            if not public_long_options:
                continue
            short_options = [
                option
                for option in action.option_strings
                if option.startswith("-") and not option.startswith("--")
            ]
            assert short_options, f"prompt {name}: {'/'.join(public_long_options)}"
