"""Early dispatch for common ``sase bead`` commands."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Literal, overload

from sase.bead.mutation_commit import (
    close_mutation_commit_message,
    mutation_commit_message,
)

_BEADS_DIRNAME = "sdd/beads"
_BEADS_DIRNAME_NON_VC = "beads"
_MUTATING_VERBS = frozenset({"close", "create", "open", "ref", "rm", "update"})
_READ_ONLY_DEP_ACTIONS = frozenset({"list", "tree"})
_READ_ONLY_REF_ACTIONS = frozenset({"list"})


def try_handle_bead_fast_path(argv: list[str]) -> int | None:
    """Handle a fast-pathed bead command.

    Returns an exit code when handled, or ``None`` when argparse should handle
    the command through the compatibility slow path.
    """
    if not argv or any(arg in {"-h", "--help"} for arg in argv):
        return None
    # The Rust close fast path does not yet expose the classification fields
    # needed for truthful close/already-closed/noted/cascade rendering.
    if argv[0] == "close":
        return None
    if argv[0] in {"list", "show"} or _search_uses_full_format(argv):
        return None

    return execute_bead_cli(argv)


def execute_bead_cli(argv: list[str], *, materialize: bool = False) -> int | None:
    """Run one bead command through the Rust bead CLI core.

    Returns an exit code when the Rust core handled the command, or ``None``
    when the caller must fall back to its own implementation. Slow-path callers
    that have no fallback of their own pass ``materialize=True`` so a bead store
    that has not been materialized yet is prepared instead of deferred.
    """
    context = _resolve_fast_path_context(argv)
    if context is None and materialize:
        context = _resolve_materialized_context()
    if context is None:
        return None

    if _is_mutating_verb(argv):
        from sase.core.state_write_guard import assert_bead_store_write_sandboxed

        assert_bead_store_write_sandboxed(
            context.write_beads_dir,
            operation=f"fast-path {argv[0]}",
            read_only=context.read_only,
        )

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

    mutation_summary = outcome.get("mutation_summary")
    if isinstance(mutation_summary, dict):
        _apply_mutation_side_effects(context.write_beads_dir, mutation_summary)

    stdout = str(outcome.get("stdout") or "")
    stderr = str(outcome.get("stderr") or "")
    if stdout:
        sys.stdout.write(stdout)
    if stderr:
        sys.stderr.write(stderr)

    try:
        from sase.bead.sync import schedule_current_bead_refresh

        schedule_current_bead_refresh()
    except Exception:
        pass

    return int(outcome.get("exit_code") or 0)


def _is_mutating_verb(argv: list[str]) -> bool:
    """Classify writes conservatively before invoking the Rust fast path."""
    if not argv:
        return False
    if argv[0] == "dep":
        return len(argv) < 2 or argv[1] not in _READ_ONLY_DEP_ACTIONS
    if argv[0] == "ref":
        return len(argv) < 2 or argv[1] not in _READ_ONLY_REF_ACTIONS
    return argv[0] in _MUTATING_VERBS


class _FastPathContext:
    def __init__(
        self,
        *,
        read_beads_dirs: list[Path],
        write_beads_dir: Path,
        relativize_design_paths: bool,
        read_only: bool = False,
    ) -> None:
        self.read_beads_dirs = read_beads_dirs
        self.write_beads_dir = write_beads_dir
        self.relativize_design_paths = relativize_design_paths
        self.read_only = read_only


def _resolve_fast_path_context(argv: list[str]) -> _FastPathContext | None:
    cwd = Path.cwd().resolve()
    resolved = _resolve_lightweight_beads_context(cwd, include_read_only=True)
    if resolved is None:
        return None
    read_beads_dirs, write_beads_dir, beads_dirname, read_only = resolved

    return _FastPathContext(
        read_beads_dirs=read_beads_dirs,
        write_beads_dir=write_beads_dir,
        relativize_design_paths=beads_dirname == _BEADS_DIRNAME,
        read_only=read_only,
    )


def _resolve_materialized_context() -> _FastPathContext | None:
    """Resolve a write context, materializing the bead store if needed."""
    from sase.bead.cli_common import resolve_beads_location

    location = resolve_beads_location(Path.cwd().resolve(), materialize=True)
    if location is None:
        return None
    return _FastPathContext(
        read_beads_dirs=[location.beads_dir],
        write_beads_dir=location.beads_dir,
        relativize_design_paths=location.beads_dirname == _BEADS_DIRNAME,
        read_only=location.read_only,
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


@overload
def _resolve_lightweight_beads_context(
    cwd: Path,
    *,
    include_read_only: Literal[False] = False,
) -> tuple[list[Path], Path, str] | None: ...


@overload
def _resolve_lightweight_beads_context(
    cwd: Path,
    *,
    include_read_only: Literal[True],
) -> tuple[list[Path], Path, str, bool] | None: ...


def _resolve_lightweight_beads_context(
    cwd: Path,
    *,
    include_read_only: bool = False,
) -> tuple[list[Path], Path, str] | tuple[list[Path], Path, str, bool] | None:
    from sase.bead.cli_common import resolve_beads_location
    from sase.bead.sync import bead_refresh_mode

    location = (
        resolve_beads_location(cwd, materialize=True)
        if bead_refresh_mode() == "blocking"
        else resolve_beads_location(cwd, require_existing=True)
    )
    if location is None:
        return None
    values = [location.beads_dir], location.beads_dir, location.beads_dirname
    if include_read_only:
        return (*values, location.read_only)
    return values


def _apply_mutation_side_effects(
    write_beads_dir: Path, mutation_summary: dict[str, Any]
) -> None:
    del write_beads_dir
    operation = str(mutation_summary.get("operation") or "")
    issue_ids = [str(value) for value in mutation_summary.get("issue_ids") or []]
    if mutation_summary.get("changed") is False:
        return
    try:
        from sase.bead.cli_common import auto_commit_bead_store

        if operation == "close":
            message = close_mutation_commit_message(
                closed_ids=[
                    str(value) for value in mutation_summary.get("closed_ids") or []
                ],
                cascade_closed_ids=[
                    str(value)
                    for value in mutation_summary.get("cascade_closed_ids") or []
                ],
                noted_ids=[
                    str(value) for value in mutation_summary.get("noted_ids") or []
                ],
            )
        else:
            message = mutation_commit_message(operation, issue_ids)
        if message:
            auto_commit_bead_store(message)
    except Exception:
        pass


_mutation_commit_message = mutation_commit_message
