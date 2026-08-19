"""Build and paint the tmux Agent ``display-menu``."""

from __future__ import annotations

import shlex
import subprocess

from .models import TmuxAgentCatalog, TmuxAgentEntry
from .palette import (
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
from .tmux import TmuxRunner, tmux_agent_self_command

_MENU_STYLE_MIN_VERSION = (3, 4)
_MIN_NAME_WIDTH = 10


def build_display_menu_args(
    catalog: TmuxAgentCatalog,
    *,
    title: str,
    self_command: str | None = None,
    tmux_version: tuple[int, int] | None = None,
) -> list[str]:
    """Return the exact ``tmux display-menu`` argv for *catalog*.

    Style flags ``-b``, ``-s``, ``-S``, and ``-H`` are emitted only when
    *tmux_version* is ``>= 3.4``. Older (or unknown) tmux gets the same menu
    without those flags. Not-installed rows use tmux's ``-`` name prefix so
    they render dim and unselectable, with empty key and command — the
    shell script's convention.
    """
    command = self_command if self_command is not None else tmux_agent_self_command()
    args: list[str] = ["tmux", "display-menu"]
    if _supports_menu_styles(tmux_version):
        args.extend(
            (
                "-b",
                BORDER,
                "-S",
                f"fg={SELECTED_FG},bg={SELECTED_BG}",
                "-s",
                f"fg={MENU_FG},bg={MENU_BG}",
                "-H",
                f"fg={HIGHLIGHT_FG},bg={HIGHLIGHT_BG},bold",
            )
        )
    args.extend(
        (
            "-T",
            _styled_title(title),
            "-C",
            str(_default_choice_index(catalog)),
            "-x",
            "C",
            "-y",
            "C",
        )
    )
    name_width = _name_width(catalog)
    for entry in catalog.entries:
        args.extend(_entry_triple(entry, catalog.directory, command, name_width))
    return args


def run_display_menu(
    catalog: TmuxAgentCatalog,
    *,
    runner: TmuxRunner,
    title: str = "tmux Agent",
    self_command: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Paint the tmux Agent ``display-menu`` through *runner*."""
    args = build_display_menu_args(
        catalog,
        title=title,
        self_command=self_command,
        tmux_version=runner.tmux_version(),
    )
    return runner.display_menu(args)


def _supports_menu_styles(version: tuple[int, int] | None) -> bool:
    return version is not None and version >= _MENU_STYLE_MIN_VERSION


def _styled_title(title: str) -> str:
    return f"#[align=centre,fg={TITLE_FG},bg={TITLE_BG},bold] {title} "


def _name_width(catalog: TmuxAgentCatalog) -> int:
    widest = max((len(entry.display_name) for entry in catalog.entries), default=0)
    return max(widest, _MIN_NAME_WIDTH)


def _default_choice_index(catalog: TmuxAgentCatalog) -> int:
    if catalog.default_provider:
        for index, entry in enumerate(catalog.entries):
            if entry.provider == catalog.default_provider:
                return index
    for index, entry in enumerate(catalog.entries):
        if entry.installed:
            return index
    return 0


def _entry_triple(
    entry: TmuxAgentEntry,
    directory: str,
    self_command: str,
    name_width: int,
) -> tuple[str, str, str]:
    if not entry.installed:
        return (_disabled_label(entry, name_width), "", "")
    return (
        _enabled_label(entry, name_width),
        entry.key,
        _run_shell_command(self_command, entry.provider, directory),
    )


def _enabled_label(entry: TmuxAgentEntry, name_width: int) -> str:
    name = entry.display_name.ljust(name_width)
    accent = entry.color or MENU_FG
    label = f"#[fg={accent},bold]{name}"
    if entry.vendor:
        label += f"#[fg={VENDOR_FG},nobold] {entry.vendor}"
    return label


def _disabled_label(entry: TmuxAgentEntry, name_width: int) -> str:
    name = entry.display_name.ljust(name_width)
    label = f"-#[fg={DISABLED_FG},bold]{name}"
    if entry.vendor:
        label += f"#[fg={DISABLED_FG},nobold] {entry.vendor}"
    return label


def _run_shell_command(self_command: str, provider: str, directory: str) -> str:
    inner = f"{self_command} {shlex.quote(provider)} --dir {shlex.quote(directory)}"
    return f"run-shell {shlex.quote(inner)}"


__all__ = [
    "build_display_menu_args",
    "run_display_menu",
]
