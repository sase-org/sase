"""Handlers for the ``sase goal`` command group (epic sase-1bu, phase cli).

Bare ``sase goal`` defaults to ``list`` through the central
``_default_list_subcommands`` registry. Reads render through the
sase-core terminal renderer so the slow path and the lean
``goal_fast_path`` entry point print byte-identical output.
Mutations go through the locked :func:`apply_goal_action` transaction.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone, UTC
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.goals.store import GoalLedger, resolve_goal_ledger

if TYPE_CHECKING:
    from sase.goals.write import GoalWriteOutcome

logger = logging.getLogger(__name__)

HUMAN_ONLY_VERBS = frozenset({"new", "edit", "drop", "reopen", "merge"})

HUMAN_VERB_REFUSAL = (
    "sase goal {verb} is a human verb: only a person creates, reshapes, "
    "or settles a goal. Agents may run `sase goal list` and `sase goal show`."
)

HISTORY_STATUSES = frozenset({"done", "dropped", "settled", "all"})

_LEDGER_MISSING_MARKERS = ("missing", "no such file")


def utc_now_iso() -> str:
    """Return now as RFC3339 millis, the clock reading renderers need."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _current_project_name() -> str:
    """Return the project name for the current working directory."""
    from sase.main.init_memory.config import project_memory_name
    from sase.project_aliases import resolve_project_alias_ref

    return resolve_project_alias_ref(project_memory_name(Path.cwd()))


def _in_agent_run() -> bool:
    """Return True inside an agent run (identity or ``SASE_AGENT``)."""
    if os.environ.get("SASE_AGENT") or os.environ.get("SASE_AGENT_NAME"):
        return True
    try:
        from sase.agent.identity import discover_agent_identity

        return discover_agent_identity() is not None
    except Exception:  # noqa: BLE001 - refusal fails closed on errors.
        return True


def _refuse_human_verb(verb: str) -> int | None:
    """Refuse human-only *verb* inside agent runs; None when allowed."""
    if verb in HUMAN_ONLY_VERBS or verb == "repair":
        if _in_agent_run():
            print(HUMAN_VERB_REFUSAL.format(verb=verb), file=sys.stderr)
            return 2
    return None


def _normalize_goal_id_token(token: str) -> tuple[str | None, str]:
    """Split ``ID`` forms into ``(project_or_None, id)``.

    Accepts ``7k2mq``, ``⌖7k2mq``, ``goal:7k2mq``, and
    ``goal:<project>@7k2mq``.
    """
    text = token.strip().removeprefix("⌖").removeprefix("goal:")
    if "@" in text:
        project, _, rest = text.partition("@")
        if project and rest:
            return project, rest.lower()
    return None, text.lower()


def _is_ledger_missing(error: Exception) -> bool:
    message = str(error).lower()
    return "goal_ledger:store:" in message and any(
        marker in message for marker in _LEDGER_MISSING_MARKERS
    )


def _should_colorize() -> bool:
    from sase.core.term_color import should_colorize

    try:
        return bool(should_colorize(sys.stdout))
    except Exception:  # noqa: BLE001 - color never fails a command.
        return False


def _compact_rows() -> bool:
    if _in_agent_run():
        return True
    try:
        return not sys.stdout.isatty()
    except Exception:  # noqa: BLE001 - layout never fails a command.
        return False


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))


def _sync_footer(ledger: GoalLedger) -> dict[str, Any]:
    from sase.goals.sync_status import goal_sync_status

    try:
        return dict(goal_sync_status(ledger))
    except Exception as exc:  # noqa: BLE001 - freshness never fails a read.
        logger.warning("goal sync status failed: %s", exc)
        return {
            "mode": ledger.mode,
            "synced_at": None,
            "synced_ago_seconds": None,
            "unpublished": False,
            "refreshing": False,
        }


def _render_list_text(
    ledger: GoalLedger,
    goals: list[dict[str, Any]],
    *,
    now: str,
    empty_label: str,
    color: bool,
    compact: bool,
) -> str:
    from sase.core.goal_ledger_facade import goal_render_list

    status = _sync_footer(ledger)
    return goal_render_list(
        {
            "goals": goals,
            "project": ledger.project,
            "mode": ledger.mode,
            "synced_ago_seconds": status.get("synced_ago_seconds"),
            "unpublished": bool(status.get("unpublished")),
            "refreshing": bool(status.get("refreshing")),
            "color": color,
            "compact": compact,
            "now": now,
            "empty_label": empty_label,
        }
    )


