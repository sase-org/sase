"""Tests for sase.completion.model."""

from __future__ import annotations

from typing import Any

from sase.completion.build import build_spec
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
        "options": (_option(),),
        "positionals": (_positional(),),
        "subcommands": (),
        "default_child": None,
        "mutex_groups": (),
    }
    base.update(overrides)
    return CommandSpec(**base)


def test_option_spec_round_trips_through_json() -> None:
    option = _option(choices=("a", "b"), kind=None)
    assert OptionSpec.from_json(option.to_json()) == option


def test_positional_spec_round_trips_through_json() -> None:
    positional = _positional()
    assert PositionalSpec.from_json(positional.to_json()) == positional


def test_command_spec_round_trips_through_json() -> None:
    command = _command()
    assert CommandSpec.from_json(command.to_json()) == command


def test_completion_spec_round_trips_through_json() -> None:
    spec = CompletionSpec(
        prog="sase", version="1.2.3", root=_command(path=(), name="sase")
    )
    assert CompletionSpec.from_json(spec.to_json()) == spec


def test_structural_view_excludes_summary_but_keeps_description_digest() -> None:
    view = _command().structural_view()
    assert "summary" not in view
    assert "description_digest" in view
    for option_view in view["options"]:
        assert "summary" not in option_view
    for positional_view in view["positionals"]:
        assert "summary" not in positional_view


def test_description_digest_changes_with_own_summary_but_not_with_children() -> None:
    command = _command()
    reworded = _command(summary="Totally different wording")
    assert command.description_digest() != reworded.description_digest()

    with_extra_child = _command(
        subcommands=(_command(name="extra", path=("bead", "show", "extra")),)
    )
    assert command.description_digest() == with_extra_child.description_digest()


def test_structural_digest_ignores_version() -> None:
    spec_a = CompletionSpec(
        prog="sase", version="1.0", root=_command(path=(), name="sase")
    )
    spec_b = CompletionSpec(
        prog="sase", version="2.0", root=_command(path=(), name="sase")
    )
    assert spec_a.structural_digest() == spec_b.structural_digest()


def test_structural_digest_changes_with_grammar() -> None:
    spec_a = CompletionSpec(
        prog="sase", version="1.0", root=_command(path=(), name="sase")
    )
    spec_b = CompletionSpec(
        prog="sase",
        version="1.0",
        root=_command(path=(), name="sase", mutex_groups=(("a", "b"),)),
    )
    assert spec_a.structural_digest() != spec_b.structural_digest()


def test_full_spec_round_trips_from_the_real_tree() -> None:
    spec = build_spec()
    assert CompletionSpec.from_json(spec.to_json()) == spec
