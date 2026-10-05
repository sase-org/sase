"""Parser help tests for ``sase macro show``."""

from __future__ import annotations

import pytest

from sase.main.parser import create_parser
from tests.main.parser_help_helpers import (
    flat_help,
    help_subcommand_rows,
    parser_for,
)


def test_macro_help_renders_show_in_sorted_subcommands() -> None:
    macro_parser = parser_for(("sase", "macro"))
    expected_commands = {
        "catalog",
        "expand",
        "explain",
        "graph",
        "list",
        "show",
        "types",
    }

    help_text = macro_parser.format_help()
    help_commands = help_subcommand_rows(help_text, expected_commands)

    assert help_commands == sorted(expected_commands)
    assert "{catalog,expand,explain,graph,list,show,types}" in help_text


def test_macro_show_help_documents_flags_and_examples() -> None:
    help_text = flat_help(parser_for(("sase", "macro", "show")).format_help())

    assert "-c" in help_text
    assert "--color" in help_text
    assert "-f" in help_text
    assert "--format" in help_text
    assert "-p" in help_text
    assert "--project" in help_text
    assert "Show one macro or workflow definition" in help_text
    assert "sase macro show sase/reads" in help_text
    assert "sase macro show '#!sync'" in help_text
    assert "sase macro show plan --format json | jq .inputs" in help_text
    assert "sase macro show coder --format raw > coder.md" in help_text
    assert "sase macro show t --color always | less -R" in help_text


def test_bare_macro_still_delegates_to_list() -> None:
    args = create_parser().parse_args(["macro"])

    assert args.command == "macro"
    assert args.macro_subcommand == "list"


def test_legacy_xprompt_normalizes_to_macro_parser() -> None:
    """Root-position normalization rewrites ``xprompt`` to ``macro`` (flag on)."""
    from sase.feature_flags import override_flags
    from sase.legacy_xprompt_syntax import normalize_legacy_root_args

    with override_flags(legacy_xprompt_syntax=True):
        argv = ["sase", "xprompt", "list"]
        normalize_legacy_root_args(argv)
        args = create_parser().parse_args(argv[1:])

    assert args.command == "macro"
    assert args.macro_subcommand == "list"


def test_legacy_xprompt_off_exits_with_retirement_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With the sunset flag off, a root ``xprompt`` exits 2 with a hint."""
    import pytest

    from sase.feature_flags import override_flags
    from sase.legacy_xprompt_syntax import normalize_legacy_root_args

    with override_flags(legacy_xprompt_syntax=False):
        with pytest.raises(SystemExit) as exc_info:
            normalize_legacy_root_args(["sase", "xprompt", "list"])

    assert exc_info.value.code == 2
    assert "xprompt is retired; use macro" in capsys.readouterr().err


def test_legacy_path_target_normalizes_with_flag_on() -> None:
    """``sase path xprompts-dir`` behaves like its canonical form (flag on)."""
    from sase.feature_flags import override_flags
    from sase.legacy_xprompt_syntax import normalize_legacy_root_args

    with override_flags(legacy_xprompt_syntax=True):
        argv = ["sase", "path", "xprompts-dir"]
        normalize_legacy_root_args(argv)
        args = create_parser().parse_args(argv[1:])

    assert args.command == "path"
    assert args.name == "macros-dir"


def test_legacy_path_target_off_exits_with_retirement_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With the sunset flag off, ``sase path xprompts-dir`` exits 2."""
    import pytest

    from sase.feature_flags import override_flags
    from sase.legacy_xprompt_syntax import normalize_legacy_root_args

    with override_flags(legacy_xprompt_syntax=False):
        with pytest.raises(SystemExit) as exc_info:
            normalize_legacy_root_args(["sase", "path", "xprompts-dir"])

    assert exc_info.value.code == 2
    assert "xprompts-dir is retired; use macros-dir" in capsys.readouterr().err


def test_prompt_argument_containing_legacy_term_is_untouched() -> None:
    """A prompt payload containing the retired term is never rewritten."""
    from sase.feature_flags import override_flags
    from sase.legacy_xprompt_syntax import normalize_legacy_root_args

    with override_flags(legacy_xprompt_syntax=True):
        argv = ["sase", "macro", "expand", "xprompt"]
        normalize_legacy_root_args(argv)

    assert argv == ["sase", "macro", "expand", "xprompt"]


def test_full_help_contains_no_retired_spelling() -> None:
    """``--full-help`` and ``sase path --help`` show no retired spelling."""
    from io import StringIO

    from sase.main.parser import create_parser as _create_parser

    parser = _create_parser()
    buf = StringIO()
    with __import__("contextlib").redirect_stdout(buf):
        try:
            parser.parse_args(["--full-help"])
        except SystemExit:
            pass
    full_help = buf.getvalue()
    assert "xprompt" not in full_help

    path_parser_buf = StringIO()
    with __import__("contextlib").redirect_stdout(path_parser_buf):
        try:
            parser.parse_args(["path", "--help"])
        except SystemExit:
            pass
    path_help = path_parser_buf.getvalue()
    assert "xprompts-dir" not in path_help
    assert "xprompts-schema" not in path_help
    assert "xprompts-collection-schema" not in path_help
