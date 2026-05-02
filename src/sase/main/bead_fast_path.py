"""Early dispatch for common ``sase bead`` commands."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


_BEADS_DIRNAME = "sdd/beads"
_BEADS_DIRNAME_NON_VC = "beads"
_LEGACY_BEADS_DIRNAME = ".sase_beads"
_FAST_WRITE_COMMANDS = {"open", "update", "close", "dep"}


def try_handle_bead_fast_path(argv: list[str]) -> int | None:
    """Handle a fast-pathed bead command.

    Returns an exit code when handled, or ``None`` when argparse should handle
    the command through the compatibility slow path.
    """
    if not argv or any(arg in {"-h", "--help"} for arg in argv):
        return None

    context = _resolve_fast_path_context(argv)
    if context is None:
        return None

    try:
        from sase.core.rust import require_rust_binding

        binding = require_rust_binding("bead_cli_execute")
        outcome: dict[str, Any] = dict(
            binding(
                argv,
                [str(path) for path in context.read_beads_dirs],
                str(context.write_beads_dir),
                str(Path.cwd()),
                context.relativize_design_paths,
            )
        )
    except (AttributeError, ImportError, ValueError):
        return None

    if not bool(outcome.get("handled")):
        return None

    stdout = str(outcome.get("stdout") or "")
    stderr = str(outcome.get("stderr") or "")
    if stdout:
        sys.stdout.write(stdout)
    if stderr:
        sys.stderr.write(stderr)

    mutation_summary = outcome.get("mutation_summary")
    if isinstance(mutation_summary, dict):
        _apply_mutation_side_effects(context.write_beads_dir, mutation_summary)

    return int(outcome.get("exit_code") or 0)


class _FastPathContext:
    def __init__(
        self,
        *,
        read_beads_dirs: list[Path],
        write_beads_dir: Path,
        relativize_design_paths: bool,
    ) -> None:
        self.read_beads_dirs = read_beads_dirs
        self.write_beads_dir = write_beads_dir
        self.relativize_design_paths = relativize_design_paths


def _resolve_fast_path_context(argv: list[str]) -> _FastPathContext | None:
    subcommand = argv[0]
    resolved = _resolve_lightweight_beads_context(Path.cwd().resolve())
    if resolved is None:
        return None
    read_beads_dirs, write_beads_dir, beads_dirname = resolved
    if subcommand in _FAST_WRITE_COMMANDS and beads_dirname == _BEADS_DIRNAME_NON_VC:
        return None

    return _FastPathContext(
        read_beads_dirs=read_beads_dirs,
        write_beads_dir=write_beads_dir,
        relativize_design_paths=beads_dirname == _BEADS_DIRNAME,
    )


def _resolve_lightweight_beads_context(
    cwd: Path,
) -> tuple[list[Path], Path, str] | None:
    primary = _resolve_primary_workspace_by_project_scan(cwd)
    if primary is not None:
        non_vc = primary / ".sase" / "sdd" / _BEADS_DIRNAME_NON_VC
        if non_vc.is_dir():
            return [non_vc], non_vc, _BEADS_DIRNAME_NON_VC

        read_dirs = _enumerate_workspace_beads_dirs(primary)
        write_dir, beads_dirname = _select_write_beads_dir(cwd, primary)
        if write_dir is not None:
            return read_dirs or [write_dir], write_dir, beads_dirname

    for parent in [cwd, *cwd.parents]:
        vc = parent / _BEADS_DIRNAME
        if vc.is_dir():
            return [vc], vc, _BEADS_DIRNAME
        non_vc = parent / ".sase" / "sdd" / _BEADS_DIRNAME_NON_VC
        if non_vc.is_dir():
            return [non_vc], non_vc, _BEADS_DIRNAME_NON_VC
        legacy = parent / _LEGACY_BEADS_DIRNAME
        if legacy.is_dir():
            return [legacy], legacy, _LEGACY_BEADS_DIRNAME

    return None


def _resolve_primary_workspace_by_project_scan(cwd: Path) -> Path | None:
    projects_dir = Path.home() / ".sase" / "projects"
    if not projects_dir.is_dir():
        return None

    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        project_name = project_dir.name
        primary = _parse_workspace_dir(project_dir / f"{project_name}.gp")
        if primary is None:
            continue
        if _cwd_matches_project_workspace(cwd, primary, project_name):
            return primary
    return None


def _parse_workspace_dir(project_file: Path) -> Path | None:
    try:
        for line in project_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("WORKSPACE_DIR:"):
                value = line.split(":", 1)[1].strip().rstrip("/")
                if value:
                    path = Path(value)
                    if path.is_dir():
                        return path.resolve()
    except OSError:
        return None
    return None


def _cwd_matches_project_workspace(cwd: Path, primary: Path, project_name: str) -> bool:
    primary_parts = primary.parts
    cwd_parts = cwd.parts
    if len(cwd_parts) < len(primary_parts):
        return False

    for idx, primary_component in enumerate(primary_parts):
        cwd_component = cwd_parts[idx]
        if primary_component == cwd_component:
            continue
        if _is_workspace_variant(
            primary_component, project_name
        ) and _is_workspace_variant(cwd_component, project_name):
            return cwd_parts[idx + 1 : len(primary_parts)] == primary_parts[idx + 1 :]
        return False
    return True


def _is_workspace_variant(component: str, project_name: str) -> bool:
    return component == project_name or component.startswith(f"{project_name}_")


def _enumerate_workspace_beads_dirs(primary: Path) -> list[Path]:
    workspaces = _enumerate_project_workspace_dirs(primary)
    current_dirs = [workspace / _BEADS_DIRNAME for workspace in workspaces]
    legacy_dirs = [workspace / _LEGACY_BEADS_DIRNAME for workspace in workspaces]
    return _dedupe_existing_dirs([*current_dirs, *legacy_dirs])


def _enumerate_project_workspace_dirs(primary: Path) -> list[Path]:
    workspaces = [primary]
    parent = primary.parent
    prefix = f"{primary.name}_"
    if parent.is_dir():
        for entry in sorted(parent.iterdir()):
            if not entry.is_dir() or not entry.name.startswith(prefix):
                continue
            suffix = entry.name.removeprefix(prefix)
            if not suffix.isdigit():
                continue
            workspaces.append(entry)
    return workspaces


def _dedupe_existing_dirs(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        if not path.is_dir():
            continue
        key = path.resolve()
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _select_write_beads_dir(cwd: Path, primary: Path) -> tuple[Path | None, str]:
    local_current = cwd / _BEADS_DIRNAME
    if local_current.is_dir():
        return local_current, _BEADS_DIRNAME

    primary_current = primary / _BEADS_DIRNAME
    if primary_current.is_dir():
        return primary_current, _BEADS_DIRNAME

    local_legacy = cwd / _LEGACY_BEADS_DIRNAME
    if local_legacy.is_dir():
        return local_legacy, _LEGACY_BEADS_DIRNAME

    primary_legacy = primary / _LEGACY_BEADS_DIRNAME
    if primary_legacy.is_dir():
        return primary_legacy, _LEGACY_BEADS_DIRNAME

    return None, _BEADS_DIRNAME


def _apply_mutation_side_effects(
    write_beads_dir: Path, mutation_summary: dict[str, Any]
) -> None:
    try:
        from sase.bead.sync import rebuild_from_jsonl

        rebuild_from_jsonl(write_beads_dir)
    except Exception:
        pass

    try:
        from sase.telemetry.metrics import BEAD_OPERATIONS, BEAD_STATUS_TRANSITIONS

        operation = str(mutation_summary.get("operation") or "")
        if operation:
            BEAD_OPERATIONS.labels(operation=operation).inc()
        for transition in mutation_summary.get("status_transitions") or []:
            if not isinstance(transition, dict):
                continue
            from_status = str(transition.get("from_status") or "")
            to_status = str(transition.get("to_status") or "")
            if from_status and to_status:
                BEAD_STATUS_TRANSITIONS.labels(
                    from_status=from_status,
                    to_status=to_status,
                ).inc()
    except Exception:
        pass
