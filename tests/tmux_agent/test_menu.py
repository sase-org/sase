"""Tests for tmux Agent display-menu rendering."""

from __future__ import annotations

import shlex

from sase.tmux_agent.menu import build_display_menu_args, run_display_menu
from sase.tmux_agent.palette import (
    BORDER,
    DISABLED_FG,
    HIGHLIGHT_BG,
    HIGHLIGHT_FG,
    MENU_BG,
    MENU_FG,
    SELECTED_BG,
    SELECTED_FG,
    TITLE_BG,
    TITLE_FG,
    VENDOR_FG,
)

from .fakes import FakeTmuxRunner, make_catalog, make_entry

_SELF = "sase tmux-agent"
_TITLE = "tmux Agent"
_DIR = "/tmp/project dir"


def _catalog(*, directory: str = _DIR):
    return make_catalog(
        (
            make_entry(
                "agy",
                key="a",
                display_name="Antigravity CLI",
                vendor="Antigravity",
                color="#7aa2f7",
            ),
            make_entry(
                "claude",
                key="c",
                display_name="Claude Code",
                vendor="Anthropic",
                color="#D97757",
            ),
            make_entry(
                "codex",
                key="x",
                display_name="Codex",
                vendor="OpenAI",
                color="#9ece6a",
                installed=False,
            ),
        ),
        directory=directory,
        default_provider="claude",
    )


def _args(*, version: tuple[int, int] | None = (3, 5), directory: str = _DIR):
    return build_display_menu_args(
        _catalog(directory=directory),
        title=_TITLE,
        self_command=_SELF,
        tmux_version=version,
    )


def test_menu_rows_are_in_catalog_order_with_keys() -> None:
    args = _args()
    items = _menu_items(args)
    assert [item[1] for item in items] == ["a", "c", ""]
    assert [_plain_name(item[0]) for item in items] == [
        "Antigravity CLI",
        "Claude Code",
        "Codex",
    ]


def test_default_choice_index_is_the_default_provider() -> None:
    args = _args()
    assert _flag_value(args, "-C") == "1"


def test_default_choice_falls_back_to_first_installed() -> None:
    catalog = make_catalog(
        (
            make_entry("agy", key="a", installed=False),
            make_entry("claude", key="c"),
            make_entry("grok", key="g"),
        ),
        default_provider=None,
    )
    args = build_display_menu_args(
        catalog, title=_TITLE, self_command=_SELF, tmux_version=(3, 5)
    )
    assert _flag_value(args, "-C") == "1"


def test_installed_row_uses_accent_and_run_shell_callback() -> None:
    args = _args()
    items = {
        _plain_name(label): (label, key, command)
        for label, key, command in _menu_items(args)
    }

    label, key, command = items["Claude Code"]
    assert key == "c"
    assert label.startswith("#[fg=#D97757,bold]Claude Code")
    assert f"#[fg={VENDOR_FG},nobold] Anthropic" in label
    assert not label.startswith("-")
    assert command == (
        "run-shell " + shlex.quote(f"{_SELF} claude --dir {shlex.quote(_DIR)}")
    )


def test_not_installed_row_uses_dash_prefix_and_empty_key_command() -> None:
    args = _args()
    items = {
        _plain_name(label): (label, key, command)
        for label, key, command in _menu_items(args)
    }

    label, key, command = items["Codex"]
    assert label.startswith(f"-#[fg={DISABLED_FG},bold]")
    assert key == ""
    assert command == ""


def test_directory_with_space_and_quote_is_shell_quoted_in_callback() -> None:
    directory = "/tmp/foo's bar"
    args = _args(directory=directory)
    items = _menu_items(args)
    claude = next(item for item in items if item[1] == "c")
    expected_inner = f"{_SELF} claude --dir {shlex.quote(directory)}"
    assert claude[2] == f"run-shell {shlex.quote(expected_inner)}"


def test_style_flags_present_on_tmux_3_4() -> None:
    args = _args(version=(3, 4))
    assert args[:2] == ["tmux", "display-menu"]
    assert _flag_value(args, "-b") == BORDER
    assert _flag_value(args, "-S") == f"fg={SELECTED_FG},bg={SELECTED_BG}"
    assert _flag_value(args, "-s") == f"fg={MENU_FG},bg={MENU_BG}"
    assert _flag_value(args, "-H") == f"fg={HIGHLIGHT_FG},bg={HIGHLIGHT_BG},bold"
    assert _flag_value(args, "-T") == (
        f"#[align=centre,fg={TITLE_FG},bg={TITLE_BG},bold] {_TITLE} "
    )
    assert _flag_value(args, "-x") == "C"
    assert _flag_value(args, "-y") == "C"


def test_style_flags_omitted_on_tmux_older_than_3_4() -> None:
    args = _args(version=(3, 3))
    assert "-b" not in args
    assert "-S" not in args
    assert "-s" not in args
    assert "-H" not in args
    assert _flag_value(args, "-T") == (
        f"#[align=centre,fg={TITLE_FG},bg={TITLE_BG},bold] {_TITLE} "
    )
    assert _flag_value(args, "-C") == "1"
    assert _flag_value(args, "-x") == "C"
    assert _flag_value(args, "-y") == "C"
    # Rows still present in the degraded form.
    assert any(key == "c" for _label, key, _command in _menu_items(args))


def test_style_flags_omitted_when_version_unknown() -> None:
    args = _args(version=None)
    assert "-b" not in args
    assert "-T" in args


def test_run_display_menu_probes_version_and_invokes_display_menu() -> None:
    runner = FakeTmuxRunner(version_output="tmux 3.5a")
    result = run_display_menu(
        _catalog(),
        runner=runner,
        title=_TITLE,
        self_command=_SELF,
    )
    assert result.returncode == 0
    assert runner.calls_for("-V") == [["tmux", "-V"]]
    menus = runner.calls_for("display-menu")
    assert len(menus) == 1
    assert menus[0][0:2] == ["tmux", "display-menu"]
    assert "-b" in menus[0]


def test_run_display_menu_reports_nonzero_stderr() -> None:
    runner = FakeTmuxRunner(
        version_output="tmux 3.5a",
        display_menu_error="no current target",
    )
    result = run_display_menu(
        _catalog(),
        runner=runner,
        title=_TITLE,
        self_command=_SELF,
    )
    assert result.returncode == 1
    assert "no current target" in result.stderr


def _flag_value(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1]


def _menu_items(args: list[str]) -> list[tuple[str, str, str]]:
    start = args.index("-y") + 2
    triples = args[start:]
    assert len(triples) % 3 == 0
    return [
        (triples[index], triples[index + 1], triples[index + 2])
        for index in range(0, len(triples), 3)
    ]


def _plain_name(label: str) -> str:
    text = label[1:] if label.startswith("-") else label
    after_style = text.split("]", 1)[1]
    return after_style.split("#[", 1)[0].rstrip()
