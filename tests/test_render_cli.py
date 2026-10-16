"""Tests for the generated CLI reference pages.

Phase sase-1le.16 renders ``docs/reference/cli/<group>.md`` (one page per
top-level command group) plus ``docs/reference/cli/index.md`` from the live
argparse tree. Hidden ``SUPPRESS`` helpers stay out; legacy top-level
aliases share their canonical page.
"""

from __future__ import annotations

import argparse
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import sys
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "render_cli"


def _load() -> ModuleType:
    loader = SourceFileLoader("render_cli_test", str(TOOL_PATH))
    spec = importlib.util.spec_from_loader("render_cli_test", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["render_cli_test"] = module
    loader.exec_module(module)
    return module


def _parsers() -> tuple[argparse.ArgumentParser, argparse.ArgumentParser]:
    tool = _load()
    root = argparse.ArgumentParser(prog="sase")
    sub = root.add_subparsers(dest="command")
    bead = sub.add_parser(
        "bead",
        help="Lightweight git-native issue tracking",
        description="Manage beads.",
    )
    bead_sub = bead.add_subparsers(dest="bead_subcommand")
    list_p = bead_sub.add_parser("list", help="List issues")
    list_p.add_argument("-j", "--json", action="store_true", help="Emit JSON")
    list_p.add_argument("--limit", metavar="N", default=20, help="Max rows | shown")
    hidden = bead_sub.add_parser("exec-batch", help=argparse.SUPPRESS)
    hidden.add_argument("batch", help=argparse.SUPPRESS)
    # Legacy alias shares the canonical object, like patch/changespec.
    sub._choices_actions.append(
        argparse.Action(
            option_strings=[],
            dest="task",
            help="Legacy alias",
        )
    )
    sub.choices["task"] = bead
    assert tool is not None
    return root, bead


def test_clean_unescapes_argparse_percent() -> None:
    tool = _load()
    assert tool._clean("Predict each %%auto decision") == "Predict each %auto decision"
    assert tool._clean("a  b\n c") == "a b c"


def test_cell_escapes_pipes_and_marks_empty() -> None:
    tool = _load()
    assert tool._cell("a|b") == "a\\|b"
    assert tool._cell("") == "—"
    assert tool._cell(None) == "—"


def test_option_label_and_default() -> None:
    tool = _load()
    parser = argparse.ArgumentParser(prog="sase bead list")
    parser.add_argument("-j", "--json", action="store_true", help="Emit JSON")
    parser.add_argument("--limit", metavar="N", default=20, help="Max rows")
    by_dest = {a.dest: a for a in parser._actions if a.option_strings}
    assert tool._option_label(by_dest["json"]) == "`-j`, `--json`"
    assert tool._option_label(by_dest["limit"]) == "`--limit N`"
    assert tool._format_default(by_dest["json"]) == "`false`"
    assert tool._format_default(by_dest["limit"]) == "`20`"


def test_visible_subcommands_skip_suppress() -> None:
    tool = _load()
    root, bead = _parsers()
    names = [name for name, _, _ in tool._visible_subcommands(bead)]
    assert names == ["list"]


def test_yaml_quote_protects_colons() -> None:
    tool = _load()
    assert tool._yaml_quote("a: b") == '"a: b"'
    assert tool._yaml_quote('say "hi"') == '"say \\"hi\\""'


def test_group_page_has_frontmatter_marker_and_tables() -> None:
    tool = _load()
    _, bead = _parsers()
    text = tool.render_group_page(
        "bead", bead, "Lightweight git-native issue tracking", []
    )
    assert text.startswith('---\ntitle: "sase bead"\ndescription: ')
    assert "generated, do not edit" in text
    assert "# sase bead" in text
    assert "Bare `sase bead` defaults to `sase bead list`." in text
    assert "`sase bead list`" in text
    assert "`-j`, `--json`" in text
    assert "Max rows \\| shown" in text


def test_group_page_notes_alias() -> None:
    tool = _load()
    _, bead = _parsers()
    text = tool.render_group_page("proc", bead, "Manage procs", ["task"])
    assert "Aliases: `sase task`." in text


def test_canonical_groups_fold_aliases() -> None:
    tool = _load()
    # Build a root with an explicit alias pair sharing one object.
    root = argparse.ArgumentParser(prog="sase")
    sub = root.add_subparsers(dest="command")
    real = {"artifact-file": "artifact"}
    tool.ALIASES.update(real)
    try:
        artifact = sub.add_parser("artifact", help="Manage artifacts")
        sub.choices["artifact-file"] = artifact
        canonical, _, notes = tool._canonical_groups(root)
        assert sorted(canonical.keys()) == ["artifact"]
        assert notes == {"artifact": ["artifact-file"]}
    finally:
        del tool.ALIASES["artifact-file"]


def test_index_lists_groups() -> None:
    tool = _load()
    root, bead = _parsers()
    root.add_argument("-f", "--enable-feature", metavar="FLAG", help="Enable a flag")
    root._add_action(
        argparse.Action(
            option_strings=["-H", "--full-help"],
            dest="full_help",
            nargs=0,
            help="Show every command",
        )
    )
    text = tool.render_index_text({"bead": bead}, {"bead": "Lightweight"}, root)
    assert text.startswith('---\ntitle: "CLI command groups"\n')
    assert "generated, do not edit" in text
    assert "## Global options" in text
    assert "`-f FLAG`, `--enable-feature FLAG`" in text
    assert "`-H`, `--full-help`" in text
    assert "--full-help FULL_HELP" not in text
    assert "[`sase bead`](bead.md)" in text
