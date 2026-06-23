"""Pure rendering and filtering helpers for the Config Center config pane."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.text import Text

from sase.config import ConfigField, ConfigSource

from .config_pane_view import (
    ConfigPaneView,
    _DEPRECATED_COLOR,
    _KIND_COLOR,
    _KIND_LABEL,
    _MODIFIED_COLOR,
    _MUTED,
)


def format_value(value: Any) -> str:
    """Render a config value for display (compact JSON for non-strings)."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return repr(value)


def kind_badge(kind: str) -> Text:
    """A small colored badge for a source kind."""
    return Text(_KIND_LABEL.get(kind, kind), style=_KIND_COLOR.get(kind, _MUTED))


def ancestor_paths(path: str) -> list[str]:
    """Dotted ancestor paths of *path*, outermost first (excludes *path*)."""
    parts = path.split(".")
    return [".".join(parts[: i + 1]) for i in range(len(parts) - 1)]


def visible_leaf_paths(
    view: ConfigPaneView, *, filter_text: str = "", modified_only: bool = False
) -> list[str]:
    """Leaf paths passing the active filter + modified-only toggle, in order."""
    query = filter_text.strip().casefold()
    modified = view.modified_paths() if modified_only else None
    result: list[str] = []
    for field in view.field_model.fields:
        if not field.leaf:
            continue
        if modified is not None and field.path not in modified:
            continue
        if query:
            haystack = f"{field.path}\n{field.description}".casefold()
            if query not in haystack:
                continue
        result.append(field.path)
    return result


def visible_paths(
    view: ConfigPaneView, *, filter_text: str = "", modified_only: bool = False
) -> set[str]:
    """Every path to show: the visible leaves plus their ancestor sections."""
    leaves = visible_leaf_paths(
        view, filter_text=filter_text, modified_only=modified_only
    )
    shown: set[str] = set(leaves)
    for leaf in leaves:
        shown.update(ancestor_paths(leaf))
    return shown


def render_row_label(view: ConfigPaneView, path: str) -> Text:
    """Tree row label: name + modified marker + winning-layer badge."""
    field = view.fields_by_path.get(path)
    if field is None:
        return Text(path)
    text = Text()
    if not field.leaf:
        # Section / nested object container.
        text.append(field.name, style="bold")
        return text
    if view.is_modified(path):
        text.append("● ", style=_MODIFIED_COLOR)
    else:
        text.append("  ")
    name_style = f"{_DEPRECATED_COLOR} strike" if view.is_deprecated(path) else ""
    text.append(field.name, style=name_style)
    winning = view.winning_layer(path)
    if winning is not None:
        kind = view.kind_by_layer.get(winning, "other")
        text.append("  ")
        text.append(
            _KIND_LABEL.get(kind, kind), style=f"dim {_KIND_COLOR.get(kind, _MUTED)}"
        )
    return text


def render_source_rail(view: ConfigPaneView) -> Text:
    """Render the source-rail body: one block per config layer."""
    text = Text()
    sources: tuple[ConfigSource, ...] = view.inventory.sources
    if not sources:
        return Text("No config layers discovered.", style=f"italic {_MUTED}")
    for index, source in enumerate(sources):
        if index:
            text.append("\n")
        text.append(source_status_marker(source))
        text.append(" ")
        text.append(source.name, style="bold")
        text.append("\n  ")
        text.append(kind_badge(source.kind))
        text.append("  ", style=_MUTED)
        for badge in source_badges(source):
            text.append_text(badge)
            text.append(" ")
        text.append(
            f"\n  {source.list_strategy} · {source.key_count} keys", style=_MUTED
        )
        if source.path:
            text.append(f"\n  {abbreviate_path(source.path)}", style=f"dim {_MUTED}")
        if source.error:
            text.append(f"\n  ! {source.error}", style=_DEPRECATED_COLOR)
    return text


def source_status_marker(source: ConfigSource) -> Text:
    """A leading status glyph for a source row."""
    if source.error:
        return Text("✗", style=_DEPRECATED_COLOR)
    if not source.exists:
        return Text("○", style=_MUTED)
    return Text("●", style=_KIND_COLOR.get(source.kind, "#00D7AF"))