def handle_goal_list(args: argparse.Namespace) -> int:
    """Run ``sase goal list``; return the process exit code."""
    if getattr(args, "all_projects", False):
        return _handle_goal_list_all(args)
    project = _current_project_name()
    ledger = resolve_goal_ledger(project)
    if getattr(args, "fresh", False) and ledger.mode == "shared":
        from sase.goals.fetch_worker import run_goals_fetch

        outcome = run_goals_fetch(project, force=True)
        if outcome.get("error") and not outcome.get("integrated"):
            print(
                f"sase goal list: refresh failed: {outcome['error']}",
                file=sys.stderr,
            )
    elif not getattr(args, "fresh", False):
        from sase.goals.fetch_worker import maybe_spawn_goals_fetch

        try:
            maybe_spawn_goals_fetch(project)
        except Exception as exc:  # noqa: BLE001 - spawn fails open.
            logger.warning("goals fetch spawn failed: %s", exc)
    return _print_goal_list(ledger, args)


def _print_goal_list(ledger: GoalLedger, args: argparse.Namespace) -> int:
    from sase.core.goal_ledger_facade import (
        goal_ledger_history,
        goal_ledger_list,
    )

    status = str(getattr(args, "status", "unsettled") or "unsettled")
    limit = getattr(args, "limit", None)
    now = utc_now_iso()
    color = _should_colorize()
    compact = _compact_rows()
    as_json = bool(getattr(args, "json", False))
    try:
        if status in HISTORY_STATUSES:
            payload = goal_ledger_history(
                ledger.root,
                {"status": status, "limit": limit if limit else 20},
            )
        else:
            list_filter: dict[str, Any] = {}
            if status != "unsettled":
                list_filter["status"] = status
            if limit:
                list_filter["limit"] = limit
            payload = goal_ledger_list(
                ledger.root, list_filter if list_filter else None
            )
    except Exception as exc:
        if _is_ledger_missing(exc):
            payload = {
                "schema_version": 1,
                "project": ledger.project,
                "generated_at": now,
                "stale_markers": 0,
                "goals": [],
            }
        else:
            print(f"sase goal list: {exc}", file=sys.stderr)
            return 1
    if as_json:
        _print_json(payload)
        return 0
    print(
        _render_list_text(
            ledger,
            list(payload.get("goals", [])),
            now=now,
            empty_label=status if status != "unsettled" else "active",
            color=color,
            compact=compact,
        )
    )
    return 0


def _handle_goal_list_all(args: argparse.Namespace) -> int:
    from sase.workspace_provider.inventory import collect_workspace_inventory

    try:
        inventory = collect_workspace_inventory()
    except Exception as exc:
        print(f"sase goal list: {exc}", file=sys.stderr)
        return 1
    names = sorted({info.project for info in inventory.projects})
    if not names:
        print("No enabled projects have goal ledgers yet.")
        return 0
    exit_code = 0
    for name in names:
        try:
            ledger = resolve_goal_ledger(name)
        except Exception as exc:  # noqa: BLE001 - one project never blocks.
            print(f"⌖ Goals · {name}\n  unavailable: {exc}")
            exit_code = 1
            continue
        args = argparse.Namespace(**{**vars(args), "all_projects": False})
        print(f"⌖ Goals · {name}")
        if not _ledger_exists(ledger):
            print("  no goals yet")
            continue
        code = _print_goal_list(ledger, args)
        exit_code = exit_code or code
    return exit_code


def _ledger_exists(ledger: GoalLedger) -> bool:
    return (ledger.root / "STORE.json").exists()


def handle_goal_show(args: argparse.Namespace) -> int:
    """Run ``sase goal show``; return the process exit code."""
    from sase.core.goal_ledger_facade import goal_ledger_show

    token = str(args.goal_id)
    id_project, goal_id = _normalize_goal_id_token(token)
    project = id_project or _current_project_name()
    ledger = resolve_goal_ledger(project)
    now = utc_now_iso()
    try:
        state = goal_ledger_show(ledger.root, goal_id)
    except Exception as exc:
        if _is_ledger_missing(exc):
            print(
                f"sase goal show: unknown goal goal:{goal_id} in {project}",
                file=sys.stderr,
            )
        else:
            print(f"sase goal show: {exc}", file=sys.stderr)
        return 1
    if bool(getattr(args, "json", False)):
        _print_json(state)
        return 0
    from sase.core.goal_ledger_facade import goal_render_card

    print(goal_render_card(state, now, color=_should_colorize()))
    return 0


