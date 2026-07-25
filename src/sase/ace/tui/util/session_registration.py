"""Register the running ACE process in the live-session registry.

Registration is startup-path work, so it stays cheap: the checkout marker
already sitting in the workspace answers project and workspace number without
a plugin round trip. Every failure is swallowed — a missing session record
costs a chip in a task list, never a TUI that will not start.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


def register_ace_session(title: str | None = None) -> None:
    """Record this ACE process as a live session."""
    try:
        from sase.sessions import SESSION_KIND_ACE, register_session

        cwd = os.getcwd()
        project, workspace_num = _project_context(cwd)
        register_session(
            SESSION_KIND_ACE,
            project=project,
            workspace_num=workspace_num,
            cwd=cwd,
            title=title,
        )
    except Exception:
        log.debug("ACE session registration failed", exc_info=True)


def unregister_ace_session() -> None:
    """Drop this ACE process's live-session record."""
    try:
        from sase.sessions import unregister_session

        unregister_session()
    except Exception:
        log.debug("ACE session unregistration failed", exc_info=True)


def _project_context(cwd: str) -> tuple[str | None, int | None]:
    """Return the ``(project, workspace_num)`` this process is running in."""
    try:
        from sase.workspace_provider.marker import find_marker_from_cwd

        found = find_marker_from_cwd(cwd)
        if found is not None:
            _checkout_dir, marker = found
            return (marker.project_name or None, marker.workspace_num)
    except Exception:
        log.debug("checkout marker lookup failed", exc_info=True)

    try:
        from sase.xprompt.loader import detect_project

        return detect_project(), None
    except Exception:
        log.debug("project detection failed", exc_info=True)
        return None, None
