"""Whole-spec contract between the Python spec and the Rust wire (sase-17x.5)."""

from __future__ import annotations

import json

import pytest

from sase.completion.build import build_spec
from sase.completion.command_line_grammar import (
    COMMAND_LINE_GRAMMAR_SCHEMA_VERSION,
    CommandLineGrammar,
    load_command_line_grammar,
)
from sase.completion.model import CommandSpec


def _leaves(root: CommandSpec) -> list[CommandSpec]:
    if not root.subcommands:
        return [root]
    leaves: list[CommandSpec] = []
    for child in root.subcommands:
        leaves.extend(_leaves(child))
    return leaves


@pytest.fixture(scope="module")
def grammar() -> CommandLineGrammar:
    spec = build_spec()
    return CommandLineGrammar.from_spec_json(json.dumps(spec.to_json()))


def test_load_round_trip(tmp_path: object, grammar: CommandLineGrammar) -> None:
    from pathlib import Path

    assert len(grammar) > 0
    spec = build_spec()
    path = Path(str(tmp_path)) / "spec.json"
    path.write_text(json.dumps(spec.to_json()), encoding="utf-8")
    loaded = load_command_line_grammar(path)
    assert len(loaded) == len(grammar)


def test_whole_tree_agreement(grammar: CommandLineGrammar) -> None:
    spec = build_spec()
    checked = 0
    for leaf in _leaves(spec.root):
        if leaf.hidden or not leaf.path:
            continue
        help_view = grammar.command_help(list(leaf.path))
        assert help_view is not None, leaf.path
        spec_dests = sorted(option.dest for option in leaf.options if not option.hidden)
        help_dests = sorted(option["dest"] for option in help_view["options"])
        assert help_dests == spec_dests, leaf.path
        line = " ".join(leaf.path) + " "
        context = grammar.resolve(line, len(line))
        assert context["node_kind"] == "leaf", leaf.path
        assert context["path"] == list(leaf.path), leaf.path
        if all(rule.when is None for rule in leaf.run_policy):
            expected = leaf.run_policy[0].policy if leaf.run_policy else "proc"
            assert context["run_policy"]["policy"] == expected, leaf.path
            assert context["writes"] == leaf.writes, leaf.path
        checked += 1
    assert checked > 200


def test_end_to_end_lines(grammar: CommandLineGrammar) -> None:
    line = "bead close sase-1 --reason "
    context = grammar.resolve(line, len(line))
    assert context["slot"]["kind"] == "option_value"
    assert context["slot"]["dest"] == "reason"

    line = "sase proc run -- ls -la"
    context = grammar.resolve(line, len(line))
    assert context["argv"] == ["proc", "run", "--", "ls", "-la"]

    context = grammar.resolve("tui", 3)
    assert context["run_policy"]["policy"] == "deny"

    completed = grammar.complete("bead cl", 7)
    assert completed["items"][0]["insert_text"] == "close "

    completed = grammar.complete("bead list -s ", len("bead list -s "))
    assert "open" in [item["display"] for item in completed["items"]]


def test_schema_mismatch_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.completion.command_line_grammar as adapter

    monkeypatch.setattr(adapter, "COMMAND_LINE_GRAMMAR_SCHEMA_VERSION", 999_999)
    spec = build_spec()
    with pytest.raises(RuntimeError):
        CommandLineGrammar.from_spec_json(json.dumps(spec.to_json()))
    assert COMMAND_LINE_GRAMMAR_SCHEMA_VERSION == 1