def _idempotency_key(verb: str) -> str:
    return f"cli:{verb}:{uuid.uuid4().hex[:12]}"


def _run_mutation(args: argparse.Namespace, verb: str, action: dict[str, Any]) -> int:
    from sase.goals.write import apply_goal_action

    refused = _refuse_human_verb(verb)
    if refused is not None:
        return refused
    project = _current_project_name()
    ledger = resolve_goal_ledger(project)
    try:
        outcome = apply_goal_action(ledger, action)
    except Exception as exc:
        print(f"sase goal {verb}: {exc}", file=sys.stderr)
        return 1
    if outcome.status == "refused":
        detail = outcome.message or outcome.code or "refused"
        code = f" ({outcome.code})" if outcome.code else ""
        print(f"sase goal {verb}: {detail}{code}", file=sys.stderr)
        return 1
    if outcome.status == "stale_basis":
        print(
            f"sase goal {verb}: the goal changed under you; "
            "re-run `sase goal show` and retry",
            file=sys.stderr,
        )
        return 1
    _print_write_confirmation(ledger, verb, action, outcome)
    return 0


def _print_write_confirmation(
    ledger: GoalLedger,
    verb: str,
    action: dict[str, Any],
    outcome: GoalWriteOutcome,
) -> None:
    states = list(getattr(outcome, "states", ()) or ())
    by_id = {state.get("id"): state for state in states if isinstance(state, dict)}
    if verb == "merge":
        target_id = str(action.get("target_id", ""))
        target = by_id.get(target_id, {})
        title = str(target.get("title", ""))
        print(f"⌖ Merged goal:{action.get('source_id')} into goal:{target_id}  {title}")
    else:
        past = {
            "new": "Created",
            "edit": "Edited",
            "drop": "Dropped",
            "reopen": "Reopened",
        }[verb]
        goal_id = outcome.goal_id or ""
        title = str(by_id.get(goal_id, {}).get("title", ""))
        print(f"⌖ {past} goal:{goal_id}  {title}".rstrip())
    print(f"  {_publish_line(ledger, outcome)}")


def _publish_line(ledger: GoalLedger, outcome: GoalWriteOutcome) -> str:
    goal_id = outcome.goal_id or ""
    cite = f"cite it as @goal:{goal_id}" if goal_id else ""
    if ledger.mode == "local":
        return f"saved locally · {cite}".rstrip(" ·")
    if outcome.published:
        if getattr(outcome, "offline_mint", False):
            return f"published · minted offline · {cite}".rstrip(" ·")
        return f"published · {cite}".rstrip(" ·")
    error = getattr(outcome, "publish_error", None) or "publish failed"
    return f"saved locally · ↑ {error} — will retry automatically"


def handle_goal_new(args: argparse.Namespace) -> int:
    """Run ``sase goal new``; return the process exit code."""
    action = {
        "action": "new",
        "title": args.title,
        "outcome": args.outcome,
        "criteria": [{"text": text} for text in (args.criterion or [])],
        "project": _current_project_name(),
        "via": "cli",
        "idempotency_key": _idempotency_key("new"),
    }
    return _run_mutation(args, "new", action)


def handle_goal_edit(args: argparse.Namespace) -> int:
    """Run ``sase goal edit``; return the process exit code."""
    _, goal_id = _normalize_goal_id_token(str(args.goal_id))
    if (
        args.title is None
        and args.outcome is None
        and not (args.criterion or [])
        and not (args.remove_criterion or [])
    ):
        print("sase goal edit: nothing to change", file=sys.stderr)
        return 2
    action: dict[str, Any] = {
        "action": "edit",
        "goal_id": goal_id,
        "idempotency_key": _idempotency_key("edit"),
    }
    if args.title is not None:
        action["title"] = args.title
    if args.outcome is not None:
        action["outcome"] = args.outcome
    if args.criterion:
        action["criteria_added"] = [{"text": text} for text in args.criterion]
    if args.remove_criterion:
        action["criteria_removed"] = list(args.remove_criterion)
    return _run_mutation(args, "edit", action)


def handle_goal_drop(args: argparse.Namespace) -> int:
    """Run ``sase goal drop``; return the process exit code."""
    _, goal_id = _normalize_goal_id_token(str(args.goal_id))
    return _run_mutation(
        args,
        "drop",
        {
            "action": "drop",
            "goal_id": goal_id,
            "why": args.why,
            "idempotency_key": _idempotency_key("drop"),
        },
    )


