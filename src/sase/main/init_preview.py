"""Rich inventory and diff previews for ``sase init`` plans."""

from __future__ import annotations

from dataclasses import dataclass
import difflib
from pathlib import Path
from typing import TextIO

from rich.console import Console
from rich.rule import Rule
from rich.text import Text

from .init_plan import InitAction, InitPlan


@dataclass(frozen=True)
class _Diffstat:
    """Line or byte changes for one planned action."""

    added: int = 0
    removed: int = 0
    binary: bool = False
    old_size: int = 0
    new_size: int = 0


_OPERATION_PRESENTATION = {
    "create": ("+", "green"),
    "update": ("~", "yellow"),
    "overwrite": ("~", "yellow"),
    "delete": ("−", "red"),
    "validate": ("●", "cyan"),
    "deploy": ("●", "cyan"),
}


def preview_console(file: TextIO) -> Console:
    """Return a Rich console with color enabled exactly when *file* is a TTY."""
    is_tty = file.isatty()
    return Console(
        file=file,
        force_terminal=is_tty,
        color_system="auto" if is_tty else None,
        no_color=not is_tty,
        soft_wrap=True,
    )


def _display_path(path: Path) -> str:
    resolved = path.expanduser().resolve(strict=False)
    cwd = Path.cwd().resolve(strict=False)
    try:
        return str(resolved.relative_to(cwd)) or "."
    except ValueError:
        pass

    home = Path.home().resolve(strict=False)
    try:
        return f"~/{resolved.relative_to(home)}"
    except ValueError:
        return str(path)


def _read_old_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _read_old_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""


def _line_counts(old: str, new: str) -> tuple[int, int]:
    matcher = difflib.SequenceMatcher(
        None,
        old.splitlines(),
        new.splitlines(),
        autojunk=False,
    )
    added = removed = 0
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag in {"replace", "delete"}:
            removed += old_end - old_start
        if tag in {"replace", "insert"}:
            added += new_end - new_start
    return added, removed


def _action_diffstat(action: InitAction) -> _Diffstat | None:
    """Return a lazily-computed diffstat for *action*, when content is known."""
    if isinstance(action.new_content, bytes):
        old_bytes = _read_old_bytes(action.path)
        return _Diffstat(
            binary=True,
            old_size=len(old_bytes),
            new_size=len(action.new_content),
        )
    if isinstance(action.new_content, str):
        old_text = _read_old_text(action.path)
        added, removed = _line_counts(old_text, action.new_content)
        return _Diffstat(added=added, removed=removed)
    if action.operation == "delete":
        old_text = _read_old_text(action.path)
        added, removed = _line_counts(old_text, "")
        return _Diffstat(added=added, removed=removed)
    return None


def _human_size(size: int) -> str:
    if size < 1000:
        return f"{size} B"
    if size < 1_000_000:
        return f"{size / 1000:.1f} kB"
    return f"{size / 1_000_000:.1f} MB"


def _operation_text(action: InitAction) -> Text:
    glyph, style = _OPERATION_PRESENTATION[action.operation]
    result = Text()
    result.append(f"{glyph} {action.operation}", style=style)
    return result


def _diffstat_text(stat: _Diffstat | None) -> Text:
    if stat is None:
        return Text("–", style="dim")
    if stat.binary:
        result = Text("binary ", style="dim")
        result.append(_human_size(stat.old_size), style="dim")
        result.append(" → ", style="dim")
        result.append(_human_size(stat.new_size), style="dim")
        return result
    result = Text()
    if stat.added:
        result.append(f"+{stat.added}", style="green")
    if stat.removed:
        if result:
            result.append(" ")
        result.append(f"−{stat.removed}", style="red")
    if not result:
        result.append("–", style="dim")
    return result


def render_plan_inventory(console: Console, plan: InitPlan) -> None:
    """Render every planned action with aligned path and diffstat columns."""
    rows: list[tuple[InitAction, str, Text]] = []
    for action in plan.actions:
        rows.append(
            (
                action,
                _display_path(action.path),
                _diffstat_text(_action_diffstat(action)),
            )
        )
    operation_width = max(
        (len(_operation_text(action).plain) for action, _, _ in rows),
        default=0,
    )
    path_width = max((len(path) for _, path, _ in rows), default=0)
    diffstat_width = max((len(stat.plain) for _, _, stat in rows), default=0)
    for action, path, stat in rows:
        operation = _operation_text(action)
        line = Text("       ")
        line.append_text(operation)
        line.append(" " * (operation_width - len(operation.plain) + 2))
        line.append(path, style="bold")
        line.append(" " * (path_width - len(path) + 2))
        line.append_text(stat)
        if action.detail:
            line.append(" " * (diffstat_width - len(stat.plain) + 2))
            line.append(action.detail, style="dim")
        console.print(line)


def _rule_title(action: InitAction) -> Text:
    if isinstance(action.new_content, bytes):
        title = Text("binary ", style="dim")
        title.append_text(_operation_text(action))
        title.append(f" {_display_path(action.path)}", style="bold")
        return title
    if action.new_content is None and action.operation != "delete":
        return Text(f"● {action.detail or _display_path(action.path)}", style="cyan")
    title = _operation_text(action)
    title.append(f" {_display_path(action.path)}", style="bold")
    return title


def _styled_diff_line(line: str) -> Text:
    style = "dim"
    if line.startswith("+++") or line.startswith("---"):
        style = "bold green" if line.startswith("+++") else "bold red"
    elif line.startswith("+"):
        style = "green"
    elif line.startswith("-"):
        style = "red"
    elif line.startswith("@@"):
        style = "cyan"
    return Text(line.rstrip("\n"), style=style)


def _render_text_diff(console: Console, action: InitAction) -> None:
    old = _read_old_text(action.path)
    new = action.new_content if isinstance(action.new_content, str) else ""
    display_path = _display_path(action.path)
    fromfile = "/dev/null" if action.operation == "create" else display_path
    tofile = "/dev/null" if action.operation == "delete" else display_path

    if action.operation == "create":
        console.print(f"New file, {len(new.splitlines())} lines:", style="dim")
    elif action.operation == "delete":
        console.print(f"Removes {len(old.splitlines())} lines.", style="dim")

    diff = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=fromfile,
        tofile=tofile,
    )
    for line in diff:
        console.print(_styled_diff_line(line))


def render_plan_diff(console: Console, plan: InitPlan) -> None:
    """Render the complete content diff for every action in *plan*."""
    for action in plan.actions:
        console.print()
        console.print(Rule(_rule_title(action), style="dim"))
        if isinstance(action.new_content, bytes):
            stat = _action_diffstat(action)
            assert stat is not None
            console.print(
                "Binary file differs: "
                f"{_human_size(stat.old_size)} on disk → "
                f"{_human_size(stat.new_size)} generated.",
                style="dim",
            )
        elif action.new_content is None and action.operation != "delete":
            console.print(
                "Remote/procedural action — no local file diff.",
                style="dim",
            )
            if "companion" in action.detail.casefold():
                console.print(
                    "A separate y/N confirmation guards companion repository creation.",
                    style="dim",
                )
        else:
            _render_text_diff(console, action)


__all__ = [
    "preview_console",
    "render_plan_diff",
    "render_plan_inventory",
]
