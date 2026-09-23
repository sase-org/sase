"""Pure toast copy for host-owned ``$`` link-follow reveals.

The reveal engine (:mod:`sase.ace.link_reveal_context`) decides *what* a jump
rewrote; this module decides *what the toast says*. It turns a
:class:`~sase.ace.link_reveal_context.RevealOutcome` plus live key names and
the destination pane's accent into a ``(title, markup message)`` pair exactly
as the artifact-link-jumps design specifies::

    ↪ Bead sase-16n.7
    query  id:sase-16n.* limit:100
    was    -status:closed limit:100 · hidden by -status:closed
    epic sase-16n · ^ restore · ctrl+o back

Every dynamic value is escaped with :func:`textual.markup.escape`, so a
hostile query or id can never break the toast's markup. Key names arrive
already resolved through :func:`sase.ace.tui.keymaps.display.key_display_name`
from the live keymap registry -- they are never hard-coded here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from textual.markup import escape
from textual.notifications import SeverityLevel

from sase.ace.link_reveal_context import HiddenReason, RevealOutcome

from ..relations.link_keys import short_ref_label

#: How long a reveal toast stays on screen (information severity).
REVEAL_TOAST_TIMEOUT = 8.0

#: Shown when the scope was or is the spec-wide "all projects" scope.
ALL_PROJECTS_LABEL = "All projects"

LinkFailureKind = Literal["dangling", "load", "unconfigured", "missing"]


def _scope_display_name(scope: str | None, names: Mapping[str, str]) -> str:
    """Return the toast-facing name for an Artifacts project *scope*.

    *names* maps canonical project keys to the display names the Artifacts
    pane itself shows, so the toast never prints a raw directory key; an
    unknown key falls back to itself.
    """
    if scope is None:
        return ALL_PROJECTS_LABEL
    return names.get(scope) or scope


def _describe_scope_change(
    change: tuple[str | None, str | None] | None,
    names: Mapping[str, str],
) -> str | None:
    """Return the ``scope`` toast line for *change*, or ``None``.

    *change* is the transaction's ``(old, new)`` scope pair, where ``None``
    means the All-projects scope.
    """
    if change is None:
        return None
    old, new = change
    old_name = escape(_scope_display_name(old, names))
    new_name = escape(_scope_display_name(new, names))
    return f"scope  {old_name} → {new_name}"


def _describe_hidden_reason(hidden: HiddenReason) -> str:
    """Return the trailing reason phrase for the toast's ``was`` line."""
    if hidden.kind == "filtered":
        terms = ", ".join(f"[bold]{escape(term)}[/]" for term in hidden.terms)
        return f"hidden by {terms}" if terms else "hidden by your query"
    if hidden.kind == "filtered_boolean":
        return "hidden by your query"
    if hidden.kind == "limited":
        return (
            f"past limit:{hidden.cap}" if hidden.cap is not None else "past the limit"
        )
    if hidden.kind == "scoped":
        return "hidden by the project scope"
    hint = hidden.hint or "not in the loaded rows"
    return escape(hint)


def format_reveal_toast(
    outcome: RevealOutcome,
    *,
    restore_key: str = "",
    back_key: str = "",
    accent: str = "cyan",
    scope_names: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Return the ``(title, markup message)`` toast for one reveal.

    *restore_key* names the live ``prev_query`` binding (``^``) and
    *back_key* names the binding that dispatches ``_walk_link_trail_back``
    (``ctrl+o``); either segment is dropped when its key is unknown rather
    than guessed. *accent* is the destination pane's accent color, used for
    the new-query line only. *scope_names* maps project keys in the
    outcome's scope change to their display names.
    """
    title = f"↪ {outcome.pane_label} {short_ref_label(outcome.ref)}"
    lines = [
        f"query  [bold {accent}]{escape(outcome.new_canonical)}[/]",
        f"[dim]was    {escape(outcome.old_canonical)} · {_describe_hidden_reason(outcome.hidden)}[/]",
    ]
    key_segments: list[str] = []
    if outcome.context_label:
        key_segments.append(escape(outcome.context_label))
    if restore_key:
        key_segments.append(f"{escape(restore_key)} restore")
    if back_key:
        key_segments.append(f"{escape(back_key)} back")
    if key_segments:
        lines.append(" · ".join(key_segments))
    scope_line = _describe_scope_change(outcome.scope_change, scope_names or {})
    if scope_line is not None:
        lines.append(scope_line)
    if outcome.hydrated:
        lines.append("fetched  outside the loaded rows")
    if outcome.agents_tab_fallback:
        lines.append("Agents tab filter hides it — showing Artifacts ▸ Agent")
    return title, "\n".join(lines)


def format_link_failure(
    kind: LinkFailureKind,
    *,
    ref: str,
    pane_label: str = "",
    detail: str = "",
) -> tuple[str, str, SeverityLevel]:
    """Return the ``(title, message, severity)`` triple for a failed jump.

    Every case names the artifact in the title and carries exactly one
    reason line: a dangling ref, a pane load failure, an unconfigured pane,
    or a target genuinely outside the pane's inventory.
    """
    short = short_ref_label(ref)
    if kind == "dangling":
        return (
            f"No such artifact: {short}",
            f"No pane resolves {escape(ref)}; the link may be stale or mistyped.",
            "warning",
        )
    if kind == "load":
        pane = pane_label or "the destination pane"
        return (
            f"Cannot load {short}",
            f"{escape(pane)} failed to load for {escape(ref)}.",
            "error",
        )
    if kind == "unconfigured":
        pane = pane_label or "destination"
        extra = f" {escape(detail)}" if detail else ""
        return (
            f"Cannot follow {short}",
            f"The {escape(pane)} pane is not configured; configure its provider to enable this link.{extra}",
            "warning",
        )
    pane = pane_label or "The destination pane"
    return (
        f"Not in {pane}: {short}",
        f"{escape(pane)} has no {escape(ref)} in its inventory.",
        "warning",
    )


__all__ = [
    "ALL_PROJECTS_LABEL",
    "REVEAL_TOAST_TIMEOUT",
    "LinkFailureKind",
    "format_link_failure",
    "format_reveal_toast",
]
