"""Early dispatch for common ``sase bead`` commands."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


_BEADS_DIRNAME = "sdd/beads"
_BEADS_DIRNAME_NON_VC = "beads"
_FAST_WRITE_COMMANDS = {"create", "open", "update", "close", "dep"}


def try_handle_bead_fast_path(argv: list[str]) -> int | None:
    """Handle a fast-pathed bead command.

    Returns an exit code when handled, or ``None`` when argparse should handle
    the command through the compatibility slow path.
    """
    if not argv or any(arg in {"-h", "--help"} for arg in argv):
        return None
    if argv[0] in {"list", "show"} or _search_uses_full_format(argv):
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


def _search_uses_full_format(argv: list[str]) -> bool:
    if not argv or argv[0] != "search":
        return False

    for index, arg in enumerate(argv[1:], start=1):
        if arg in {"--format", "-f"}:
            return index + 1 < len(argv) and argv[index + 1] == "full"
        if arg == "--format=full" or arg == "-ffull":
            return True
    return False


def _resolve_lightweight_beads_context(
    cwd: Path,
) -> tuple[list[Path], Path, str] | None:
    from sase.bead.cli_common import resolve_beads_location

    location = resolve_beads_location(cwd, require_existing=True)
    if location is not None:
        return [location.beads_dir], location.beads_dir, location.beads_dirname
    return None


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
