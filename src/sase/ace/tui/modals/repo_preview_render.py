"""Pure render helpers for the ACE repo-mention preview card."""

from __future__ import annotations

from typing import Any

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from sase.xprompt.highlight_theme import derive_argument_color
from sase.xprompt.repo_mention_catalog import RepoMention

_COLOR_MUTED = "dim"
_COLOR_LABEL = "dim"
_COLOR_TITLE = "bold"
_FALLBACK_ACCENT = "#C3ABD8"
_PILL_FOREGROUND = "#1a1a1a"


def repo_card_accent(theme: Any) -> str:
    """Return the theme-derived repo-mention accent used by prompt highlighting."""
    background = getattr(theme, "background", None) or "#000000"
    accent = derive_argument_color(
        getattr(theme, "accent", None),
        foreground=getattr(theme, "foreground", None),
        background=background,
    )
    return accent or _FALLBACK_ACCENT


def build_repo_title(
    mention: RepoMention,
    *,
    matched_text: str | None,
    accent: str,
) -> RenderableType:
    """Build the card title with an optional matched-text disclosure line."""
    identity = Text()
    identity.append("R", style=f"bold {accent}")
    identity.append(" ")
    identity.append("REPO", style=f"bold {accent}")
    identity.append("  ")
    identity.append(mention.identifier, style=_COLOR_TITLE)

    project_name = mention.record.project
    if project_name:
        first_line = Table.grid(expand=True, padding=(0, 0, 0, 2))
        first_line.add_column(ratio=1, overflow="ellipsis")
        first_line.add_column(justify="right", no_wrap=True)
        first_line.add_row(identity, Text(project_name, style=f"bold {accent}"))
        lines: list[RenderableType] = [first_line]
    else:
        lines = [identity]

    if _should_show_matched_text(mention, matched_text):
        match = Text()
        match.append('matched "', style=_COLOR_MUTED)
        match.append(matched_text or "", style=f"bold underline {accent}")
        match.append('"', style=_COLOR_MUTED)
        lines.append(match)
    return Group(*lines)


def build_repo_chips(mention: RepoMention, *, accent: str) -> Text:
    """Build the kind / auto-clone / auto-sync / env chip row."""
    record = mention.record
    text = Text()
    _append_chip(text, record.kind.upper(), accent=accent)
    if record.auto_clone:
        _append_chip(text, "AUTO-CLONE", accent=accent)
    if record.auto_sync:
        _append_chip(text, "AUTO-SYNC", accent=accent)
    if record.env_name:
        _append_chip(text, f"ENV {record.env_name}", accent=accent)
    return text


def build_repo_property_grid(
    mention: RepoMention,
    *,
    checkout_display: str,
    clones_display: str | None,
    accent: str | None = None,
) -> RenderableType:
    """Build the aligned project/kind/checkout/clones/remote/declared grid."""
    record = mention.record
    rows: list[tuple[str, str]] = []
    if record.project:
        rows.append(("Project", record.project))
    rows.append(("Kind", record.kind))
    rows.append(("Checkout", checkout_display))
    if clones_display:
        rows.append(("Clones", clones_display))
    if record.remote_url:
        rows.append(("Remote", record.remote_url))
    declared = _repo_declaration_display(mention)
    if declared:
        rows.append(("Declared", declared))

    grid = Table.grid(expand=True, padding=(0, 2, 0, 0))
    grid.add_column(no_wrap=True)
    grid.add_column(ratio=1, overflow="fold")
    for label, value in rows:
        grid.add_row(
            Text(label, style=_COLOR_LABEL),
            Text(value, style=accent or ""),
        )
    return grid


def repo_checkout_path(
    mention: RepoMention,
    *,
    workspace_num: int | None,
) -> tuple[str, bool]:
    """Return ``(path, exists)`` for *mention*'s checkout.

    Prefers the clone registered for *workspace_num* when one is known, else
    falls back to the record's own path.
    """
    record = mention.record
    clone = (
        record.clone_for_workspace(workspace_num) if workspace_num is not None else None
    )
    if clone is not None:
        return clone.path, clone.exists
    return record.path, record.exists


def repo_checkout_display(path: str, *, exists: bool) -> str:
    """Return the checkout path, annotated when it is not cloned locally."""
    return path if exists else f"{path} (not cloned)"


def repo_not_cloned_hint(mention: RepoMention, *, exists: bool) -> str | None:
    """Return the materialize-checkout hint line, or ``None`` when cloned."""
    if exists:
        return None
    return f"Run `sase repo open {mention.identifier}` to materialize this checkout."


def repo_clones_display(mention: RepoMention) -> str | None:
    """Return ``"<existing> of <registered> workspaces"``, or ``None`` when absent."""
    clones = mention.record.clones
    if not clones:
        return None
    existing = sum(1 for clone in clones if clone.exists)
    return f"{existing} of {len(clones)} workspaces"


def repo_source_path(mention: RepoMention) -> str | None:
    """Return the declaration source path for a repo mention, if resolvable."""
    return mention.config_path


def repo_declaration_position(mention: RepoMention) -> tuple[int | None, int | None]:
    """Return one-based declaration line/column metadata for editor handoffs."""
    return mention.config_line, mention.config_col


def _repo_declaration_display(mention: RepoMention) -> str | None:
    """Return a displayable declaration path with an optional line/col suffix."""
    path = repo_source_path(mention)
    if path is None:
        return None
    line, col = repo_declaration_position(mention)
    if line is None:
        return path
    if col is None:
        return f"{path}:{line}"
    return f"{path}:{line}:{col}"


def _append_chip(text: Text, label: str, *, accent: str) -> None:
    if text.plain:
        text.append(" ")
    text.append(f" {label} ", style=f"bold {_PILL_FOREGROUND} on {accent}")


def _should_show_matched_text(mention: RepoMention, matched_text: str | None) -> bool:
    if not matched_text:
        return False
    return matched_text != mention.identifier


__all__ = [
    "build_repo_chips",
    "build_repo_property_grid",
    "build_repo_title",
    "repo_card_accent",
    "repo_checkout_display",
    "repo_checkout_path",
    "repo_clones_display",
    "repo_declaration_position",
    "repo_not_cloned_hint",
    "repo_source_path",
]
