"""Create/update/delete bead CLI command handlers."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from sase.agent.identity import discover_agent_identity
from sase.bead.cli_common import (
    auto_commit_bead_store,
    bead_store_mutation,
    find_beads_location,
    init_beads,
    storage_plan_path,
)
from sase.bead.model import BeadTier, Issue, IssueType
from sase.bead.mutation_commit import (
    close_mutation_commit_message,
    require_mutation_commit_message,
)
from sase.bead.phase_selector import (
    PhaseSelectorError,
    parse_phase_selectors,
    resolve_epic_phase_ids,
)
from sase.bead.project import BeadProject


def handle_bead_init(args: argparse.Namespace) -> None:
    root, beads_dirname = find_beads_location(materialize=True)
    beads_path = root / beads_dirname
    if beads_path.exists():
        print(f"Already initialized: {beads_path}")
        return
    init_beads(root, beads_dirname)
    print(f"Initialized {beads_dirname}/ in {root}")


def parse_type_arg(value: str) -> tuple[IssueType, str | None, str | None]:
    """Parse the ``--type`` argument into (issue_type, plan_path, parent_id).

    Accepted forms:
    - ``plan(<path>)``                -> PLAN, design=path, parent_id=None
    - ``plan(<path>,<parent_id>)``    -> PLAN, design=path, parent_id=parent_id
    - ``phase(<parent_id>)``          -> PHASE, design=None, parent_id=parent_id
    """
    m = re.match(r"^(plan|phase)\((.+)\)$", value)
    if not m:
        print(
            f"Error: invalid --type value: {value}\n"
            "Expected: plan(<plan_file>), plan(<plan_file>,<parent_id>), or phase(<parent_id>)",
            file=sys.stderr,
        )
        sys.exit(1)

    kind, inner = m.group(1), m.group(2)
    parts = [p.strip() for p in inner.split(",")]

    if kind == "plan":
        if len(parts) == 1:
            return IssueType.PLAN, parts[0], None
        if len(parts) == 2:
            return IssueType.PLAN, parts[0], parts[1]
        print(
            f"Error: plan() expects 1 or 2 arguments, got {len(parts)}",
            file=sys.stderr,
        )
        sys.exit(1)
    else:  # phase
        if len(parts) == 1:
            return IssueType.PHASE, None, parts[0]
        print(
            f"Error: phase() expects exactly 1 argument, got {len(parts)}",
            file=sys.stderr,
        )
        sys.exit(1)


def handle_bead_create(args: argparse.Namespace) -> None:
    issue_type, plan_path, parent_id = parse_type_arg(args.type)
    changespec_name = getattr(args, "changespec", None) or ""
    changespec_bug_id = getattr(args, "bug_id", None) or ""
    if issue_type != IssueType.PLAN and (changespec_name or changespec_bug_id):
        print(
            "Error: ChangeSpec metadata can only be attached to plan beads",
            file=sys.stderr,
        )
        sys.exit(1)
    if changespec_bug_id and not changespec_name:
        print("Error: --bug-id requires --changespec", file=sys.stderr)
        sys.exit(1)
    tier = BeadTier(args.tier) if getattr(args, "tier", None) else None
    if issue_type != IssueType.PLAN and tier is not None:
        print("Error: --tier can only be set on plan beads", file=sys.stderr)
        sys.exit(1)
    size = getattr(args, "size", None)
    if issue_type != IssueType.PHASE and size is not None:
        print("Error: --size can only be set on phase beads", file=sys.stderr)
        sys.exit(1)
    design = ""
    if plan_path:
        plan_file = Path(plan_path)
        if not plan_file.exists():
            print(f"Error: plan file not found: {plan_path}", file=sys.stderr)
            sys.exit(1)
        design = storage_plan_path(plan_file.resolve())

    with bead_store_mutation(auto_commit_bead_store) as mutation:
        proj = mutation.project
        if parent_id:
            try:
                proj.show(parent_id)
            except KeyError:
                print(f"Error: parent bead not found: {parent_id}", file=sys.stderr)
                sys.exit(1)

        try:
            issue = proj.create(
                title=args.title,
                issue_type=issue_type,
                parent_id=parent_id,
                description=args.description or "",
                assignee=args.assignee or "",
                design=design,
                refs=getattr(args, "ref", None) or (),
                tier=tier,
                changespec_name=changespec_name,
                changespec_bug_id=changespec_bug_id,
                model=getattr(args, "model", None) or "",
                size=size,
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        mutation.commit(require_mutation_commit_message("create", [issue.id]))
    print(f"Created {issue.issue_type.value}: {issue.id} — {issue.title}")


def handle_bead_update(args: argparse.Namespace) -> None:
    with bead_store_mutation(auto_commit_bead_store) as mutation:
        proj = mutation.project
        fields: dict[str, str | int | None] = {}
        if args.status:
            fields["status"] = args.status
        if args.title:
            fields["title"] = args.title
        if args.description is not None:
            fields["description"] = args.description
        if args.notes is not None:
            fields["notes"] = args.notes
        if args.design is not None:
            fields["design"] = args.design
        if args.assignee is not None:
            fields["assignee"] = args.assignee
        if getattr(args, "tier", None) is not None:
            fields["tier"] = args.tier
        if getattr(args, "model", None) is not None:
            fields["model"] = args.model
        if getattr(args, "size", None) is not None:
            fields["size"] = args.size
        if not fields:
            print("No fields to update.", file=sys.stderr)
            sys.exit(1)
        try:
            issue = proj.update(args.id, **fields)
        except KeyError:
            print(f"Error: issue not found: {args.id}", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        mutation.commit(require_mutation_commit_message("update", [issue.id]))
    print(f"✓ Updated issue: {issue.id} — {issue.title}")


def handle_bead_note(args: argparse.Namespace) -> None:
    text = args.text
    if isinstance(text, list):
        text = " ".join(text)
    with bead_store_mutation(auto_commit_bead_store) as mutation:
        try:
            author = args.author
            if author is None:
                identity = discover_agent_identity()
                author = (
                    identity.name if identity is not None else mutation.project.owner
                )
            issue = mutation.project.append_note(args.id, str(text), author=author)
        except KeyError:
            print(f"Error: issue not found: {args.id}", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        mutation.commit(require_mutation_commit_message("note", [issue.id]))
    print(f"Noted: {issue.id} — {issue.title}")


def handle_bead_open(args: argparse.Namespace) -> None:
    with bead_store_mutation(auto_commit_bead_store) as mutation:
        try:
            issue, reopened_ancestors = mutation.project.open(args.id)
        except KeyError:
            print(f"Error: issue not found: {args.id}", file=sys.stderr)
            sys.exit(1)
        mutation.commit(require_mutation_commit_message("open", [issue.id]))
    print(f"○ Opened: {issue.id} — {issue.title}")
    for ancestor in reopened_ancestors:
        print(f"○ Reopened ancestor: {ancestor.id} — {ancestor.title}")


def _resolve_close_ids(args: argparse.Namespace, project: BeadProject) -> list[str]:
    phases = getattr(args, "phases", None)
    if phases is None:
        return args.ids
    if len(args.ids) != 1:
        targets = ", ".join(args.ids)
        raise PhaseSelectorError(
            f"--phases takes exactly one epic bead ID (got {len(args.ids)}: {targets})"
        )
    phase_numbers = parse_phase_selectors(phases)
    return resolve_epic_phase_ids(project, args.ids[0], phase_numbers)


def _mutation_outcome_ids(outcome: dict[str, object], field: str) -> list[str]:
    values = outcome.get(field)
    if not isinstance(values, list):
        return []
    return [str(value) for value in values]


def _print_close_results(
    issues: list[Issue],
    *,
    closed_ids: list[str],
    already_closed_ids: list[str],
    noted_ids: list[str],
    cascade_closed_ids: list[str],
) -> None:
    closed = set(closed_ids)
    already_closed = set(already_closed_ids)
    noted = set(noted_ids)
    cascade_closed = set(cascade_closed_ids)

    for issue in issues:
        if issue.id in cascade_closed:
            _print_close_result_row("↳", "Closed", issue)
        elif issue.id in closed:
            _print_close_result_row("✓", "Closed", issue)
        elif issue.id in already_closed:
            resolution = issue.resolution.value if issue.resolution else "(unrecorded)"
            metadata = f" ({issue.closed_at or 'unknown close time'} · {resolution})"
            _print_close_result_row("·", "Already closed", issue, metadata)

        if issue.id in noted:
            _print_close_result_row("+", "Noted", issue)


def _print_close_result_row(
    glyph: str,
    label: str,
    issue: Issue,
    suffix: str = "",
) -> None:
    prefix = f"{glyph} {label}"
    print(f"{prefix:<18}{issue.id} — {issue.title}{suffix}")


def handle_bead_close(args: argparse.Namespace) -> None:
    with bead_store_mutation(
        auto_commit_bead_store,
        no_push=getattr(args, "no_push", False),
    ) as mutation:
        try:
            resolved_ids = _resolve_close_ids(args, mutation.project)
            note = getattr(args, "note", None)
            author = None
            if note is not None:
                identity = discover_agent_identity()
                author = (
                    identity.name if identity is not None else mutation.project.owner
                )
            closed = mutation.project.close(
                resolved_ids,
                reason=args.reason,
                resolution=getattr(args, "resolution", None),
                force=getattr(args, "force", False),
                note=note,
                author=author,
            )
        except KeyError as exc:
            message = str(exc.args[0]) if exc.args else ""
            missing_id = message.rsplit("Issue not found:", 1)[-1].strip()
            print(f"Error: issue not found: {missing_id}", file=sys.stderr)
            sys.exit(1)
        except PhaseSelectorError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        outcome = mutation.project.last_mutation_outcome
        closed_ids = _mutation_outcome_ids(outcome, "closed_ids")
        already_closed_ids = _mutation_outcome_ids(outcome, "already_closed_ids")
        noted_ids = _mutation_outcome_ids(outcome, "noted_ids")
        cascade_closed_ids = _mutation_outcome_ids(outcome, "cascade_closed_ids")
        commit_message = close_mutation_commit_message(
            closed_ids=closed_ids,
            cascade_closed_ids=cascade_closed_ids,
            noted_ids=noted_ids,
        )
        if commit_message is not None:
            mutation.commit(commit_message)
    _print_close_results(
        closed,
        closed_ids=closed_ids,
        already_closed_ids=already_closed_ids,
        noted_ids=noted_ids,
        cascade_closed_ids=cascade_closed_ids,
    )


def handle_bead_rm(args: argparse.Namespace) -> None:
    with bead_store_mutation(auto_commit_bead_store) as mutation:
        try:
            removed = mutation.project.remove_many(args.ids)
        except KeyError as exc:
            message = str(exc.args[0]) if exc.args else ""
            missing_id = message.rsplit("Issue not found:", 1)[-1].strip()
            print(f"Error: issue not found: {missing_id}", file=sys.stderr)
            sys.exit(1)
        mutation.commit(require_mutation_commit_message("rm", args.ids))
    for issue in removed:
        print(f"✗ Removed: {issue.id} — {issue.title}")


_parse_type_arg = parse_type_arg
