"""Built-in Command Line commands (run-policies phase).

Built-ins are recognized by the first token, run instantly with no proc,
and render ``›`` blocks. ``<cmd> -h`` still runs argparse's real help as a
proc because only a first-token built-in name intercepts the line.

- ``cd <path|+project|->`` pins, unpins and completes dirs and projects.
- ``clear`` drops finished transcript blocks (procs are untouched).
- ``help [command…]`` renders ``command_help`` for one command path.
- ``history [query]`` lists matching history lines.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

#: First-token names intercepted as built-ins (never collide with spec tops).
BUILTIN_NAMES: tuple[str, ...] = ("cd", "clear", "help", "history")


@dataclass(frozen=True)
class BuiltinOutcome:
    """The rendered result of one built-in execution."""

    text: str
    exit_code: int = 0


@dataclass(frozen=True)
class CdResolution:
    """Off-thread result of resolving one ``cd`` command."""

    outcome: BuiltinOutcome
    pinned: str | None
    changes_pin: bool


def builtin_name_for(tokens: Sequence[str]) -> str | None:
    """Return the built-in name when *tokens* starts with one, else ``None``."""
    if not tokens:
        return None
    first = str(tokens[0])
    return first if first in BUILTIN_NAMES else None


def run_cd(
    session: Any,
    arg: str | None,
    *,
    cwd: str,
    resolve_project: Callable[[str], str | None] | None = None,
) -> BuiltinOutcome:
    """Pin or unpin the session's working directory; never raises.

    UI code should use :func:`resolve_cd` in a worker and apply its result on
    the app loop.  This compatibility wrapper remains useful for non-UI
    callers and focused unit tests.
    """
    resolution = resolve_cd(arg, cwd=cwd, resolve_project=resolve_project)
    if resolution.changes_pin:
        session.cwd_pin = resolution.pinned
    return resolution.outcome


def resolve_cd(
    arg: str | None,
    *,
    cwd: str,
    resolve_project: Callable[[str], str | None] | None = None,
) -> CdResolution:
    """Resolve a ``cd`` target without mutating UI-held session state."""
    if arg is None or not arg.strip():
        return CdResolution(BuiltinOutcome("usage: cd <path|+project|->"), None, False)
    target = arg.strip()
    if target == "-":
        return CdResolution(
            BuiltinOutcome("unpinned · following the TUI project"), None, True
        )
    if target.startswith("+"):
        name = target[1:]
        resolved = resolve_project(name) if resolve_project is not None else None
        if resolved is None:
            resolved = _resolve_project_checkout(name)
        if resolved is None:
            return CdResolution(
                BuiltinOutcome(f"error: no such project: {name}", exit_code=2),
                None,
                False,
            )
        return CdResolution(BuiltinOutcome(f"pinned · {resolved}"), resolved, True)
    path = os.path.expanduser(target)
    if not os.path.isabs(path):
        path = os.path.normpath(os.path.join(cwd, path))
    if not os.path.isdir(path):
        return CdResolution(
            BuiltinOutcome(f"error: no such directory: {target}", exit_code=2),
            None,
            False,
        )
    return CdResolution(BuiltinOutcome(f"pinned · {path}"), path, True)


def run_clear(session: Any) -> BuiltinOutcome:
    """Drop finished transcript blocks; running procs are untouched."""
    session.clear_transcript()
    return BuiltinOutcome("")


def render_help(help_view: dict[str, Any] | None, path: list[str]) -> BuiltinOutcome:
    """Render ``command_help`` for *path* as plain text, never blank."""
    if not help_view:
        name = " ".join(path) if path else "sase"
        return BuiltinOutcome(f"error: no such command: {name}", exit_code=2)
    lines = [str(help_view.get("usage", "") or "").strip()]
    summary = str(help_view.get("summary", "") or "").strip()
    if summary:
        lines.append(summary)
    positionals = help_view.get("positionals") or []
    if positionals:
        lines.append("")
        lines.append("positionals:")
        for item in positionals:
            metavar = str(item.get("metavar", "") or "")
            item_summary = str(item.get("summary", "") or "")
            row = f"  {metavar}" if not item_summary else f"  {metavar}  {item_summary}"
            lines.append(row)
    options = help_view.get("options") or []
    if options:
        lines.append("")
        lines.append("options:")
        for item in options:
            strings = ", ".join(str(part) for part in (item.get("strings") or []))
            item_summary = str(item.get("summary", "") or "")
            row = f"  {strings}" if not item_summary else f"  {strings}  {item_summary}"
            lines.append(row)
    children = help_view.get("children") or []
    if children:
        lines.append("")
        lines.append("commands:")
        for item in children:
            name = str(item.get("name", "") or "")
            item_summary = str(item.get("summary", "") or "")
            row = f"  {name}" if not item_summary else f"  {name}  {item_summary}"
            lines.append(row)
    return BuiltinOutcome("\n".join(line for line in lines if line is not None).strip())


def render_history(entries: Sequence[Any], query: str | None) -> BuiltinOutcome:
    """Render matching history lines, most recent first, never blank."""
    text = (query or "").strip().lower()
    matches = [
        entry for entry in entries if not text or text in str(entry.line).lower()
    ]
    if not matches:
        return BuiltinOutcome("(no matching history)")
    return BuiltinOutcome("\n".join(str(entry.line) for entry in matches))


def _resolve_project_checkout(name: str) -> str | None:
    """Best-effort ``+project`` resolution to an enabled project's checkout."""
    try:
        from sase.core.paths import sase_projects_dir
        from sase.core.project_lifecycle_facade import list_project_records
    except Exception:  # noqa: BLE001 - project lookup always degrades.
        return None
    try:
        root = sase_projects_dir()
        if not root.is_dir():
            return None
        records = list_project_records(root, "all", include_home=False)
    except Exception:  # noqa: BLE001 - project lookup always degrades.
        return None
    for record in records:
        project_name = getattr(record, "project_name", None)
        if project_name != name:
            continue
        if getattr(record, "state", None) != "enabled":
            return None
        workspace = getattr(record, "workspace_dir", None)
        if workspace:
            return str(workspace)
        return None
    return None


__all__ = [
    "BUILTIN_NAMES",
    "BuiltinOutcome",
    "CdResolution",
    "builtin_name_for",
    "render_help",
    "render_history",
    "resolve_cd",
    "run_cd",
    "run_clear",
]
