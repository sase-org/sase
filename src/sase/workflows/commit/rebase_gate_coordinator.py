"""Narrow gate coordinator wiring the after-rebase check into git dispatch.

Phase ``publication`` of the rebased-stitch gate epic. This module owns git
fact collection (immutable IDs plus the NUL-safe changed-path union) and the
pending-context lifecycle persisted on the checkpoint payload. Generic
bounded execution stays in :mod:`sase.workflows.commit.rebase_gate_runner`
and policy stays in Rust (:mod:`sase.core.rebase_gate`); the dispatch mixin
only calls these helpers.

All helpers are best-effort and fail open: gate problems never raise, so a
checker or git failure can only skip the check, never block publication.
Only cancellation propagates. Candidate inputs are checkpointed before a
rebase, and the current result identity is checkpointed before the runner
starts, so interruption cannot lose a required check.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Literal, cast

from sase.output import print_status
from sase.core.rebase_gate import (
    ChangedPathWire,
    ChangeKind,
    ContextWire,
    RebaseFactsWire,
)
from sase.workflows.commit.checkpoint import persist_checkpoint_payload
from sase.workflows.commit.rebase_gate_budget import (
    GateBudgetExhausted,
    GateWorkBudget,
)
from sase.workflows.commit.rebase_gate_runner import (
    GateSettings,
    RebaseGateOutcome,
    load_after_rebase_gate_settings,
    run_after_rebase_gate,
)

GateOutcome = Literal["applied", "conflict", "no_op", "failed"]

REBASE_GATE_PENDING_KEY = "_rebase_gate_pending"
REBASE_GATE_BLOCKED_KEY = "_rebase_gate_blocked"
REBASE_GATE_CAPTURE_KEY = "_rebase_gate_capture"

_DEFAULT_GATE_TIMEOUT_SECONDS = 10.0

__all__ = [
    "REBASE_GATE_BLOCKED_KEY",
    "REBASE_GATE_CAPTURE_KEY",
    "REBASE_GATE_PENDING_KEY",
    "begin_rebase_gate_capture",
    "complete_rebase_gate_check",
    "clear_rebase_gate_state",
    "is_gate_blocked",
    "run_pending_rebase_gate",
    "stash_rebase_gate_for_conflict",
]


class _GateDiscoveryError(RuntimeError):
    """A gate-specific Git query failed; it cannot certify a clean tree."""


def _warn_gate(reason: str, detail: str | None = None) -> None:
    """Emit visible fail-open evidence for coordinator-side failures."""
    print_status(f"Rebase gate warning: {reason}", "warning")
    if detail:
        print_status(f"Rebase gate detail: {detail}", "warning")


def _load_pending_context(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the pending gate context stored on *payload*, if it is valid."""
    pending = payload.get(REBASE_GATE_PENDING_KEY)
    if not isinstance(pending, dict):
        return None
    if pending.get("schema_version") != 1:
        return None
    if not isinstance(pending.get("inputs"), list) or not pending["inputs"]:
        return None
    return pending


def _store_pending_context(
    payload: dict[str, Any], context: dict[str, Any] | None
) -> None:
    """Persist *context* on *payload*; None clears the pending check."""
    if context is None:
        payload.pop(REBASE_GATE_PENDING_KEY, None)
        payload.pop(REBASE_GATE_BLOCKED_KEY, None)
    else:
        payload[REBASE_GATE_PENDING_KEY] = context


def _store_capture(payload: dict[str, Any], capture: dict[str, Any] | None) -> None:
    if capture is None:
        payload.pop(REBASE_GATE_CAPTURE_KEY, None)
    else:
        payload[REBASE_GATE_CAPTURE_KEY] = capture


def clear_rebase_gate_state(payload: dict[str, Any]) -> None:
    """Clear gate state after the corresponding commit is pushed."""
    _store_pending_context(payload, None)
    _store_capture(payload, None)
    payload.pop(REBASE_GATE_BLOCKED_KEY, None)
    persist_checkpoint_payload(payload)


def is_gate_blocked(payload: Mapping[str, Any]) -> bool:
    """Return whether *payload* carries an explicit gate finding."""
    return payload.get(REBASE_GATE_BLOCKED_KEY) is True


