"""App title / version helpers for the ACE TUI header.

The header title shows the running ``sase`` version. Resolution is two-phased so
the title is instant at ``__init__`` (I/O-free) yet refines to a git-derived dev
version shortly after mount for editable installs:

- :func:`initial_app_version` — the cheap, I/O-free release string for ``__init__``.
- :func:`resolved_app_version` — the fully resolved version, safe to call only
  off the event loop (blocks on git subprocesses for editable installs).
- :func:`format_app_title` — the single title format shared by both writers.
"""

from __future__ import annotations

import sase


def initial_app_version() -> str:
    """Return the cheap, I/O-free version string for ``AceApp.__init__``.

    Uses the release-please-managed ``sase.__version__`` so the header title can
    be set synchronously during construction without touching disk or git.
    """
    return sase.__version__


def resolved_app_version() -> str | None:
    """Return the fully resolved host display version, or ``None``.

    Delegates to :func:`sase.version.host_display_version`, which may block on
    git subprocesses for editable installs, so this MUST be called off the
    Textual event loop (e.g. via ``asyncio.to_thread``). Title refinement is
    best-effort: any failure is swallowed and reported as ``None`` so a broken
    version probe can never break TUI startup.
    """
    try:
        from sase.version import host_display_version

        return host_display_version()
    except Exception:
        return None


def format_app_title(version: str) -> str:
    """Return the ACE header title for ``version`` (e.g. ``sase ace (v0.7.1)``)."""
    return f"sase ace (v{version})"
