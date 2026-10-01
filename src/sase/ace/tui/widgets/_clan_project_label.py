"""Shared clan project-label rendering for clan rows and CLAN headers."""

from __future__ import annotations

from rich.text import Text

# Matches agent-row titles and the header's ``Project:`` field.
CLAN_PROJECT_LABEL_COLOR = "#00D7AF"
CLAN_PROJECT_LABEL_LIMIT = 2


def append_clan_project_label(
    text: Text,
    labels: tuple[str, ...],
    *,
    bold: bool = False,
    limit: int | None = CLAN_PROJECT_LABEL_LIMIT,
) -> None:
    """Append capped teal project labels with a dim `` +N`` overflow."""
    if not labels:
        return
    visible = labels if limit is None else labels[:limit]
    style = f"bold {CLAN_PROJECT_LABEL_COLOR}" if bold else CLAN_PROJECT_LABEL_COLOR
    for index, label in enumerate(visible):
        if index:
            text.append(", ", style="dim")
        text.append(label, style=style)
    dropped = len(labels) - len(visible)
    if dropped > 0:
        text.append(f" +{dropped}", style="dim")


__all__ = [
    "CLAN_PROJECT_LABEL_COLOR",
    "CLAN_PROJECT_LABEL_LIMIT",
    "append_clan_project_label",
]
