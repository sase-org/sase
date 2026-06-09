"""Memory episode checks for ``sase doctor``."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.core.paths import sase_projects_dir
from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck
from sase.doctor.checks_project import resolve_current_project_record
from sase.memory.episodes._auto_build_state import read_build_state_details_unlocked
from sase.memory.episodes.index import episode_index_path, project_episodes_dir
from sase.memory.episodes.index import read_episode_index_unlocked

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_MAX_DETAIL_ROWS = 10


def memory_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return deep memory check specs."""
    return (
        CheckSpec(
            id="memory.episodes",
            group="memory",
            title="Memory episodes",
            runner=lambda: _check_memory_episodes(context),
            deep=True,
        ),
    )


def _check_memory_episodes(context: DoctorContext) -> DiagnosticCheck:
    """Inspect automatic episode-builder state without creating lock files."""
    project = _resolve_project_name(context)
    if project is None:
        return DiagnosticCheck(
            id="memory.episodes",
            group="memory",
            status="SKIP",
            title="Memory episodes",
            summary="no current project episode state to inspect",
            next_steps=("Pass `sase doctor -D -p <project>` to inspect a project.",),
            data={"project": None},
        )

    root = sase_projects_dir()
    episodes_dir = project_episodes_dir(project, projects_root=root)
    index_path = episode_index_path(project, projects_root=root)
    if not _episode_state_exists(episodes_dir, index_path):
        return DiagnosticCheck(
            id="memory.episodes",
            group="memory",
            status="SKIP",
            title="Memory episodes",
            summary=f"no episode auto-build state found for project {project!r}",
            data={
                "project": project,
                "episodes_dir": str(episodes_dir),
                "index_path": str(index_path),
            },
        )

    checks, repairs = _read_episode_checks(project, episodes_dir, index_path)
    status = _aggregate_status(checks)
    problem_checks = [
        check
        for check in checks
        if str(check.get("status", "")).upper() not in {"OK", "SKIP"}
    ]
    summary = (
        f"episode auto-build state is healthy; {len(checks)} check(s)"
        if status == "OK"
        else f"episode auto-build doctor reported {len(problem_checks)} problem(s)"
    )
    details = tuple(
        f"{check['status']}: {check['id']}: {check['summary']}"
        for check in problem_checks[:_MAX_DETAIL_ROWS]
    )

    next_steps: list[str] = []
    if problem_checks:
        next_steps.append(f"Run `sase memory episodes doctor -p {project} -j`.")
    if repairs:
        next_steps.append(
            f"Review `sase memory episodes doctor -p {project} -R -j` before applying repairs."
        )

    return DiagnosticCheck(
        id="memory.episodes",
        group="memory",
        status=status,
        title="Memory episodes",
        summary=summary,
        details=details,
        next_steps=tuple(next_steps),
        data={
            "project": project,
            "episodes_dir": str(episodes_dir.resolve(strict=False)),
            "index_path": str(index_path),
            "checks": checks,
            "repairs": repairs,
            "repaired": False,
        },
    )


def _resolve_project_name(context: DoctorContext) -> str | None:
    if context.project:
        return context.project
    try:
        resolution = resolve_current_project_record(context)
    except Exception:
        return None
    project_name = getattr(resolution, "project_name", None)
    return project_name if isinstance(project_name, str) and project_name else None


def _episode_state_exists(episodes_dir: Path, index_path: Path) -> bool:
    if index_path.exists():
        return True
    if not episodes_dir.exists():
        return False
    state_names = {
        "build_state.json",
        "build_state.json.prev",
        "index.jsonl",
        "index.lock",
    }
    if any((episodes_dir / name).exists() for name in state_names):
        return True
    return any(
        path.is_dir() and path.name.startswith(".") and ".tmp." in path.name
        for path in _safe_iterdir(episodes_dir)
    )


