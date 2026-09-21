"""Progress-event mapping for dev-update and mode-switch backends.

This module owns the stable step ids, friendly titles, and result-detail
formatting used when backends emit :mod:`sase.update_progress` events. It is
pure (no subprocess calls) so tests can assert the mapping directly.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sase.dev_update.models import DevReconcileStep, RepoCommitLog, RepoDiffStat
from sase.update_progress import (
    NULL_PROGRESS,  # noqa: F401  (re-exported for backend defaults)
    NullProgress,
    OutputSink,
    UpdateProgress,
)

CHECK_STEP_ID = "check"
CHECK_STEP_TITLE = "Check for updates"
MERGE_STEP_ID = "merge"
MERGE_STEP_TITLE = "Fast-forward checkouts"

_RECONCILE_TITLES = {
    "uv_tool_install": "Reinstall editable Python packages",
    "rust_prebuild_install": "Install prebuilt Rust core",
    "rust_dev_install": "Rebuild Rust core into uv-tool venv",
    "rust_install_uv_tool": "Rebuild Rust core into uv-tool venv",
    "rust_health_check": "Verify sase-core-rs imports",
    "rust_lsp_install": "Install xprompt LSP",
}


def is_active_progress(progress: UpdateProgress) -> bool:
    """Whether *progress* observes events (i.e. is not the null sink)."""
    return not isinstance(progress, NullProgress)


def check_child_id(git_root: str) -> str:
    """Return the stable ``check`` child id for a git root."""
    return f"{CHECK_STEP_ID}:{git_root}"


def merge_child_id(git_root: str) -> str:
    """Return the stable ``merge`` child id for a git root."""
    return f"{MERGE_STEP_ID}:{git_root}"


def reconcile_step_id(index: int) -> str:
    """Return the stable step id for the *index*-th reconcile step."""
    return f"reconcile:{index}"


def switch_step_id(index: int) -> str:
    """Return the stable step id for the *index*-th mode-switch command."""
    return f"switch:{index}"


def merge_child_title(display_name: str) -> str:
    """Return the ``merge`` child title for a repo display name."""
    return f"Fast-forward {display_name}"


def reconcile_step_title(step: DevReconcileStep) -> str:
    """Return the friendly timeline title for a reconcile step."""
    return _RECONCILE_TITLES.get(step.kind, step.label)


def root_display_names(roots: Sequence[str]) -> dict[str, str]:
    """Map each git root to a short display name.

    The name is the checkout directory basename. When basenames collide,
    the colliding roots are disambiguated with their parent directory
    name (``parent/base``); a root still colliding after that keeps its
    full path. Full paths always remain available to the log sink via
    the ``command`` event.
    """
    by_base: dict[str, list[str]] = {}
    for root in roots:
        by_base.setdefault(Path(root).name or root, []).append(root)
    names: dict[str, str] = {}
    for base, group in by_base.items():
        if len(group) == 1:
            names[group[0]] = base
            continue
        by_parent: dict[str, list[str]] = {}
        for root in group:
            by_parent.setdefault(f"{Path(root).parent.name}/{base}", []).append(root)
        for qualified, qualified_group in by_parent.items():
            if len(qualified_group) == 1:
                names[qualified_group[0]] = qualified
            else:
                for root in qualified_group:
                    names[root] = root
    return names


def format_merge_detail(
    old_head: str | None,
    new_head: str | None,
    commits: RepoCommitLog | None,
    diffstat: RepoDiffStat | None,
) -> str | None:
    """Format a successful fast-forward result detail, or ``None`` when empty."""
    parts: list[str] = []
    if old_head and new_head:
        parts.append(f"{old_head[:7]} → {new_head[:7]}")
    if commits is not None:
        noun = "commit" if commits.total == 1 else "commits"
        parts.append(f"{commits.total} {noun}")
    if diffstat is not None and diffstat.has_line_changes:
        parts.append(f"+{diffstat.insertions} \u2212{diffstat.deletions}")
    return " · ".join(parts) or None


def output_sink_for(progress: UpdateProgress, step_id: str) -> OutputSink | None:
    """Return the output sink bound to *step_id*, or ``None`` when inactive.

    ``None`` preserves the legacy captured subprocess behavior, so injected
    test fakes that do not accept ``on_output`` keep working when no
    progress session is active.
    """
    if not is_active_progress(progress):
        return None
    return progress.output_sink(step_id)


def record_command(
    progress: UpdateProgress,
    step_id: str,
    argv: Sequence[str],
    cwd: str | None,
) -> None:
    """Emit a ``command`` event for the log sink when progress is active."""
    if is_active_progress(progress):
        progress.command(step_id, tuple(argv), cwd)


__all__ = [
    "CHECK_STEP_ID",
    "CHECK_STEP_TITLE",
    "MERGE_STEP_ID",
    "MERGE_STEP_TITLE",
    "NULL_PROGRESS",
    "check_child_id",
    "format_merge_detail",
    "is_active_progress",
    "merge_child_id",
    "merge_child_title",
    "output_sink_for",
    "reconcile_step_id",
    "reconcile_step_title",
    "record_command",
    "root_display_names",
    "switch_step_id",
]
