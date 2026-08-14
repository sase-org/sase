"""Shared display identity for SASE sessions.

The chip built here is the visual thread tying a row to the TUI it came from:
the same handle and the same color render in ``sase proc list`` and in the
Admin Center. Every helper is pure — no file reads, no process probes — so it
is safe to call from a render or keystroke path.
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Mapping
from typing import Any

from rich.text import Text

from .registry import SessionIdentity

SESSION_HANDLE_LENGTH = 4

# Unambiguous base32: no ``i``/``l``/``o``/``u``, so a handle read off a
# terminal can be typed back as a ``--session`` reference.
_HANDLE_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"

# Drawn from the ACE tribe/status hues so session colors sit alongside the
# rest of the palette instead of competing with it.
SESSION_PALETTE: tuple[str, ...] = (
    "#5FAFFF",
    "#5FD7AF",
    "#FFAF00",
    "#FF5FAF",
    "#AF87D7",
    "#87D75F",
    "#FFD75F",
    "#FF875F",
)

NO_SESSION_MARK = "—"
DEAD_SESSION_MARK = "†"
_DEAD_STYLE = "dim"
_ABSENT_STYLE = "dim"


def short_session_handle(session_id: str) -> str:
    """Return the stable 4-character handle for a session id."""
    digest = _digest(session_id)
    return "".join(
        _HANDLE_ALPHABET[digest[index] % len(_HANDLE_ALPHABET)]
        for index in range(SESSION_HANDLE_LENGTH)
    )


def session_color(session_id: str) -> str:
    """Return the deterministic palette color for a session id."""
    digest = _digest(session_id)
    return SESSION_PALETTE[digest[-1] % len(SESSION_PALETTE)]


def session_display_label(identity: SessionIdentity) -> str:
    """Return the denormalized session label, e.g. ``ace·sase#24``.

    Task rows store this alongside the session id so a session that has since
    exited still renders with a name instead of a bare handle.
    """
    label = identity.kind or "session"
    if identity.project:
        label = f"{label}·{identity.project}"
        if identity.workspace_num is not None:
            label = f"{label}#{identity.workspace_num}"
    return label


def session_chip(
    source: SessionIdentity | Mapping[str, Any] | None,
    *,
    live_session_ids: Collection[str] | None = None,
) -> Text:
    """Render the shared session badge, e.g. ``ace·sase#24 4f2a``.

    Args:
        source: A :class:`SessionIdentity`, or any mapping carrying
            ``session_id`` and an optional ``session_label`` (a task row).
            ``None`` — or a row with no session — renders as a dim em dash.
        live_session_ids: Session ids known to be live. When supplied, a
            session outside it renders dim with a ``†`` marker. Callers pass
            the ids they already loaded so this stays free of I/O.

    Returns:
        A :class:`rich.text.Text` badge.
    """
    session_id, label = _chip_parts(source)
    if not session_id:
        return Text(NO_SESSION_MARK, style=_ABSENT_STYLE)

    handle = short_session_handle(session_id)
    body = f"{label} {handle}" if label else handle
    if live_session_ids is not None and session_id not in live_session_ids:
        return Text(f"{body} {DEAD_SESSION_MARK}", style=_DEAD_STYLE)
    return Text(body, style=session_color(session_id))


def _chip_parts(
    source: SessionIdentity | Mapping[str, Any] | None,
) -> tuple[str, str]:
    if source is None:
        return "", ""
    if isinstance(source, SessionIdentity):
        return source.session_id, session_display_label(source)
    session_id = source.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return "", ""
    label = source.get("session_label")
    return session_id, label if isinstance(label, str) and label else ""


def _digest(session_id: str) -> bytes:
    return hashlib.blake2b(session_id.encode("utf-8"), digest_size=8).digest()
