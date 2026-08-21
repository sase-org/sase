"""Tests for sase.completion.build against the real sase argparse tree."""

from __future__ import annotations

from collections.abc import Iterator

from sase.completion.build import build_spec
from sase.completion.kinds import ValueKind
from sase.completion.model import CommandSpec
from sase.main.parser import create_parser


def _all_commands(root: CommandSpec) -> Iterator[CommandSpec]:
    yield root
    for child in root.subcommands:
        yield from _all_commands(child)


def _by_path(root: CommandSpec, path: tuple[str, ...]) -> CommandSpec:
    return next(command for command in _all_commands(root) if command.path == path)


def test_alias_collapses_changespec_into_patch() -> None:
    spec = build_spec()
    names = [
        command.name
        for command in _all_commands(spec.root)
        if command.path == ("patch",)
    ]
    assert names == ["patch"]

    patch = _by_path(spec.root, ("patch",))
    assert patch.aliases == ("changespec",)
    assert "changespec" not in {command.name for command in _all_commands(spec.root)}


def test_hidden_subcommands_are_absent() -> None:
    spec = build_spec()
    names = {command.name for command in _all_commands(spec.root)}
    assert "helper-bridge" not in names
    assert "bgcmd-launch" not in names
    assert "_supervise" not in names

    editor = _by_path(spec.root, ("editor",))
    assert editor.subcommands == ()


def test_mutex_groups_found() -> None:
    spec = build_spec()
    total = sum(len(command.mutex_groups) for command in _all_commands(spec.root))
    assert total == 15


def test_glossary_del_term_is_kinded_and_add_term_is_not() -> None:
    spec = build_spec()
    del_cmd = _by_path(spec.root, ("glossary", "del"))
    del_term = next(
        positional for positional in del_cmd.positionals if positional.dest == "term"
    )
    assert del_term.kind is ValueKind.GLOSSARY

    add_cmd = _by_path(spec.root, ("glossary", "add"))
    add_term = next(
        positional for positional in add_cmd.positionals if positional.dest == "term"
    )
    add_definition = next(
        positional
        for positional in add_cmd.positionals
        if positional.dest == "definition"
    )
    assert add_term.kind is None
    assert add_definition.kind is None


def test_kind_resolution_precedence_on_real_tree() -> None:
    spec = build_spec()
    show = _by_path(spec.root, ("bead", "show"))
    id_positional = next(p for p in show.positionals if p.dest == "id")
    assert id_positional.kind is ValueKind.BEAD


def test_flag_key_positionals_are_flag_kinded() -> None:
    spec = build_spec()
    flag_group = _by_path(spec.root, ("flag",))
    assert [child.name for child in flag_group.subcommands] == [
        "disable",
        "enable",
        "list",
        "new",
        "show",
    ]
    for name in ("disable", "enable", "new", "show"):
        command = _by_path(spec.root, ("flag", name))
        flag_key = next(
            positional
            for positional in command.positionals
            if positional.dest == "flag_key"
        )
        assert flag_key.kind is ValueKind.FLAG, name


def test_default_list_child_recorded() -> None:
    spec = build_spec()
    bead = _by_path(spec.root, ("bead",))
    assert bead.default_child == "list"


def test_root_help_actions_present() -> None:
    spec = build_spec()
    strings = {s for option in spec.root.options for s in option.strings}
    assert {"-h", "--help"} <= strings
    assert {"-H", "--full-help"} <= strings
    assert {"-f", "--enable-feature"} <= strings
    assert {"-F", "--disable-feature"} <= strings


def test_subparser_auto_help_option_present() -> None:
    spec = build_spec()
    bead = _by_path(spec.root, ("bead",))
    strings = {s for option in bead.options for s in option.strings}
    assert "-h" in strings


def test_remainder_positional_marked() -> None:
    spec = build_spec()
    proc_run = _by_path(spec.root, ("proc", "run"))
    assert any(p.is_remainder for p in proc_run.positionals)


def test_static_choices_need_no_kind() -> None:
    spec = build_spec()
    show = _by_path(spec.root, ("bead", "show"))
    format_option = next(option for option in show.options if option.dest == "format")
    assert format_option.choices is not None
    assert format_option.kind is None


def test_suppressed_option_is_kept_and_flagged_hidden() -> None:
    spec = build_spec()
    commit = _by_path(spec.root, ("commit",))
    file_option = next(option for option in commit.options if option.dest == "file")
    assert file_option.hidden is True


def test_visible_option_is_not_flagged_hidden() -> None:
    spec = build_spec()
    show = _by_path(spec.root, ("bead", "show"))
    format_option = next(option for option in show.options if option.dest == "format")
    assert format_option.hidden is False


def test_no_summary_exceeds_sixty_characters() -> None:
    spec = build_spec()
    for command in _all_commands(spec.root):
        assert len(command.summary) <= 60
        for option in command.options:
            assert len(option.summary) <= 60
        for positional in command.positionals:
            assert len(positional.summary) <= 60


def test_build_spec_does_not_mutate_the_parser() -> None:
    parser = create_parser(only=None)
    before = len(parser._actions)

    build_spec(parser)

    assert len(parser._actions) == before
