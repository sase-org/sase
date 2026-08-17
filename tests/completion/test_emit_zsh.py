"""Tests for sase.completion.emit_zsh over hand-built specs and the live tree."""

from __future__ import annotations

import re
from typing import Any

import pytest

from sase.completion.build import build_spec
from sase.completion.emit_zsh import emit_zsh
from sase.completion.kinds import ValueKind
from sase.completion.model import (
    CommandSpec,
    CompletionSpec,
    OptionSpec,
    PositionalSpec,
)


def _option(**overrides: Any) -> OptionSpec:
    base: dict[str, Any] = {
        "strings": ("-j", "--json"),
        "dest": "json",
        "summary": "Emit machine-readable JSON",
        "takes_value": False,
        "repeatable": False,
        "choices": None,
        "kind": None,
        "hidden": False,
    }
    base.update(overrides)
    return OptionSpec(**base)


def _positional(**overrides: Any) -> PositionalSpec:
    base: dict[str, Any] = {
        "metavar": "ID",
        "dest": "id",
        "summary": "Full or shorthand issue ID",
        "nargs": None,
        "choices": None,
        "kind": ValueKind.BEAD,
        "is_remainder": False,
    }
    base.update(overrides)
    return PositionalSpec(**base)


def _command(**overrides: Any) -> CommandSpec:
    base: dict[str, Any] = {
        "name": "show",
        "path": ("bead", "show"),
        "aliases": (),
        "hidden": False,
        "summary": "Show issue details",
        "options": (),
        "positionals": (),
        "subcommands": (),
        "default_child": None,
        "mutex_groups": (),
    }
    base.update(overrides)
    return CommandSpec(**base)


def _spec(*children: CommandSpec, **root_overrides: Any) -> CompletionSpec:
    root = _command(
        name="sase",
        path=(),
        summary="",
        subcommands=children,
        **root_overrides,
    )
    return CompletionSpec(prog="sase", version="0.0-test", root=root)


def _describe_block(script: str, *, label: str) -> str:
    pattern = re.compile(
        rf"_describe -t commands '{re.escape(label)}' commands",
        re.MULTILINE,
    )
    match = pattern.search(script)
    assert match is not None, script
    start = script.rfind("commands=(", 0, match.start())
    assert start != -1
    return script[start : match.end()]


def test_emit_zsh_header_and_arguments_flags() -> None:
    script = emit_zsh(_spec())
    assert script.startswith("#compdef sase\n")
    assert "_arguments -C -s -S" in script
    assert "__sase_run()" in script
    assert '_sase_root "$@"' in script


def test_default_child_still_lists_every_child() -> None:
    listing = _command(
        name="list",
        path=("bead", "list"),
        summary="List beads",
    )
    show = _command(
        name="show",
        path=("bead", "show"),
        summary="Show a bead",
        positionals=(_positional(),),
    )
    bead = _command(
        name="bead",
        path=("bead",),
        summary="Inspect beads",
        default_child="list",
        subcommands=(listing, show),
    )
    script = emit_zsh(_spec(bead))
    block = _describe_block(script, label="sase bead commands")
    assert "'list:List beads'" in block
    assert "'show:Show a bead'" in block


def test_mutex_pair_shares_exclusion_list() -> None:
    json_opt = _option()
    yaml_opt = _option(
        strings=("-y", "--yaml"),
        dest="yaml",
        summary="Emit YAML",
    )
    leaf = _command(
        options=(json_opt, yaml_opt),
        mutex_groups=(("json", "yaml"),),
        positionals=(),
    )
    script = emit_zsh(_spec(leaf))
    assert "(-j --json -y --yaml)" in script
    assert "{-j,--json}" in script
    assert "{-y,--yaml}" in script


def test_repeatable_option_uses_star_and_skips_exclusion() -> None:
    tag = _option(
        strings=("-t", "--tag"),
        dest="tag",
        summary="Add a tag",
        takes_value=True,
        repeatable=True,
    )
    script = emit_zsh(_spec(_command(options=(tag,))))
    assert "'*'{-t,--tag}'[Add a tag]:tag:'" in script
    assert "(-t --tag)" not in script


