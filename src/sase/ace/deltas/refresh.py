"""DELTAS refresh orchestrator — compute + persist in one best-effort call.

This is the single entry point that lifecycle hooks (commit-entry creation,
rewind, sync, accept-proposal, re-parent) call to keep a ChangeSpec's
``DELTAS`` field in sync with the underlying VCS state.

The function is deliberately failure-tolerant: a VCS lookup failure leaves
the existing DELTAS untouched, and any unexpected exception is logged and
swallowed so the calling workflow (the commit, the sync, etc.) is never
blocked on delta refresh.
"""

from __future__ import annotations

import logging
import os

from sase.vcs_provider import get_vcs_provider

from .compute import DeltaComputationError, compute_deltas
from .persistence import update_changespec_deltas_field


_log = logging.getLogger(__name__)


def _find_changespec(project_file: str, changespec_name: str) -> object | None:
    try:
        from ..changespec import parse_project_file
    except ImportError:  # pragma: no cover
        return None

    try:
        for cs in parse_project_file(project_file):
            if cs.name == changespec_name:
                return cs
    except Exception as exc:
        _log.warning(
            "Failed to parse %s while refreshing deltas for %s: %s",
            project_file,
            changespec_name,
            exc,
        )
    return None


def refresh_deltas_for_changespec(
    project_file: str,
    changespec_name: str,
    workspace_dir: str | None = None,
) -> bool:
    """Recompute DELTAS for *changespec_name* and persist atomically.

    Args:
        project_file: Path to the ``.gp`` project file.
        changespec_name: NAME of the ChangeSpec to refresh.
        workspace_dir: VCS workspace directory. Defaults to ``os.getcwd()``
            when not provided.

    Returns:
        True when DELTAS was successfully refreshed; False on any failure
        (parse error, VCS query failure, lock timeout, etc.). Failures are
        logged but never raised — callers can ignore the return value.
    """
    cwd = workspace_dir or os.getcwd()

    changespec = _find_changespec(project_file, changespec_name)
    if changespec is None:
        _log.debug(
            "ChangeSpec %s not found in %s; skipping DELTAS refresh",
            changespec_name,
            project_file,
        )
        return False

    try:
        provider = get_vcs_provider(cwd)
    except Exception as exc:
        _log.warning(
            "VCS provider lookup failed for %s while refreshing %s: %s",
            cwd,
            changespec_name,
            exc,
        )
        return False

    try:
        deltas = compute_deltas(changespec, provider, cwd)  # type: ignore[arg-type]
    except DeltaComputationError as exc:
        # VCS hiccup or missing parent ref — preserve existing DELTAS.
        _log.warning("DELTAS compute failed for %s: %s", changespec_name, exc)
        return False
    except Exception as exc:
        _log.warning(
            "Unexpected error computing DELTAS for %s in %s: %s",
            changespec_name,
            cwd,
            exc,
        )
        return False

    return update_changespec_deltas_field(project_file, changespec_name, deltas)


def refresh_deltas_after_commits_change(
    project_file: str,
    changespec_name: str,
    workspace_dir: str | None = None,
) -> bool:
    """Best-effort DELTAS refresh after COMMITS-affecting mutations.

    Any code path that changes the COMMITS list, accepted proposal set, parent
    base, or VCS head used by a ChangeSpec should call this helper after the
    atomic write.
    """
    try:
        return refresh_deltas_for_changespec(
            project_file, changespec_name, workspace_dir
        )
    except Exception as exc:  # pragma: no cover - refresh_deltas already guards this.
        _log.warning(
            "Unexpected DELTAS post-COMMITS refresh failure for %s in %s: %s",
            changespec_name,
            project_file,
            exc,
        )
        return False