def handle_goal_reopen(args: argparse.Namespace) -> int:
    """Run ``sase goal reopen``; return the process exit code."""
    _, goal_id = _normalize_goal_id_token(str(args.goal_id))
    return _run_mutation(
        args,
        "reopen",
        {
            "action": "reopen",
            "goal_id": goal_id,
            "message": args.message,
            "idempotency_key": _idempotency_key("reopen"),
        },
    )


def handle_goal_merge(args: argparse.Namespace) -> int:
    """Run ``sase goal merge``; return the process exit code."""
    _, source_id = _normalize_goal_id_token(str(args.goal_id))
    _, target_id = _normalize_goal_id_token(str(args.into))
    action: dict[str, Any] = {
        "action": "merge",
        "source_id": source_id,
        "target_id": target_id,
        "idempotency_key": _idempotency_key("merge"),
    }
    if getattr(args, "why", None):
        action["why"] = args.why
    return _run_mutation(args, "merge", action)


def handle_goal_doctor(args: argparse.Namespace) -> int:
    """Run ``sase goal doctor``; return the process exit code."""
    from sase.core.goal_ledger_facade import goal_ledger_doctor

    repair = bool(getattr(args, "repair", False))
    if repair:
        refused = _refuse_human_verb("repair")
        if refused is not None:
            return refused
    project = _current_project_name()
    ledger = resolve_goal_ledger(project)
    try:
        report = goal_ledger_doctor(ledger.root, {"repair": repair})
    except Exception as exc:
        print(f"sase goal doctor: {exc}", file=sys.stderr)
        return 1
    if bool(getattr(args, "json", False)):
        _print_json(report)
        return 0 if report.get("ok") else 1
    _print_doctor_report(ledger, report, repair=repair)
    if repair and report.get("changed_paths") and ledger.mode == "shared":
        _commit_doctor_repair(ledger)
    _print_sync_counters(ledger)
    return 0 if report.get("ok") else 1


def _print_doctor_report(
    ledger: GoalLedger, report: dict[str, Any], *, repair: bool
) -> None:
    checks = list(report.get("checks", []))
    failed = [check for check in checks if not check.get("ok")]
    if report.get("ok"):
        print(f"⌖ Goals · {ledger.project}: healthy")
    else:
        print(f"⌖ Goals · {ledger.project}: {len(failed)} problem(s)")
    for check in checks:
        mark = "ok" if check.get("ok") else "FAIL"
        detail = str(check.get("message", ""))
        goal = check.get("goal_id")
        scope = f" goal:{goal}" if goal else ""
        line = f"  [{mark}] {check.get('code')}{scope}"
        print(f"{line} — {detail}" if detail else line)
    for goal_id in report.get("unreadable", []):
        print(f"  ⚠ unreadable goal:{goal_id} (run sase goal doctor)")
    if repair and report.get("changed_paths"):
        print(
            f"  repaired {len(report['changed_paths'])} path(s): "
            + ", ".join(str(path) for path in report["changed_paths"][:5])
        )


def _commit_doctor_repair(ledger: GoalLedger) -> None:
    from sase.goals.write import commit_goal_paths

    if ledger.hidden_clone is None:
        return
    try:
        from sase.sdd._git_contention import store_git_write_lock

        with store_git_write_lock(
            ledger.hidden_clone, op="goals.doctor", mutates_worktree=True
        ) as acquired:
            if not acquired:
                print(
                    "sase goal doctor: repair applied locally but the "
                    "store lock was busy; run again to commit",
                    file=sys.stderr,
                )
                return
            commit_goal_paths(
                ledger.hidden_clone, "chore(goals): reconcile live markers"
            )
    except Exception as exc:  # noqa: BLE001 - repair already applied.
        print(f"sase goal doctor: repair commit failed: {exc}", file=sys.stderr)


def _print_sync_counters(ledger: GoalLedger) -> None:
    status = _sync_footer(ledger)
    print(
        "  publishes {publishes} · push retries {push_retries} · "
        "rejected after max {rejected_after_max}".format(
            publishes=status.get("publishes", 0),
            push_retries=status.get("push_retries", 0),
            rejected_after_max=status.get("rejected_after_max", 0),
        )
    )


__all__ = [
    "HISTORY_STATUSES",
    "HUMAN_ONLY_VERBS",
    "HUMAN_VERB_REFUSAL",
    "handle_goal_doctor",
    "handle_goal_drop",
    "handle_goal_edit",
    "handle_goal_list",
    "handle_goal_merge",
    "handle_goal_new",
    "handle_goal_reopen",
    "handle_goal_show",
    "utc_now_iso",
]