def test_remainder_emits_normal_command_action() -> None:
    remainder = _positional(
        metavar="-- COMMAND ...",
        dest="proc_command",
        kind=None,
        is_remainder=True,
        nargs="...",
    )
    script = emit_zsh(_spec(_command(positionals=(remainder,))))
    assert "'*::command:_normal'" in script


def test_plus_prefixed_command_survives() -> None:
    plus = _command(
        name="+1",
        path=("bead", "+1"),
        summary="Add a plus-one",
        positionals=(_positional(),),
    )
    listing = _command(name="list", path=("bead", "list"), summary="List beads")
    bead = _command(
        name="bead",
        path=("bead",),
        summary="Inspect beads",
        subcommands=(plus, listing),
    )
    script = emit_zsh(_spec(bead))
    assert "'+1:Add a plus-one'" in script
    assert "(+1) _sase_bead_plus1 && ret=0" in script
    assert "_sase_bead_plus1() {" in script


def test_description_quoting_escapes_quote_and_brackets() -> None:
    option = _option(summary="Don't use [this]: yet")
    script = emit_zsh(_spec(_command(options=(option,))))
    assert r"[Don'\''t use \[this\]\: yet]" in script


def test_aliases_are_completable_but_absent_from_describe() -> None:
    patch = _command(
        name="patch",
        path=("patch",),
        aliases=("changespec",),  # legacy command alias
        summary="Inspect patches",
    )
    script = emit_zsh(_spec(patch))
    block = _describe_block(script, label="sase commands")
    assert "'patch:Inspect patches'" in block
    assert "changespec" not in block  # legacy command alias
    assert "(patch|changespec) _sase_patch && ret=0" in script  # legacy command alias
    assert "_sase_aliases=(changespec)" in script  # legacy command alias


def test_hidden_option_is_not_emitted() -> None:
    hidden = _option(
        strings=("--secret",),
        dest="secret",
        summary="Hidden",
        hidden=True,
    )
    visible = _option()
    script = emit_zsh(_spec(_command(options=(hidden, visible))))
    assert "--secret" not in script
    assert "--json" in script


def test_static_choices_and_kind_calls() -> None:
    fmt = _option(
        strings=("-f", "--format"),
        dest="format",
        summary="Output format",
        takes_value=True,
        choices=("json", "text"),
    )
    project = _option(
        strings=("-p", "--project"),
        dest="project",
        summary="Project name",
        takes_value=True,
        kind=ValueKind.PROJECT,
    )
    out = _option(
        strings=("-o", "--output"),
        dest="output",
        summary="Write to a file",
        takes_value=True,
        kind=ValueKind.PATH,
    )
    directory = _option(
        strings=("-d", "--dir"),
        dest="dir",
        summary="A directory",
        takes_value=True,
        kind=ValueKind.DIR,
    )
    script = emit_zsh(_spec(_command(options=(fmt, project, out, directory))))
    assert ":format:(json text)" in script
    assert ":project:{__sase_candidates project}" in script
    assert ":output:_files" in script
    assert ":dir:_files -/" in script


@pytest.fixture(scope="module")
def live_script() -> str:
    return emit_zsh(build_spec())


def test_live_script_has_compdef_and_arguments(live_script: str) -> None:
    assert live_script.startswith("#compdef sase\n")
    assert "_arguments -C -s -S" in live_script
    assert "helper-bridge" not in live_script


def test_live_script_treats_changespec_as_alias(live_script: str) -> None:
    block = _describe_block(live_script, label="sase commands")
    assert "changespec" not in block  # legacy command alias
    assert "patch:" in block
    assert "changespec" in live_script  # legacy command alias
    assert "(patch|changespec)" in live_script  # legacy command alias


def test_live_script_descriptions_fit_column(live_script: str) -> None:
    for match in re.finditer(r"\[((?:\\.|[^\]\\])*)\]", live_script):
        raw = (
            match.group(1)
            .replace(r"\[", "[")
            .replace(r"\]", "]")
            .replace(r"\:", ":")
            .replace(r"'\''", "'")
        )
        assert len(raw) <= 60, raw


def test_live_script_plus_one_command_is_present(live_script: str) -> None:
    assert "'+1:" in live_script
    assert "(+1)" in live_script