def _run_git(
    run: Callable[..., Any],
    args: list[str],
    cwd: str,
    budget: GateWorkBudget,
) -> str:
    """Run one gate Git query within the remaining shared budget."""
    try:
        out = budget.run(run, args, cwd)
    except GateBudgetExhausted:
        raise
    except Exception as exc:
        raise _GateDiscoveryError(f"{' '.join(args)} failed: {exc}") from exc
    if out is None or not getattr(out, "success", False):
        detail = ""
        if out is not None:
            detail = (getattr(out, "stderr", "") or getattr(out, "stdout", "")).strip()
        raise _GateDiscoveryError(
            f"{' '.join(args)} failed" + (f": {detail}" if detail else "")
        )
    return getattr(out, "stdout", "") or ""


def begin_rebase_gate_capture(
    cwd: str,
    run: Callable[..., Any],
    upstream_ref: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Capture immutable git IDs before a rebase that may combine work.

    The candidate input IDs and original path union are checkpointed before
    the rebase starts. The in-memory budget/settings travel with the capture,
    but never enter the JSON checkpoint payload.
    """
    budget = GateWorkBudget(_DEFAULT_GATE_TIMEOUT_SECONDS)
    settings, warning = load_after_rebase_gate_settings(cwd, budget)
    if warning is not None:
        _warn_gate(*warning)
        return None
    if settings is None or not settings.hook_command:
        return None
    capture: dict[str, Any] = {
        "candidate": None,
        "_budget": budget,
        "_settings": settings,
    }
    try:
        repo_root = _run_git(
            run, ["git", "rev-parse", "--show-toplevel"], cwd, budget
        ).strip()
        old_head = _run_git(run, ["git", "rev-parse", "HEAD"], cwd, budget).strip()
        upstream_tip = _run_git(
            run, ["git", "rev-parse", upstream_ref], cwd, budget
        ).strip()
        merge_base = _run_git(
            run, ["git", "merge-base", old_head, upstream_tip], cwd, budget
        ).strip()
        old_tree = _run_git(
            run, ["git", "rev-parse", f"{old_head}^{{tree}}"], cwd, budget
        ).strip()
        ids = {
            "repository_root": repo_root,
            "old_head": old_head,
            "upstream_tip": upstream_tip,
            "merge_base": merge_base,
        }
        candidate = _build_context(ids, "conflict", old_head, old_tree, [], [])
        if candidate is not None:
            local_changes = _collect_changed_paths(
                cwd, run, merge_base, old_head, budget
            )
            upstream_changes = _collect_changed_paths(
                cwd, run, merge_base, upstream_tip, budget
            )
            candidate = _update_context(
                candidate,
                repo_root,
                old_head,
                old_tree,
                [*local_changes, *upstream_changes],
            )
            capture.update(ids=ids, candidate=candidate)
            if payload is not None:
                _store_capture(
                    payload,
                    {"schema_version": 1, "candidate": candidate},
                )
                persist_checkpoint_payload(payload)
        return capture
    except GateBudgetExhausted as exc:
        _warn_gate("gate budget expired during context discovery", str(exc))
        return capture
    except Exception as exc:  # noqa: BLE001 - discovery errors fail open
        _warn_gate("could not discover complete rebase context", str(exc))
        return capture


_STATUS_KIND: dict[str, ChangeKind] = {
    "A": "added",
    "M": "modified",
    "D": "deleted",
    "R": "renamed",
    "C": "copied",
    "T": "type_changed",
    "U": "unmerged",
}


def _collect_changed_paths(
    cwd: str,
    run: Callable[..., Any],
    base: str,
    head: str,
    budget: GateWorkBudget,
) -> list[ChangedPathWire]:
    """Return the NUL-safe ``base..head`` path union with rename metadata."""
    raw = _run_git(
        run,
        [
            "git",
            "diff",
            "--name-status",
            "-z",
            "-M",
            "--no-color",
            base,
            head,
            "--",
        ],
        cwd,
        budget,
    )
    parts = raw.split("\0")
    changes: list[ChangedPathWire] = []
    index = 0
    while index < len(parts):
        status = parts[index]
        index += 1
        if not status:
            continue
        kind = _STATUS_KIND.get(status[:1])
        if kind is None:
            raise _GateDiscoveryError(f"unrecognized git path status {status!r}")
        if kind in ("renamed", "copied"):
            if index + 1 >= len(parts):
                raise _GateDiscoveryError(
                    f"incomplete {kind} record in git path output"
                )
            old_path = parts[index]
            new_path = parts[index + 1]
            index += 2
            if not old_path or not new_path:
                raise _GateDiscoveryError(f"empty path in git {kind} record")
            changes.append({"path": new_path, "kind": kind, "old_path": old_path})
        else:
            if index >= len(parts):
                raise _GateDiscoveryError(
                    f"incomplete {kind} record in git path output"
                )
            path = parts[index]
            index += 1
            if not path:
                raise _GateDiscoveryError(f"empty path in git {kind} record")
            changes.append({"path": path, "kind": kind})
    return changes


def _resolve_current_ids(
    cwd: str, run: Callable[..., Any], budget: GateWorkBudget
) -> tuple[str, str]:
    head = _run_git(run, ["git", "rev-parse", "HEAD"], cwd, budget).strip()
    tree = _run_git(run, ["git", "rev-parse", "HEAD^{tree}"], cwd, budget).strip()
    return head, tree


def _build_context(
    capture: Mapping[str, Any],
    outcome: GateOutcome,
    head: str,
    tree: str,
    local_changes: list[ChangedPathWire],
    upstream_changes: list[ChangedPathWire],
) -> dict[str, Any] | None:
    from sase.core.rebase_gate import build_rebase_gate_context

    facts: RebaseFactsWire = {
        "schema_version": 1,
        "repository_root": capture["repository_root"],
        "old_head": capture["old_head"],
        "upstream_tip": capture["upstream_tip"],
        "merge_base": capture["merge_base"],
        "rebase_outcome": outcome,
        "current_head": head,
        "current_tree": tree,
        "local_changes": local_changes,
        "upstream_changes": upstream_changes,
    }
    try:
        built = build_rebase_gate_context(facts)
    except Exception as exc:
        raise _GateDiscoveryError(
            f"rebase gate policy rejected Git facts: {exc}"
        ) from exc
    if built is None:
        return None
    return cast(dict[str, Any], built)


def _merge_contexts(
    existing: dict[str, Any] | None, incoming: dict[str, Any] | None
) -> dict[str, Any] | None:
    from sase.core.rebase_gate import merge_rebase_gate_contexts

    try:
        merged = merge_rebase_gate_contexts(
            cast(ContextWire | None, existing),
            cast(ContextWire | None, incoming),
        )
    except Exception as exc:
        raise _GateDiscoveryError(
            f"could not merge pending rebase context: {exc}"
        ) from exc
    if merged is None:
        return None
    return cast(dict[str, Any], merged)


def _update_context(
    context: dict[str, Any],
    repo_root: str,
    head: str,
    tree: str,
    changes: list[ChangedPathWire],
) -> dict[str, Any]:
    from sase.core.rebase_gate import ContextUpdateWire, update_rebase_gate_context

    update: ContextUpdateWire = {
        "schema_version": 1,
        "repository_root": repo_root,
        "current_head": head,
        "current_tree": tree,
        "changed_paths": changes,
    }
    try:
        refreshed = update_rebase_gate_context(cast(ContextWire, context), update)
    except Exception as exc:
        raise _GateDiscoveryError(f"could not update rebase context: {exc}") from exc
    return cast(dict[str, Any], refreshed)


def _evaluate_context(
    payload: dict[str, Any],
    context: dict[str, Any],
    repo_root: str,
    budget: GateWorkBudget,
    settings: GateSettings,
) -> tuple[bool, str | None]:
    """Run the gate for *context*; True means the push may proceed."""
    try:
        outcome = run_after_rebase_gate(
            cast(ContextWire, context),
            repo_root,
            budget=budget,
            settings=settings,
        )
    except Exception:
        _warn_gate("rebase gate runner failed; allowing publication")
        return True, None
    decision = outcome.decision
    if _verdict_of(outcome) == "block":
        head = str(context.get("current_head", ""))
        tree = str(context.get("current_tree", ""))
        payload[REBASE_GATE_BLOCKED_KEY] = True
        persist_checkpoint_payload(payload)
        return False, _format_gate_block_message(decision, head=head, tree=tree)
    payload.pop(REBASE_GATE_BLOCKED_KEY, None)
    persist_checkpoint_payload(payload)
    return True, None


def _verdict_of(outcome: RebaseGateOutcome) -> str:
    """Return the facade verdict carried by one executed gate attempt."""
    return str(outcome.decision.get("verdict", ""))


def _format_gate_block_message(
    decision: Mapping[str, Any], *, head: str, tree: str
) -> str:
    """Render an explicit gate-finding message with repair guidance."""
    findings = decision.get("findings", [])
    if not isinstance(findings, list):
        findings = []
    lines = [
        f"Rebase gate finding blocked the push: "
        f"{len(findings)} broken first-party import(s) in the combined tree."
    ]
    for finding in findings[:20]:
        if not isinstance(finding, dict):
            continue
        lines.append(
            f"  {finding.get('path', '?')}:{finding.get('line', '?')}: "
            f"cannot import {finding.get('imported_name', '?')} "
            f"from {finding.get('module', '?')} "
            f"({finding.get('explanation', 'unresolvable import')})"
        )
    if len(findings) > 20:
        lines.append(f"  ... and {len(findings) - 20} more finding(s).")
    if head:
        lines.append(
            f"Local commit {head} is kept unpublished with pushed=false; "
            "the checkpoint is kept."
        )
    else:
        lines.append(
            "The local commit is kept unpublished with pushed=false; "
            "the checkpoint is kept."
        )
    if tree:
        lines[-1] += f" (tree {tree})"
    lines.append(
        "Repair the imports and include the fix in the local commit through "
        "the SASE repair flow, then run `sase stitch create --resume`. "
        "Unstaged edits alone do not change the committed tree the gate checks."
    )
    return "\n".join(lines)


def complete_rebase_gate_check(
    cwd: str,
    run: Callable[..., Any],
    payload: dict[str, Any],
    capture: dict[str, Any] | None,
    *,
    outcome: GateOutcome = "applied",
) -> tuple[bool, str | None]:
    """Refresh, persist, and evaluate the context for a finished rebase."""
    if capture is None:
        return run_pending_rebase_gate(cwd, run, payload)
    budget = cast(GateWorkBudget, capture["_budget"])
    settings = cast(GateSettings, capture["_settings"])
    candidate = capture.get("candidate")
    if candidate is None:
        return _evaluate_pending_with_budget(cwd, run, payload, budget, settings)
    if outcome == "no_op":
        _store_capture(payload, None)
        persist_checkpoint_payload(payload)
        return _evaluate_pending_with_budget(cwd, run, payload, budget, settings)
    if outcome != "applied":
        _warn_gate("rebase result was not confirmed; gate context retained")
        return _evaluate_pending_with_budget(cwd, run, payload, budget, settings)

    try:
        head, tree = _resolve_current_ids(cwd, run, budget)
        upstream_tip = str(capture["ids"]["upstream_tip"])
        resolved_paths = _collect_changed_paths(cwd, run, upstream_tip, head, budget)
        incoming = _update_context(
            cast(dict[str, Any], candidate),
            str(capture["ids"]["repository_root"]),
            head,
            tree,
            resolved_paths,
        )
        merged = _merge_contexts(_load_pending_context(payload), incoming)
        if merged is None:
            raise _GateDiscoveryError("eligible rebase produced no pending context")
        _store_pending_context(payload, merged)
        _store_capture(payload, None)
        persist_checkpoint_payload(payload)
        return _evaluate_context(
            payload,
            merged,
            str(capture["ids"]["repository_root"]),
            budget,
            settings,
        )
    except GateBudgetExhausted as exc:
        _warn_gate("gate budget expired while refreshing rebase context", str(exc))
    except Exception as exc:  # noqa: BLE001 - discovery errors fail open
        _warn_gate("could not refresh rebase context; publication allowed", str(exc))
    return True, None


def stash_rebase_gate_for_conflict(
    cwd: str,
    run: Callable[..., Any],
    payload: dict[str, Any],
    capture: dict[str, Any] | None,
) -> None:
    """Retain pending context when a rebase stops for manual resolution.

    Uses the pre-rebase IDs so a later resume can refresh the context for
    the repaired HEAD; manual resolution cannot bypass the check.
    """
    if capture is None or capture.get("candidate") is None:
        return
    try:
        incoming = cast(dict[str, Any], capture["candidate"])
        merged = _merge_contexts(_load_pending_context(payload), incoming)
        if merged is not None:
            _store_pending_context(payload, merged)
            _store_capture(payload, None)
            persist_checkpoint_payload(payload)
    except Exception as exc:  # noqa: BLE001 - keep the durable candidate
        _warn_gate("could not persist conflict rebase context", str(exc))


def run_pending_rebase_gate(
    cwd: str,
    run: Callable[..., Any],
    payload: dict[str, Any],
) -> tuple[bool, str | None]:
    """Evaluate stored pending context against the actual current tree.

    Refreshes the context for repaired HEADs (including repair/amend paths)
    so an unchanged broken tree blocks again. Returns ``(True, None)`` when
    no check is pending or the tree is allowed onward.
    """
    if (
        _load_pending_context(payload) is None
        and payload.get(REBASE_GATE_CAPTURE_KEY) is None
    ):
        return True, None
    pending = _load_pending_context(payload)
    stored_capture = payload.get(REBASE_GATE_CAPTURE_KEY)
    candidate = (
        stored_capture.get("candidate") if isinstance(stored_capture, dict) else None
    )
    repo_root = (
        str(pending.get("repository_root", ""))
        if pending is not None
        else str(candidate.get("repository_root", ""))
        if isinstance(candidate, dict)
        else cwd
    ) or cwd
    budget = GateWorkBudget(_DEFAULT_GATE_TIMEOUT_SECONDS)
    settings, warning = load_after_rebase_gate_settings(repo_root, budget)
    if warning is not None:
        _warn_gate(*warning)
        return True, None
    if settings is None:
        _warn_gate("could not validate project gate settings")
        return True, None
    if not settings.hook_command:
        clear_rebase_gate_state(payload)
        return True, None
    return _evaluate_pending_with_budget(cwd, run, payload, budget, settings)


def _evaluate_pending_with_budget(
    cwd: str,
    run: Callable[..., Any],
    payload: dict[str, Any],
    budget: GateWorkBudget,
    settings: GateSettings,
) -> tuple[bool, str | None]:
    """Recover any interrupted rebase, refresh repair paths, and run the gate."""
    stored_capture = payload.get(REBASE_GATE_CAPTURE_KEY)
    candidate = (
        stored_capture.get("candidate") if isinstance(stored_capture, dict) else None
    )
    try:
        if isinstance(candidate, dict):
            head, tree = _resolve_current_ids(cwd, run, budget)
            old_head = str(candidate.get("current_head", ""))
            if head == old_head:
                # The process stopped before the rebase changed the branch.
                _store_capture(payload, None)
                persist_checkpoint_payload(payload)
            else:
                upstream_tip = str(
                    (candidate.get("inputs") or [{}])[0].get("upstream_tip", "")
                )
                merge_base = _run_git(
                    run, ["git", "merge-base", upstream_tip, head], cwd, budget
                ).strip()
                if merge_base == upstream_tip:
                    paths = _collect_changed_paths(cwd, run, upstream_tip, head, budget)
                    refreshed = _update_context(
                        candidate,
                        str(candidate.get("repository_root", cwd)),
                        head,
                        tree,
                        paths,
                    )
                    merged = _merge_contexts(_load_pending_context(payload), refreshed)
                    if merged is not None:
                        _store_pending_context(payload, merged)
                        _store_capture(payload, None)
                        persist_checkpoint_payload(payload)
                else:
                    _warn_gate(
                        "could not confirm the interrupted rebase result; allowing publication",
                        f"current HEAD {head} does not contain captured upstream {upstream_tip}",
                    )

        pending = _load_pending_context(payload)
        if pending is None:
            return True, None
        head, tree = _resolve_current_ids(cwd, run, budget)
        context = pending
        if head != pending.get("current_head") or tree != pending.get("current_tree"):
            previous_head = str(pending.get("current_head", ""))
            if not previous_head:
                raise _GateDiscoveryError("pending context has no previous HEAD")
            repair_paths = _collect_changed_paths(cwd, run, previous_head, head, budget)
            context = _update_context(
                pending,
                str(pending.get("repository_root", "") or cwd),
                head,
                tree,
                repair_paths,
            )
            _store_pending_context(payload, context)
            persist_checkpoint_payload(payload)
        return _evaluate_context(
            payload,
            context,
            str(context.get("repository_root", cwd)),
            budget,
            settings,
        )
    except GateBudgetExhausted as exc:
        _warn_gate("gate budget expired during pending-context discovery", str(exc))
    except Exception as exc:  # noqa: BLE001 - discovery errors fail open
        _warn_gate("could not refresh pending rebase context", str(exc))
    return True, None
