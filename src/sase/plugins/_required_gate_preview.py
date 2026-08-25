"""Human-facing text rendered by the PluginsRequired gate.

Every renderer here is reconstructed byte for byte by gate validation, so all
of it is a pure function of the persisted payload. The project label is pinned
at create time rather than looked up live, so a later rename cannot invalidate
a pending bundle.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_PLUGIN_COLUMNS = ("Plugin", "Problem", "Command")


def render_plugins_required_preview(payload: Any) -> str:
    """Render the reviewed Markdown detail shown by ACE and mobile clients."""
    label = str(_attr(payload, "project_label"))
    missing: Sequence[Any] = _attr(payload, "missing")
    count = len(missing)
    noun = "plugin" if count == 1 else "plugins"
    intro = (
        f"{label} declares required plugins that are not installed, or that "
        f"do not satisfy their version specifier. Choosing **Install** runs "
        f"one combined install for every missing requirement, using one "
        f"bounded public-index probe and per-plugin index or definitive-404 "
        f"git source resolution. A "
        f"successful install restarts axe. Choosing **Dismiss** hides this "
        f"gate until the required set changes. Agent and non-interactive "
        f"contexts still fail closed and never auto-install."
    )
    rows = [_preview_row(item) for item in missing]
    table = _markdown_table(_PLUGIN_COLUMNS, rows)
    return f"# Missing required {noun}\n\n**Project:** {label}\n\n{intro}\n\n{table}\n"


def plugins_required_presentation_note(payload: Any) -> str:
    """Return the one-line notification note for one required-plugin gate."""
    count = len(_attr(payload, "missing"))
    noun = "plugin" if count == 1 else "plugins"
    label = str(_attr(payload, "project_label"))
    return f"{count} required {noun} to install · {label}"


def _preview_row(item: Any) -> tuple[str, ...]:
    kind = str(_attr(item, "kind"))
    problem = (
        "not installed" if kind == "missing" else "installed version does not match"
    )
    return (
        str(_attr(item, "name") or _attr(item, "requirement")),
        problem,
        f"`{_attr(item, 'install_command')}`",
    )


def _attr(item: Any, name: str) -> Any:
    if isinstance(item, Mapping):
        return item[name]
    return getattr(item, name)


def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    header = "| " + " | ".join(headers) + " |"
    divider = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(_table_cell(cell) for cell in row) + " |" for row in rows]
    return "\n".join([header, divider, *body])


def _table_cell(value: str) -> str:
    return value.replace("\n", " ").replace("|", "\\|")


__all__ = [
    "plugins_required_presentation_note",
    "render_plugins_required_preview",
]