def source_badges(source: ConfigSource) -> list[Text]:
    """State badges for a source row (loaded/missing/invalid/read-only)."""
    badges: list[Text] = []
    if source.error:
        badges.append(Text("invalid", style=_DEPRECATED_COLOR))
    elif not source.exists:
        badges.append(Text("missing", style=_MUTED))
    else:
        badges.append(Text("loaded", style="#5FAF5F"))
    if not source.writable:
        badges.append(Text("read-only", style=_MUTED))
    if source.deprecated_keys:
        badges.append(
            Text(f"{len(source.deprecated_keys)} deprecated", style=_DEPRECATED_COLOR)
        )
    if source.unsupported_keys:
        badges.append(
            Text(f"{len(source.unsupported_keys)} unsupported", style=_DEPRECATED_COLOR)
        )
    return badges


def abbreviate_path(path: str) -> str:
    """Shorten a filesystem path against ``$HOME`` for display."""
    try:
        home = str(Path.home())
    except (OSError, RuntimeError):
        return path
    if home and path.startswith(home):
        return "~" + path[len(home) :]
    return path


def render_detail(view: ConfigPaneView, path: str | None) -> Text:
    """Render the detail / provenance body for the selected *path*."""
    if path is None:
        return Text(
            "Select a field to inspect its value and provenance.",
            style=f"italic {_MUTED}",
        )
    field = view.fields_by_path.get(path)
    if field is None:
        return Text(path)
    text = Text()
    text.append(field.path, style="bold #00D7AF")
    text.append("\n")
    if not field.leaf:
        render_section_detail(view, field, text)
    else:
        render_leaf_detail(view, field, text)
    render_field_diagnostics(view, path, text)
    return text


def render_section_detail(view: ConfigPaneView, field: ConfigField, text: Text) -> None:
    children = [
        child for child in view.field_model.fields if child.parent == field.path
    ]
    text.append("section", style=_MUTED)
    text.append(f" · {len(children)} field(s)\n")
    if field.description:
        text.append(f"\n{field.description}\n", style=_MUTED)


def render_leaf_detail(view: ConfigPaneView, field: ConfigField, text: Text) -> None:
    type_label = "/".join(field.types) if field.types else field.kind
    text.append("type: ", style=_MUTED)
    text.append(type_label or "—")
    if field.enum_values:
        text.append("  enum: ", style=_MUTED)
        text.append(", ".join(format_value(v) for v in field.enum_values))
    if view.is_deprecated(field.path):
        text.append("  ")
        text.append("DEPRECATED", style=f"bold {_DEPRECATED_COLOR}")
        replacement = view.deprecation_replacement(field.path)
        if replacement:
            text.append(f" → {replacement}", style=_DEPRECATED_COLOR)
    text.append("\n")
    if field.description:
        text.append(f"\n{field.description}\n", style=_MUTED)

    state = view.state_by_path.get(field.path)
    text.append("\ndefault:   ", style=_MUTED)
    if field.has_default:
        text.append(format_value(field.default))
    else:
        text.append("(none)", style=f"italic {_MUTED}")
    text.append("\neffective: ", style=_MUTED)
    if state is not None and state.has_effective:
        text.append(format_value(state.effective_value), style="bold")
    else:
        text.append("(unset)", style=f"italic {_MUTED}")
    text.append("\n")

    render_provenance(view, field.path, text)


def render_provenance(view: ConfigPaneView, path: str, text: Text) -> None:
    state = view.state_by_path.get(path)
    text.append("\nProvenance", style="bold")
    text.append("  (low → high priority)\n", style=_MUTED)
    if state is None or not state.contributions:
        text.append("  no layer sets this field\n", style=f"italic {_MUTED}")
        return
    for contribution in state.contributions:
        kind = view.kind_by_layer.get(contribution.layer, "other")
        marker = "▶" if contribution.winning else " "
        style = "bold" if contribution.winning else _MUTED
        text.append(
            f"  {marker} ", style=_MODIFIED_COLOR if contribution.winning else _MUTED
        )
        text.append(
            contribution.layer, style=f"{style} {_KIND_COLOR.get(kind, _MUTED)}"
        )
        text.append("  ")
        text.append(format_value(contribution.raw_value), style=style)
        text.append("\n")


def render_field_diagnostics(view: ConfigPaneView, path: str, text: Text) -> None:
    diagnostics = [d for d in view.inventory.diagnostics if d.path == path]
    if not diagnostics:
        return
    text.append("\nDiagnostics\n", style="bold")
    for diagnostic in diagnostics:
        color = _DEPRECATED_COLOR if diagnostic.severity == "error" else "#FFAF5F"
        text.append(f"  {diagnostic.severity}: ", style=color)
        text.append(diagnostic.message, style=_MUTED)
        if diagnostic.layer:
            text.append(f" [{diagnostic.layer}]", style=f"dim {_MUTED}")
        text.append("\n")
