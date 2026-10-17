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


def test_usage_non_adjacent_mutex_group() -> None:
    tool = _load()
    parser = argparse.ArgumentParser(prog="demo", add_help=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-a", action="store_true")
    parser.add_argument("-m", metavar="M")
    group.add_argument("-p", metavar="NAME")
    assert (
        tool._format_usage(parser, "demo") == "usage: demo [-h] [-a | -p NAME] [-m M]"
    )


def test_usage_required_mutex_group_with_positional() -> None:
    tool = _load()
    parser = argparse.ArgumentParser(prog="demo", add_help=False)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-a", metavar="DIR")
    group.add_argument("-p", action="store_true")
    positional = parser.add_argument("name")
    # argparse rejects required positionals in mutex groups; attach the
    # already-added positional so the usage builder still groups it.
    group._group_actions.append(positional)
    assert tool._format_usage(parser, "demo") == "usage: demo (-a DIR | -p | name)"


def test_usage_subparsers_long_choice_list_stays_one_token() -> None:
    tool = _load()
    parser = argparse.ArgumentParser(prog="sase tool", add_help=True)
    sub = parser.add_subparsers()
    for name in (
        "failures",
        "list",
        "receipt",
        "receipts",
        "run",
        "runs",
        "show",
        "stats",
        "stop",
        "wait",
    ):
        sub.add_parser(name)
    usage = tool._format_usage(parser, "sase tool")
    token = "{failures,list,receipt,receipts,run,runs,show,stats,stop,wait} ..."
    assert token in usage.replace("\n", " ")
    # The brace group is one token: wrapping may move it, never split it.
    joined_no_wrap_space = usage.replace("\n" + " " * len("usage: sase tool "), " ")
    assert token in joined_no_wrap_space
    assert usage.split(token, 1)[0].count("{") == 0


def test_usage_required_option_with_metavar() -> None:
    tool = _load()
    parser = argparse.ArgumentParser(prog="demo", add_help=False)
    parser.add_argument("-o", "--output", required=True, metavar="PATH")
    assert tool._format_usage(parser, "demo") == "usage: demo -o PATH"


def test_usage_nargs_optional_star_and_plus() -> None:
    tool = _load()
    parser = argparse.ArgumentParser(prog="demo", add_help=False)
    parser.add_argument("--maybe", nargs="?", metavar="X")
    parser.add_argument("--many", nargs="*", metavar="Y")
    parser.add_argument("--some", nargs="+", metavar="Z")
    assert (
        tool._format_usage(parser, "demo")
        == "usage: demo [--maybe [X]] [--many [Y ...]] [--some Z [Z ...]]"
    )


def test_usage_wraps_long_lines_on_whole_tokens() -> None:
    tool = _load()
    parser = argparse.ArgumentParser(prog="sase tool runs", add_help=True)
    parser.add_argument("-a", action="store_true")
    parser.add_argument("-A", metavar="AGENT")
    parser.add_argument("-c", metavar="CURSOR")
    parser.add_argument("-j", action="store_true")
    parser.add_argument("-n", metavar="N")
    parser.add_argument("-s", metavar="STATE")
    parser.add_argument("-t", metavar="TOOL")
    usage = tool._format_usage(parser, "sase tool runs")
    lines = usage.splitlines()
    assert len(lines) >= 2
    assert lines[0].startswith("usage: sase tool runs ")
    indent = " " * len("usage: sase tool runs ")
    assert lines[1].startswith(indent)
    for line in lines[1:]:
        assert not line.startswith(indent + "[") or line.startswith(indent)
        # A wrapped token is intact: no mid-token split of a bracket group.
        if line.strip().startswith("["):
            assert line.count("[") == line.count("]")
    assert all(len(line) <= tool._USAGE_WIDTH or "[" in line for line in lines)


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
