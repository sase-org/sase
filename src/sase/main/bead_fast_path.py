"""Early dispatch for common ``sase bead`` commands."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, overload

from sase.bead.mutation_commit import (
    close_mutation_commit_message,
    mutation_commit_message,
)

if TYPE_CHECKING:
    from sase.bead.operation_context import BeadOperationContext

_BEADS_DIRNAME = "sdd/beads"
_BEADS_DIRNAME_NON_VC = "beads"
_MUTATING_VERBS = frozenset(
    {"+1", "close", "create", "open", "ref", "rm", "snooze", "update"}
)
# Every verb that accepts an ``@<path>`` free-text value, including those
# Rust does not currently handle. A future Rust arm must not store the raw
# token.
_AT_PATH_VALUE_VERBS = frozenset({"+1", "close", "note", "snooze", "update"})
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
    # needed for truthful close/already-closed/noted/cascade rendering, and the
    # Rust create fast path cannot resolve the acting SASE agent that
    # ``handle_bead_create`` records as the bead's creator. ``epic-symbols``
    # is a Python working-tree scan, not a bead-store query.
    if argv[0] in {"close", "create", "epic-symbols", "task-type"}:
        return None
    if argv[0] == "update" and _update_uses_python_note_surface(argv):
        return None
    # ``@<path>`` free-text expansion lives in the Python handlers. A Rust
    # fast path for any of these verbs would store the raw token, so they
    # fall through whenever argv might name a file (or the ``@@`` escape).
    if argv[0] in _AT_PATH_VALUE_VERBS and _argv_requests_at_path(argv):
        return None
    if argv[0] in {"list", "read", "show"} or _search_uses_full_format(argv):
        return None

    return execute_bead_cli(argv)


def execute_bead_cli(argv: list[str], *, materialize: bool = False) -> int | None:
    """Run one bead command through the Rust bead CLI core.

    Returns an exit code when the Rust core handled the command, or ``None``
    when the caller must fall back to its own implementation. Slow-path callers
    that have no fallback of their own pass ``materialize=True`` so a bead store
    that has not been materialized yet is prepared instead of deferred.
    """
    try:
        if materialize:
            try:
                context = _resolve_fast_path_context(
                    argv,
                    materialize=True,
                    terminal_errors=True,
                )
            except TypeError:
                context = _resolve_fast_path_context(argv)
                if context is None:
                    context = _resolve_materialized_context()
        else:
            try:
                context = _resolve_fast_path_context(argv, terminal_errors=True)
            except TypeError:
                context = _resolve_fast_path_context(argv)
    except TypeError:
        raise
    except Exception as exc:
        from sase.bead.operation_context import BeadOperationRoutingError

        if not isinstance(exc, BeadOperationRoutingError):
            raise
        print(f"Error: {exc}", file=sys.stderr)
        return 1
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
                str(context.invocation_cwd or Path.cwd().resolve()),
                context.relativize_design_paths,
            )
        )
    except (AttributeError, ImportError, ValueError):
        return None

    if not bool(outcome.get("handled")):
        return None

    published = True
    mutation_summary = outcome.get("mutation_summary")
    if isinstance(mutation_summary, dict):
        if context.bead_context is None:
            published = _apply_mutation_side_effects(
                context.write_beads_dir,
                mutation_summary,
            )
        else:
            published = _apply_mutation_side_effects(
                context.write_beads_dir,
                mutation_summary,
                bead_context=context.bead_context,
            )

    stdout = str(outcome.get("stdout") or "")
    stderr = str(outcome.get("stderr") or "")
    # A mutation that never reached the canonical remote must not print its
    # success output; the publication diagnostic is the whole answer.
    if stdout and published:
        sys.stdout.write(stdout)
    if stderr:
        sys.stderr.write(stderr)

    try:
        from sase.bead.sync import schedule_bead_refresh

        schedule_bead_refresh(context.write_beads_dir)
    except Exception:
        pass

    exit_code = int(outcome.get("exit_code") or 0)
    if not published:
        return exit_code or 1
    return exit_code


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
        invocation_cwd: Path | None = None,
        bead_context: BeadOperationContext | None = None,
    ) -> None:
        self.read_beads_dirs = read_beads_dirs
        self.write_beads_dir = write_beads_dir
        self.relativize_design_paths = relativize_design_paths
        self.read_only = read_only
        self.invocation_cwd = invocation_cwd
        self.bead_context = bead_context


def _resolve_fast_path_context(
    argv: list[str],
    *,
    materialize: bool = False,
    terminal_errors: bool = False,
) -> _FastPathContext | None:
    from sase.bead.operation_context import BeadOperationRoutingError
    from sase.bead.operation_context import (
        local_operation_context,
        resolve_operation_context_for_targets,
    )

    cwd = Path.cwd().resolve()
    targets = _fast_path_target_operands(argv)
    if targets is None:
        return None
    bead_context: BeadOperationContext | None
    if targets:
        try:
            bead_context = resolve_operation_context_for_targets(
                targets,
                cwd=cwd,
                require_single_store=True,
                for_write=_is_mutating_verb(argv),
                materialize=materialize,
            )
        except BeadOperationRoutingError:
            if terminal_errors:
                raise
            return None
    else:
        bead_context = local_operation_context(
            cwd=cwd,
            materialize=materialize,
            require_existing=not materialize,
        )
    if bead_context is None:
        return None

    return _FastPathContext(
        read_beads_dirs=bead_context.read_beads_dirs,
        write_beads_dir=bead_context.write_beads_dir,
        relativize_design_paths=bead_context.relativize_design_paths,
        read_only=bead_context.read_only,
        invocation_cwd=bead_context.invocation_cwd,
        bead_context=bead_context,
    )


def _resolve_materialized_context() -> _FastPathContext | None:
    """Resolve a write context, materializing the bead store if needed."""
    from sase.bead.operation_context import local_operation_context

    bead_context = local_operation_context(
        cwd=Path.cwd().resolve(),
        materialize=True,
        require_existing=False,
    )
    if bead_context is None:
        return None
    return _FastPathContext(
        read_beads_dirs=bead_context.read_beads_dirs,
        write_beads_dir=bead_context.write_beads_dir,
        relativize_design_paths=bead_context.relativize_design_paths,
        read_only=bead_context.read_only,
        invocation_cwd=bead_context.invocation_cwd,
        bead_context=bead_context,
    )


def _fast_path_target_operands(argv: list[str]) -> tuple[str, ...] | None:
    """Return command-aware bead targets, or ``None`` for unsupported syntax."""

    if not argv:
        return None
    verb = argv[0]
    args = argv[1:]
    if verb in {"search", "ready", "blocked", "stats"}:
        return ()
    if verb == "open":
        return (args[0],) if len(args) == 1 and not args[0].startswith("-") else None
    if verb == "rm":
        return (
            tuple(args)
            if args and not any(arg.startswith("-") for arg in args)
            else None
        )
    if verb == "update":
        return _update_target_operands(args)
    if verb == "dep":
        return _dep_target_operands(args)
    if verb == "ref":
        return _ref_target_operands(args)
    if verb == "close":
        return _close_target_operands(args)
    return ()


def _update_target_operands(args: list[str]) -> tuple[str, ...] | None:
    targets: list[str] = []
    value_options = {
        "-s",
        "--status",
        "-t",
        "--title",
        "-d",
        "--description",
        "-n",
        "--notes",
        "-D",
        "--design",
        "-m",
        "--model",
        "-a",
        "--assignee",
        "-x",
        "--external-ref",
        "-E",
        "--epic-count",
        "--tier",
    }
    prefix_options = {
        "--status=",
        "--title=",
        "--description=",
        "--notes=",
        "--design=",
        "--model=",
        "--assignee=",
        "--external-ref=",
        "--tier=",
    }
    index = 0
    while index < len(args):
        arg = args[index]
        if not arg.startswith("-"):
            targets.append(arg)
            index += 1
            continue
        if arg in {"-X", "--clear-external-ref"}:
            index += 1
            continue
        if arg in value_options:
            index += 2
            if index > len(args):
                return None
            continue
        if any(arg.startswith(prefix) for prefix in prefix_options):
            index += 1
            continue
        return None
    return tuple(targets) if targets else None


def _dep_target_operands(args: list[str]) -> tuple[str, ...] | None:
    if any(arg.startswith("-") for arg in args):
        return None
    match args:
        case ["add", source, dependency]:
            return (source, dependency)
        case ["rm", source, *dependencies] if dependencies:
            return (source, *dependencies)
        case ["list"] | ["tree"]:
            return ()
        case _:
            return None


def _ref_target_operands(args: list[str]) -> tuple[str, ...] | None:
    action = args[0] if args and args[0] in {"add", "list", "rm"} else "list"
    action_args = args[1:] if args and action == args[0] else args
    if action in {"add", "rm"}:
        if len(action_args) < 2 or action_args[0].startswith("-"):
            return None
        return (action_args[0],)
    if action != "list":
        return None
    target: str | None = None
    for arg in action_args:
        if arg in {"-j", "--json"}:
            continue
        if arg in {"-r", "--resolve"}:
            return None
        if arg.startswith("-"):
            return None
        if target is not None:
            return None
        target = arg
    return () if target is None else (target,)


def _close_target_operands(args: list[str]) -> tuple[str, ...] | None:
    targets: list[str] = []
    value_options = {"-n", "--note", "-r", "--reason", "-R", "--resolution"}
    prefix_options = {"--note=", "--reason=", "--resolution="}
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in {"-f", "--force"}:
            index += 1
            continue
        if arg in value_options:
            index += 2
            if index > len(args):
                return None
            continue
        if any(arg.startswith(prefix) for prefix in prefix_options):
            index += 1
            continue
        if arg.startswith("-"):
            return None
        targets.append(arg)
        index += 1
    return tuple(targets) if targets else None


def _argv_requests_at_path(argv: list[str]) -> bool:
    """Return whether *argv* may carry an ``@<path>`` or ``@@`` free-text value."""

    for arg in argv[1:]:
        if arg.startswith("@") and arg != "@":
            return True
        separator = arg.find("=")
        if separator > 0 and arg[separator + 1 :].startswith("@"):
            return True
    return False


def _update_uses_python_note_surface(argv: list[str]) -> bool:
    """Defer update note flags to argparse for the append-only/tombstone surface."""
    for arg in argv[1:]:
        if arg in {"-n", "--note", "--notes"}:
            return True
        if arg.startswith("--note=") or arg.startswith("--notes="):
            return True
        if arg.startswith("-n") and arg != "-n":
            return True
    return False


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
    write_beads_dir: Path,
    mutation_summary: dict[str, Any],
    *,
    bead_context: BeadOperationContext | None = None,
) -> bool:
    """Commit and publish a Rust fast-path mutation.

    Returns whether the mutation is published, using the same verification as
    the Python mutation lane so a mutation is never verified on one path and
    unverified on the other.
    """
    operation = str(mutation_summary.get("operation") or "")
    issue_ids = [str(value) for value in mutation_summary.get("issue_ids") or []]
    if mutation_summary.get("changed") is False:
        return True
    committed_message: str | None = None
    commit_description: str | None = None
    publication_required = False
    try:
        from sase.bead.cli_common import (
            auto_commit_bead_store,
            emit_routed_bead_publication_failure,
            routed_bead_context_requires_publication,
        )

        publication_required = routed_bead_context_requires_publication(bead_context)

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
        commit_description = message
        commit_kwargs: dict[str, Any] = {}
        if bead_context is not None:
            commit_kwargs["bead_context"] = bead_context
        if message and auto_commit_bead_store(message, **commit_kwargs):
            committed_message = message
        elif message and publication_required:
            emit_routed_bead_publication_failure(message, bead_context=bead_context)
            return False
    except Exception as exc:
        if publication_required:
            emit_routed_bead_publication_failure(
                commit_description,
                bead_context=bead_context,
                cause=exc,
            )
            return False
        return True

    if committed_message is None:
        return True

    from sase.bead.cli_common import (
        BeadPublicationError,
        ensure_bead_mutation_published,
    )

    try:
        ensure_bead_mutation_published(write_beads_dir, description=committed_message)
    except BeadPublicationError:
        return False
    return True


_mutation_commit_message = mutation_commit_message
