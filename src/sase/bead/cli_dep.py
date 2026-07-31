"""Dependency command handlers."""

from __future__ import annotations

import argparse
import sys

from sase.bead.cli_common import (
    auto_commit_bead_store,
    bead_store_mutation,
    get_read_view,
)
from sase.bead.cli_dep_list import print_bead_dep_list
from sase.bead.cli_dep_render import ACTIVE_STATUSES
from sase.bead.cli_dep_tree import print_bead_dep_tree
from sase.bead.dep_graph import DepGraph
from sase.bead.model import Status
from sase.bead.mutation_commit import require_mutation_commit_message


def handle_bead_dep(args: argparse.Namespace) -> None:
    """Dispatch one ``sase bead dep`` action."""
    if args.dep_action == "add":
        with bead_store_mutation(auto_commit_bead_store) as mutation:
            try:
                dep = mutation.project.add_dependency(args.issue, args.depends_on)
            except KeyError as exc:
                message = str(exc.args[0]) if exc.args else ""
                missing_id = message.rsplit("Issue not found:", 1)[-1].strip()
                print(f"Error: issue not found: {missing_id}", file=sys.stderr)
                sys.exit(1)
            except ValueError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                sys.exit(1)
            mutation.commit(
                require_mutation_commit_message(
                    "dep_add", [dep.issue_id, dep.depends_on_id]
                )
            )
        print(f"✓ Added dependency: {dep.issue_id} depends on {dep.depends_on_id}")
    elif args.dep_action == "rm":
        with bead_store_mutation(auto_commit_bead_store) as mutation:
            try:
                removed = mutation.project.remove_dependencies(
                    args.issue, args.depends_on
                )
            except KeyError as exc:
                message = str(exc.args[0]) if exc.args else ""
                missing_id = message.rsplit("Issue not found:", 1)[-1].strip()
                print(f"Error: issue not found: {missing_id}", file=sys.stderr)
                sys.exit(1)
            except ValueError as exc:
                message = str(exc).removeprefix("validation: ")
                print(f"Error: {message}", file=sys.stderr)
                sys.exit(1)
            mutation.commit(
                require_mutation_commit_message(
                    "dep_rm",
                    [
                        *(dep.issue_id for dep in removed[:1]),
                        *(dep.depends_on_id for dep in removed),
                    ],
                )
            )
            issues = mutation.project.list_issues()
            status_by_id = {issue.id: issue.status for issue in issues}
            source = next(issue for issue in issues if issue.id == args.issue)
            active_blockers = [
                dependency.depends_on_id
                for dependency in source.dependencies
                if status_by_id.get(dependency.depends_on_id) in ACTIVE_STATUSES
            ]
            ready_ids = {issue.id for issue in mutation.project.ready()}
        for dependency in removed:
            print(
                "✗ Removed dependency: "
                f"{dependency.issue_id} no longer depends on "
                f"{dependency.depends_on_id}"
            )
        if args.issue in ready_ids:
            print(f"○ {args.issue} is now ready (no active blockers).")
        elif active_blockers:
            blocker_word = "blocker" if len(active_blockers) == 1 else "blockers"
            print(
                f"○ {args.issue} still has {len(active_blockers)} active "
                f"{blocker_word}: {', '.join(active_blockers)}."
            )
        else:
            print(f"○ {args.issue} has no active blockers.")
    elif args.dep_action == "list":
        handle_bead_dep_list(args)
    elif args.dep_action == "tree":
        handle_bead_dep_tree(args)
    else:
        print(f"Unknown dep action: {args.dep_action}", file=sys.stderr)
        sys.exit(1)


def handle_bead_dep_list(args: argparse.Namespace) -> None:
    """List dependency edges with their provenance and blocking state."""
    with get_read_view() as view:
        graph = DepGraph.build(view.list_issues())
        scope = args.id
        if scope is not None:
            resolve_id = getattr(view, "resolve_id", None)
            if resolve_id is not None:
                try:
                    scope = resolve_id(scope)
                except KeyError:
                    print(f"Error: issue not found: {scope}", file=sys.stderr)
                    sys.exit(1)
                except ValueError as exc:
                    print(f"Error: {exc}", file=sys.stderr)
                    sys.exit(1)
            if graph.resolve(scope) is None:
                print(f"Error: issue not found: {scope}", file=sys.stderr)
                sys.exit(1)

        statuses = (
            frozenset(Status(value) for value in args.status) if args.status else None
        )
        print_bead_dep_list(
            graph,
            scope=scope,
            direction=args.direction,
            statuses=statuses,
            limit=args.limit,
            output_format=args.format,
            color=args.color,
        )


def handle_bead_dep_tree(args: argparse.Namespace) -> None:
    """Render the dependency graph as one or two terminating trees."""
    with get_read_view() as view:
        graph = DepGraph.build(view.list_issues())
        scope = args.id
        if scope is not None:
            resolve_id = getattr(view, "resolve_id", None)
            if resolve_id is not None:
                try:
                    scope = resolve_id(scope)
                except KeyError:
                    print(f"Error: issue not found: {scope}", file=sys.stderr)
                    sys.exit(1)
                except ValueError as exc:
                    print(f"Error: {exc}", file=sys.stderr)
                    sys.exit(1)
            if graph.resolve(scope) is None:
                print(f"Error: issue not found: {scope}", file=sys.stderr)
                sys.exit(1)

        statuses = (
            frozenset(Status(value) for value in args.status)
            if args.status
            else (None if scope is not None else ACTIVE_STATUSES)
        )
        print_bead_dep_tree(
            graph,
            scope=scope,
            direction=args.direction,
            statuses=statuses,
            levels=args.levels,
            output_format=args.format,
            color=args.color,
        )
