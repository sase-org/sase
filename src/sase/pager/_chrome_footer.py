"""Availability-driven footer legend for the pager.

No Textual imports here: everything is a plain function from document/section
state to a Rich :class:`~rich.text.Text`, so the shapes are unit-testable
without booting an App.
"""

from __future__ import annotations

from collections.abc import Sequence

from rich.text import Text


def footer_legend(
    *,
    section_total: int,
    label_count: int = 0,
    pending_prefix: str = "",
    pending_action: str = "follow",
    trail_back_count: int = 0,
    trail_forward_count: int = 0,
    status: str | None = None,
    history_pinned: bool = False,
    time_verbs: Sequence[tuple[str, str]] | None = None,
    split: bool = False,
    pane_count: int | None = None,
    other_target_label: str | None = None,
) -> Text:
    """Build the availability-driven footer legend.

    Only verbs that would sometimes do nothing are worth a row (the ACE
    footer convention, matched here): plain scrolling (``j``/``k``/``g``/``G``
    /``ctrl+d``/``ctrl+u``) is always available so it lives in ``?`` only.
    History verbs appear only when a provider owns the current section.

    ``time_verbs`` is the ordered destination list built from the version
    moment (``( vK``, ``) vK``/``) now``, ``} now``/``} deleted``,
    ``= diff``/``= read``, ``@ timeline``).

    ``split`` adds the ``^F`` pane verb and names ``q`` "close pane",
    since it closes only the focused pane while split. ``pane_count``
    overrides ``split``: with three panes the verb reads ``^F/^B pane``.
    ``other_target_label`` names an armed ``ctrl+w`` target with its
    position glyph (for example ``"◲ bottom-right"``).
    """
    panes = pane_count if pane_count is not None else (2 if split else 1)
    verbs: list[tuple[str, str]] = []
    if status is not None:
        verbs.append(("…", status))
    if time_verbs is not None:
        verbs.extend(time_verbs)
        # A pinned section names its edit verb here ("E edit now"); the
        # label layer must not add a second "E edit".
        label_has_edit = False
        if history_pinned:
            verbs.append(("E", "edit now"))
            label_has_edit = True
    else:
        label_has_edit = False
    action_key = {"copy": "y", "edit": "E", "other": "^W"}.get(pending_action)
    if action_key is not None:
        action_label = "other pane" if pending_action == "other" else pending_action
        if pending_action == "other" and other_target_label:
            action_label = f"{action_label} {other_target_label}"
        verbs.append((f"{action_key}{pending_prefix}…", action_label))
    elif pending_prefix:
        verbs.append((f"{pending_prefix}…", "link"))
    elif label_count:
        verbs.append(("0-9a-z", "follow"))
        verbs.append(("y", "copy"))
        if not label_has_edit:
            verbs.append(("E", "edit"))
    if trail_back_count:
        verbs.append(("⌫/^O", "back"))
    if trail_forward_count:
        verbs.append(("^I", "forward"))
    if section_total > 1:
        verbs.append(("^N/^P", "entity"))
    if panes >= 3:
        verbs.append(("^F/^B", "pane"))
    elif panes == 2:
        verbs.append(("^F", "pane"))
    verbs.append(("/", "search"))
    help_label = "trail/keys" if trail_back_count or trail_forward_count else "keys"
    verbs.append(("?", help_label))
    verbs.append(("q", "close pane" if split else "close"))

    line = Text()
    for index, (key, label) in enumerate(verbs):
        if index > 0:
            line.append(" · ", style="dim")
        line.append(key, style="bold")
        if label:
            line.append(f" {label}")
    return line


__all__ = [
    "footer_legend",
]
