"""Create/update/delete bead CLI command handlers."""

from __future__ import annotations

import argparse
import getpass
import re
import sys
from pathlib import Path

from rich.console import Console
from rich.markup import escape

from sase.agent.identity import (
    current_instant,
    discover_agent_identity,
    resolve_observation_window_start,
)
from sase.bead.cli_common import (
    auto_commit_bead_store,
    bead_store_mutation,
    find_beads_location,
    init_beads,
    storage_plan_path,
)
from sase.bead.model import BeadTier, Issue, IssueType, Status
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
from sase.bead.snooze_presentation import (
    SNOOZE_ACCENT,
    SNOOZE_GLYPH,
    snooze_plus_one_label,
    snooze_summary,
)
from sase.bead.snooze_time import (
    ACCEPTED_SNOOZE_FORMS,
    SnoozeTimeError,
    parse_snooze_until,
)


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
    - ``task``                        -> TASK, design=None, parent_id=None
    - ``plan(<path>)``                -> PLAN, design=path, parent_id=None
    - ``plan(<path>,<parent_id>)``    -> PLAN, design=path, parent_id=parent_id
    - ``phase(<parent_id>)``          -> PHASE, design=None, parent_id=parent_id
    """
    if value == "task":
        return IssueType.TASK, None, None

    m = re.match(r"^(plan|phase)\((.+)\)$", value)
    if not m:
        print(
            f"Error: invalid --type value: {value}\n"
            "Expected: plan(<plan_file>), plan(<plan_file>,<parent_id>), "
            "phase(<parent_id>), or task",
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
    changespec_name = (
        getattr(args, "patch", None)
        or getattr(args, "changespec", None)  # legacy CLI alias
        or ""
    )
    changespec_bug_id = getattr(args, "bug_id", None) or ""
    if issue_type != IssueType.PLAN and (changespec_name or changespec_bug_id):
        print(
            "Error: Patch metadata can only be attached to plan beads",
            file=sys.stderr,
        )
        sys.exit(1)
    if changespec_bug_id and not changespec_name:
        print("Error: --bug-id requires --patch/--changespec", file=sys.stderr)
        sys.exit(1)
    tier = BeadTier(args.tier) if getattr(args, "tier", None) else None
    if issue_type != IssueType.PLAN and tier is not None:
        print("Error: --tier can only be set on plan beads", file=sys.stderr)
        sys.exit(1)
    size = getattr(args, "size", None)
    if issue_type == IssueType.TASK and size is None:
        print(
            "Error: task beads require -z/--size "
            "(xsmall, small, medium, large, or xlarge)",
            file=sys.stderr,
        )
        sys.exit(1)
    if issue_type == IssueType.PLAN and size is not None:
        print("Error: --size can only be set on phase or task beads", file=sys.stderr)
        sys.exit(1)
    design = ""
    resolved_plan_file: Path | None = None
    if plan_path:
        plan_file = Path(plan_path)
        if not plan_file.exists():
            print(f"Error: plan file not found: {plan_path}", file=sys.stderr)
            sys.exit(1)
        resolved_plan_file = plan_file.resolve()
        design = storage_plan_path(resolved_plan_file)

    from sase.bead.attribution import plan_proposed_by, resolve_bead_creator

    creator = resolve_bead_creator(
        issue_type=issue_type,
        plan_proposed_by=(
            plan_proposed_by(resolved_plan_file)
            if resolved_plan_file is not None
            else None
        ),
    )

    prefix_repair: tuple[str, str] | None = None
    with bead_store_mutation(auto_commit_bead_store) as mutation:
        proj = mutation.project
        if parent_id:
            try:
                parent_id = proj.show(parent_id).id
            except KeyError:
                print(f"Error: parent bead not found: {parent_id}", file=sys.stderr)
                sys.exit(1)
            except ValueError as exc:
                print(f"Error: {exc}", file=sys.stderr)
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
                external_ref=getattr(args, "external_ref", None) or "",
                model=getattr(args, "model", None) or "",
                size=size,
                created_by=creator,
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        prefix_repair = proj.last_prefix_repair
        mutation.commit(require_mutation_commit_message("create", [issue.id]))
    if prefix_repair is not None:
        from sase.bead.cli_work_from_plan_render import render_prefix_repair

        render_prefix_repair(*prefix_repair)
    print(f"Created {issue.issue_type.value}: {issue.id} — {issue.title}")


def _withheld_reopen_note(reporter: str, closed_at: str) -> str:
    return (
        f"{reporter}'s +1 postdates the {closed_at} close, but its "
        "observation window does not, so the reopen was withheld and the "
        "bead was left closed. Re-file with --verified-after-close if this "
        "reproduces on a tree that already contains the close."
    )


def handle_bead_plus_one(args: argparse.Namespace) -> None:
    """Record independently attributed evidence on an existing task bead."""
    verified_after_close = bool(getattr(args, "verified_after_close", False))
    with bead_store_mutation(auto_commit_bead_store) as mutation:
        try:
            reporter = getattr(args, "author", None)
            if reporter is None:
                identity = discover_agent_identity()
                reporter = (
                    identity.name if identity is not None else mutation.project.owner
                )
            if verified_after_close:
                target = mutation.project.show(args.id)
                if target.status is not Status.CLOSED:
                    print(
                        "Error: --verified-after-close requires a closed "
                        f"bead (currently {target.status.value}): {args.id}",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                observed_since = current_instant()
            else:
                observed_since = resolve_observation_window_start()
            issue, changed = mutation.project.plus_one(
                args.id,
                args.note,
                reporter=reporter,
                refs=getattr(args, "ref", None) or (),
                observed_since=observed_since,
            )
        except KeyError:
            print(f"Error: issue not found: {args.id}", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        outcome = mutation.project.last_mutation_outcome
        reopen_withheld = bool(outcome.get("reopen_withheld"))
        reopen_withheld_closed_at = str(outcome.get("reopen_withheld_closed_at") or "")
        if changed and reopen_withheld:
            mutation.project.append_note(
                issue.id,
                _withheld_reopen_note(reporter, reopen_withheld_closed_at),
                author=reporter,
            )
        if changed:
            mutation.commit(require_mutation_commit_message("+1", [issue.id]))

    report_word = "report" if issue.plus_one_count == 1 else "reports"
    if changed and reopen_withheld:
        # Soft wrap: the reminder names two commands, and a mid-word wrap
        # (e.g. splitting `sase bead open`) reads as a broken instruction.
        Console(soft_wrap=True).print(
            f"[yellow]·[/yellow] +1 recorded: {escape(issue.id)} — "
            f"[bold]+{issue.plus_one_count}[/bold] independent {report_word}, "
            f"but the close at {escape(reopen_withheld_closed_at)} was left "
            "standing (reopen withheld). Pass --verified-after-close if you "
            "reproduced this after the close, or `sase bead open` to reopen "
            "directly."
        )
        return
    if changed:
        Console().print(
            f"[green]✓[/green] +1 recorded: {escape(issue.id)} — "
            f"[bold]+{issue.plus_one_count}[/bold] independent {report_word}"
        )
        return
    if reporter == issue.created_by:
        reason = "the task creator does not count as an additional reporter"
    else:
        reason = (
            f"{reporter} already reported this task; use `sase bead note` "
            "for supplementary evidence"
        )
    Console().print(
        f"[yellow]·[/yellow] Unchanged: {escape(issue.id)} — "
        f"{escape(reason)} ([bold]+{issue.plus_one_count}[/bold])"
    )


def _print_update_results(
    issues: list[Issue],
    *,
    changed_ids: list[str],
    reopened_ancestors: list[Issue],
) -> None:
    changed = set(changed_ids)
    for issue in issues:
        if issue.id in changed:
            print(f"✓ Updated issue: {issue.id} — {issue.title}")
        else:
            print(f"· Unchanged: {issue.id} — {issue.title}")
    for ancestor in reopened_ancestors:
        print(f"○ Reopened ancestor: {ancestor.id} — {ancestor.title}")


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
        if getattr(args, "external_ref", None) is not None:
            fields["external_ref"] = args.external_ref
        if getattr(args, "clear_external_ref", False):
            fields["external_ref"] = ""
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
            issues = proj.update_many(args.ids, **fields)
        except KeyError as exc:
            message = str(exc.args[0]) if exc.args else ""
            missing_id = message.rsplit("Issue not found:", 1)[-1].strip()
            print(f"Error: issue not found: {missing_id}", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        outcome = mutation.project.last_mutation_outcome
        changed_ids = _mutation_outcome_ids(outcome, "issue_ids")
        reopened_ancestor_ids = _mutation_outcome_ids(outcome, "reopened_ancestor_ids")
        reopened_ancestors = [
            proj.show(ancestor_id) for ancestor_id in reopened_ancestor_ids
        ]
        if changed_ids:
            mutation.commit(require_mutation_commit_message("update", changed_ids))
    _print_update_results(
        issues,
        changed_ids=changed_ids,
        reopened_ancestors=reopened_ancestors,
    )


def _snooze_actor(project: BeadProject) -> str:
    """Resolve who to attribute a snooze to, never blank.

    The store rejects an unattributed snooze, so this falls through the acting
    agent, the configured store owner, and finally the local user rather than
    failing a mutation over missing configuration.
    """
    identity = discover_agent_identity()
    if identity is not None:
        return identity.name
    return project.owner.strip() or getpass.getuser()


def handle_bead_snooze(args: argparse.Namespace) -> None:
    """Defer task beads until a wake time, or wake them early."""
    cancel = bool(getattr(args, "cancel", False))
    until_arg = getattr(args, "until", None)
    plus_ones = getattr(args, "plus_ones", None)
    reason = getattr(args, "reason", None) or ""
    if cancel and (until_arg or plus_ones is not None or reason):
        print(
            "Error: --cancel takes no wake conditions; drop -u/-p/-r",
            file=sys.stderr,
        )
        sys.exit(1)
    if not cancel and not until_arg:
        print(
            f"Error: -u/--until is required; expected {ACCEPTED_SNOOZE_FORMS}",
            file=sys.stderr,
        )
        sys.exit(1)
    if plus_ones is not None and plus_ones <= 0:
        print("Error: -p/--plus-ones must be a positive count", file=sys.stderr)
        sys.exit(1)

    until = ""
    if until_arg:
        try:
            until = parse_snooze_until(until_arg)
        except SnoozeTimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    with bead_store_mutation(auto_commit_bead_store) as mutation:
        proj = mutation.project
        actor = _snooze_actor(proj)
        # Resolve every id before mutating any bead, so a typo in the last
        # argument cannot leave the first half of the batch snoozed.
        resolved_ids: list[str] = []
        for raw_id in args.ids:
            try:
                resolved_ids.append(proj.show(raw_id).id)
            except KeyError:
                print(f"Error: issue not found: {raw_id}", file=sys.stderr)
                sys.exit(1)
            except ValueError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                sys.exit(1)
        issues: list[Issue] = []
        for issue_id in resolved_ids:
            try:
                if cancel:
                    issues.append(proj.cancel_snooze(issue_id, actor=actor))
                else:
                    issues.append(
                        proj.snooze(
                            issue_id,
                            until=until,
                            plus_ones=plus_ones,
                            reason=reason,
                            actor=actor,
                        )
                    )
            except KeyError:
                print(f"Error: issue not found: {issue_id}", file=sys.stderr)
                sys.exit(1)
            except ValueError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                sys.exit(1)
        mutation.commit(
            require_mutation_commit_message(
                "snooze_cancel" if cancel else "snooze",
                [issue.id for issue in issues],
            )
        )
    # Soft wrap: a confirmation naming an absolute time, a relative time, and
    # a +1 target is easily wider than 80 columns, and a wrapped one reads as
    # two unrelated lines.
    console = Console(soft_wrap=True)
    for issue in issues:
        console.print(_snooze_result_line(issue, canceled=cancel))


def _snooze_result_line(issue: Issue, *, canceled: bool) -> str:
    """Render one confirmation naming both wake conditions in Rich markup."""
    if canceled or issue.snooze is None:
        return f"[green]○[/green] Woken: {escape(issue.id)} — {escape(issue.title)}"
    line = (
        f"[{SNOOZE_ACCENT}]{SNOOZE_GLYPH}[/{SNOOZE_ACCENT}] Snoozed "
        f"[bold]{escape(issue.id)}[/bold] "
        f"{escape(snooze_summary(issue.snooze))}"
    )
    if plus_one := snooze_plus_one_label(issue):
        line += f" [dim]·[/dim] wakes early at {escape(plus_one)}"
    return line


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
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
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
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        mutation.commit(
            require_mutation_commit_message("rm", [issue.id for issue in removed])
        )
    for issue in removed:
        print(f"✗ Removed: {issue.id} — {issue.title}")


_parse_type_arg = parse_type_arg
