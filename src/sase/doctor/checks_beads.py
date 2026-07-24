"""Bead store checks for ``sase doctor``."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sase.bead.project import BEADS_DIRNAME, BEADS_DIRNAME_NON_VC
from sase.bead.sync import bead_state_is_clean
from sase.core import bead_read_facade as rust_beads
from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck
from sase.doctor.checks_project import resolve_current_project_record

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_MAX_DETAIL_ROWS = 10


def bead_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return default bead check specs."""
    return (
        CheckSpec(
            id="project.beads",
            group="project",
            title="Project beads",
            runner=lambda: _check_project_beads(context),
        ),
    )


def _check_project_beads(context: DoctorContext) -> DiagnosticCheck:
    """Adapt the read-only bead doctor output into one diagnostic check."""
    beads_dir = _find_existing_beads_dir(context)
    if beads_dir is None:
        return DiagnosticCheck(
            id="project.beads",
            group="project",
            status="SKIP",
            title="Project beads",
            summary="no bead store found for this checkout or project",
            data={
                "project": context.project,
                "candidate_paths": [
                    str(path) for path in _candidate_beads_dirs(context)
                ],
            },
        )

    messages = rust_beads.doctor(beads_dir)
    sync_clean = _bead_sync_clean(beads_dir)
    if sync_clean is False:
        ok_message = "OK: no issues found"
        if messages == [ok_message]:
            messages = []
        messages.append("WARNING: bead state has uncommitted changes")

    stats = rust_beads.stats(beads_dir)
    status = _messages_status(messages)
    problem_messages = tuple(
        message for message in messages if not message.strip().upper().startswith("OK:")
    )
    summary = _messages_summary(status, messages, stats)

    return DiagnosticCheck(
        id="project.beads",
        group="project",
        status=status,
        title="Project beads",
        summary=summary,
        details=problem_messages[:_MAX_DETAIL_ROWS],
        next_steps=("Run `sase bead doctor`.",) if problem_messages else (),
        data={
            "beads_dir": str(beads_dir),
            "messages": messages,
            "stats": stats,
            "sync_clean": sync_clean,
        },
    )


def _bead_sync_clean(beads_dir: Path) -> bool | None:
    """Return bead sync cleanliness, or ``None`` when git is unusable.

    ``bead_state_is_clean`` shells out to git; a missing or non-executable
    git must degrade this check, not crash the whole doctor report.
    """
    try:
        return bead_state_is_clean(beads_dir)
    except OSError:
        return None


def _find_existing_beads_dir(context: DoctorContext) -> Path | None:
    for path in _candidate_beads_dirs(context):
        if path.is_dir():
            return path
    return None


def _candidate_beads_dirs(context: DoctorContext) -> tuple[Path, ...]:
    candidates: list[Path] = []
    cwd = context.cwd.expanduser().resolve(strict=False)
    _append_resolved_beads_candidate(candidates, cwd)
    for parent in (cwd, *cwd.parents):
        candidates.append(parent / BEADS_DIRNAME)
        candidates.append(parent / ".sase" / "sdd" / BEADS_DIRNAME_NON_VC)

    try:
        resolution = resolve_current_project_record(context)
    except Exception:
        resolution = None
    record = getattr(resolution, "record", None)
    workspace_dir = getattr(record, "workspace_dir", None)
    if isinstance(workspace_dir, str) and workspace_dir:
        primary = Path(workspace_dir).expanduser()
        _append_resolved_beads_candidate(candidates, primary)
        candidates.append(primary / BEADS_DIRNAME)
        candidates.append(primary / ".sase" / "sdd" / BEADS_DIRNAME_NON_VC)

    return _dedupe_paths(candidates)


def _append_resolved_beads_candidate(candidates: list[Path], workspace: Path) -> None:
    try:
        from sase.sdd.store import resolve_sdd_kind_dir

        candidates.append(resolve_sdd_kind_dir(workspace, 1, "beads"))
    except Exception:  # noqa: BLE001 - doctor candidate resolution is best-effort.
        return


def _dedupe_paths(paths: list[Path]) -> tuple[Path, ...]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return tuple(result)


def _messages_status(messages: list[str]) -> CheckStatus:
    normalized = [message.strip().upper() for message in messages]
    if any(message.startswith("ERROR:") for message in normalized):
        return "ERROR"
    if any(
        message.startswith("WARNING:") or message.startswith("WARN:")
        for message in normalized
    ):
        return "WARN"
    return "OK"


def _messages_summary(
    status: CheckStatus,
    messages: list[str],
    stats: dict[str, int],
) -> str:
    issue_count = sum(
        int(stats.get(key, 0)) for key in ("open", "claimed", "in_progress", "closed")
    )
    if status == "OK":
        return f"bead store healthy; {issue_count} issue(s)"
    problems = [
        message for message in messages if not message.strip().upper().startswith("OK:")
    ]
    label = "error" if status == "ERROR" else "warning"
    return f"bead doctor reported {len(problems)} {label}(s)"


__all__ = [
    "bead_check_specs",
]