def _read_episode_checks(
    project: str,
    episodes_dir: Path,
    index_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []

    state_status, state, state_error = read_build_state_details_unlocked(
        episodes_dir, project
    )
    prev_status, prev_state, prev_error = read_build_state_details_unlocked(
        episodes_dir, project, previous=True
    )
    checks.append(
        _build_state_check(
            state_status,
            state,
            state_error,
            prev_status=prev_status,
            prev_error=prev_error,
        )
    )
    checks.append(
        {
            "id": "memory.episodes.build_state_prev",
            "status": "OK" if prev_status in {"ok", "missing"} else "WARN",
            "summary": _prev_state_summary(prev_status, prev_error),
            "details": [],
        }
    )
    index_rows = read_episode_index_unlocked(index_path)
    checks.append(
        {
            "id": "memory.episodes.index",
            "status": "OK",
            "summary": f"Episode index has {len(index_rows)} row(s).",
            "details": [],
        }
    )

    temp_dirs = _storage_temp_dirs(episodes_dir)
    if temp_dirs:
        repairs.append(
            {
                "id": "remove_temp_dirs",
                "summary": f"Remove {len(temp_dirs)} abandoned episode temp dir(s).",
                "executed": False,
            }
        )
        checks.append(
            {
                "id": "memory.episodes.temp_dirs",
                "status": "WARN",
                "summary": f"Found {len(temp_dirs)} abandoned episode temp dir(s).",
                "details": [str(path) for path in temp_dirs],
            }
        )
    else:
        checks.append(
            {
                "id": "memory.episodes.temp_dirs",
                "status": "OK",
                "summary": "No abandoned temp dirs found.",
                "details": [],
            }
        )

    if state_status == "corrupt" and prev_status == "ok" and prev_state is not None:
        repairs.append(
            {
                "id": "restore_build_state_prev",
                "summary": "Restore build_state.json from build_state.json.prev.",
                "executed": False,
            }
        )

    return checks, repairs


def _build_state_check(
    status: str,
    state: object,
    error: str | None,
    *,
    prev_status: str,
    prev_error: str | None,
) -> dict[str, Any]:
    if status == "ok" and state is not None:
        checkpoint = getattr(state, "checkpoint_timestamp", None) or "-"
        failures = getattr(state, "consecutive_failures", 0)
        return {
            "id": "memory.episodes.build_state",
            "status": "OK",
            "summary": "build_state.json is valid.",
            "details": [
                f"checkpoint={checkpoint}",
                f"consecutive_failures={failures}",
            ],
        }
    if status == "missing":
        return {
            "id": "memory.episodes.build_state",
            "status": "OK",
            "summary": "build_state.json is not present yet.",
            "details": [],
        }
    if prev_status == "ok":
        return {
            "id": "memory.episodes.build_state",
            "status": "WARN",
            "summary": "build_state.json is corrupt but build_state.json.prev is valid.",
            "details": [error or "invalid state"],
        }
    detail = error or prev_error or "invalid state"
    return {
        "id": "memory.episodes.build_state",
        "status": "ERROR",
        "summary": "build_state.json is corrupt and no valid previous state is available.",
        "details": [detail],
    }


def _prev_state_summary(status: str, error: str | None) -> str:
    if status == "ok":
        return "build_state.json.prev is valid."
    if status == "missing":
        return "build_state.json.prev is not present."
    return f"build_state.json.prev is corrupt: {error or 'invalid state'}"


def _storage_temp_dirs(episodes_dir: Path) -> list[Path]:
    return [
        path
        for path in sorted(_safe_iterdir(episodes_dir), key=lambda item: item.name)
        if path.is_dir() and path.name.startswith(".") and ".tmp." in path.name
    ]


def _safe_iterdir(path: Path) -> tuple[Path, ...]:
    try:
        return tuple(path.iterdir())
    except OSError:
        return ()


def _aggregate_status(checks: list[dict[str, Any]]) -> CheckStatus:
    statuses = {str(check.get("status", "")).upper() for check in checks}
    if "ERROR" in statuses:
        return "ERROR"
    if "WARN" in statuses or "WARNING" in statuses:
        return "WARN"
    return "OK"


__all__ = [
    "memory_check_specs",
]
