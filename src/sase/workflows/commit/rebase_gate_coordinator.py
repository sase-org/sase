"""Narrow gate coordinator wiring the after-rebase check into git dispatch.

Phase ``publication`` of the rebased-stitch gate epic. This module owns git
fact collection (immutable IDs plus the NUL-safe changed-path union) and the
pending-context lifecycle persisted on the checkpoint payload. Generic
bounded execution stays in :mod:`sase.workflows.commit.rebase_gate_runner`
and policy stays in Rust (:mod:`sase.core.rebase_gate`); the dispatch mixin
only calls these helpers.

All helpers are best-effort and fail open: gate problems never raise, so a
checker or git failure can only skip the check, never block publication.
Only cancellation propagates, and pending state is stored before the runner
starts so cancellation cannot lose a required check.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Literal, cast

from sase.core.rebase_gate import (
    ChangedPathWire,
    ChangeKind,
    ContextWire,
    RebaseFactsWire,
)
from sase.workflows.commit.rebase_gate_runner import RebaseGateOutcome

GateOutcome = Literal["applied", "conflict"]

REBASE_GATE_PENDING_KEY = "_rebase_gate_pending"
REBASE_GATE_BLOCKED_KEY = "_rebase_gate_blocked"

_GIT_TIMEOUT_SECONDS = 60

__all__ = [
    "REBASE_GATE_BLOCKED_KEY",
    "REBASE_GATE_PENDING_KEY",
    "begin_rebase_gate_capture",
    "complete_rebase_gate_check",
    "is_gate_blocked",
    "run_pending_rebase_gate",
    "stash_rebase_gate_for_conflict",
]


def _hook_configured_for_path(path: str) -> bool:
    """Return whether *path*'s project layer sets a non-empty after hook."""
    from sase.config.core import load_merged_config_for_local_path
    from sase.workflows.commit.hook_utils import local_config_path_for_repo_root

    try:
        config = load_merged_config_for_local_path(
            local_config_path_for_repo_root(path)
        )
    except Exception:
        return False
    hooks = config.get("commit_hooks", {})
    if not isinstance(hooks, dict):
        return False
    hook = hooks.get("after_rebase", "")
    return isinstance(hook, str) and bool(hook.strip())


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


def is_gate_blocked(payload: Mapping[str, Any]) -> bool:
    """Return whether *payload* carries an explicit gate finding."""
    return payload.get(REBASE_GATE_BLOCKED_KEY) is True


def _run_git(run: Callable[..., Any], args: list[str], cwd: str) -> str | None:
    try:
        out = run(args, cwd, timeout=_GIT_TIMEOUT_SECONDS)
    except Exception:
        return None
    if out is None or not getattr(out, "success", False):
        return None
    text = getattr(out, "stdout", "") or ""
    stripped = text.strip()
    return stripped or None


def begin_rebase_gate_capture(
    cwd: str,
    run: Callable[..., Any],
    upstream_ref: str,
) -> dict[str, str] | None:
    """Capture immutable git IDs before a rebase that may combine work.

    Returns ``None`` without running git when no after hook is configured.
    """
    if not _hook_configured_for_path(cwd):
        return None
    repo_root = _run_git(run, ["git", "rev-parse", "--show-toplevel"], cwd)
    old_head = _run_git(run, ["git", "rev-parse", "HEAD"], cwd)
    upstream_tip = _run_git(run, ["git", "rev-parse", upstream_ref], cwd)
    if repo_root is None or old_head is None or upstream_tip is None:
        return None
    merge_base = _run_git(run, ["git", "merge-base", old_head, upstream_tip], cwd)
    if merge_base is None:
        return None
    return {
        "repository_root": repo_root,
        "old_head": old_head,
        "upstream_tip": upstream_tip,
        "merge_base": merge_base,
    }


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
) -> list[ChangedPathWire]:
    """Return the NUL-safe ``base..head`` path union with rename metadata."""
    try:
        out = run(
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
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return []
    if out is None or not getattr(out, "success", False):
        return []
    raw = getattr(out, "stdout", "") or ""
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
            continue
        if kind in ("renamed", "copied"):
            if index + 1 >= len(parts):
                break
            old_path = parts[index]
            new_path = parts[index + 1]
            index += 2
            if not old_path or not new_path:
                continue
            changes.append({"path": new_path, "kind": kind, "old_path": old_path})
        else:
            if index >= len(parts):
                break
            path = parts[index]
            index += 1
            if not path:
                continue
            changes.append({"path": path, "kind": kind})
    return changes


def _resolve_current_ids(
    cwd: str, run: Callable[..., Any]
) -> tuple[str | None, str | None]:
    head = _run_git(run, ["git", "rev-parse", "HEAD"], cwd)
    tree = _run_git(run, ["git", "rev-parse", "HEAD^{tree}"], cwd)
    return head, tree


def _build_context(
    capture: Mapping[str, str],
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
    except Exception:
        return None
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
    except Exception:
        return incoming if incoming is not None else existing
    if merged is None:
        return None
    return cast(dict[str, Any], merged)


def _evaluate_context(
    payload: dict[str, Any], context: dict[str, Any], repo_root: str
) -> tuple[bool, str | None]:
    """Run the gate for *context*; True means the push may proceed."""
    from sase.workflows.commit.rebase_gate_runner import run_after_rebase_gate

    try:
        outcome = run_after_rebase_gate(cast(ContextWire, context), repo_root)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        # Cancellation stays cancellation; anything else fails open while
        # keeping the stored pending context for the next attempt.
        import asyncio

        try:
            if isinstance(asyncio.current_task(), asyncio.Task):
                raise
        except RuntimeError:
            pass
        return True, None
    decision = outcome.decision
    if _verdict_of(outcome) == "block":
        head = str(context.get("current_head", ""))
        tree = str(context.get("current_tree", ""))
        payload[REBASE_GATE_BLOCKED_KEY] = True
        return False, _format_gate_block_message(decision, head=head, tree=tree)
    _store_pending_context(payload, None)
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
    capture: dict[str, str] | None,
    *,
    outcome: GateOutcome = "applied",
) -> tuple[bool, str | None]:
    """Build, persist, and evaluate the gate context for a finished rebase.

    Returns ``(True, None)`` when the push may proceed and
    ``(False, message)`` for a confirmed finding. Never raises for gate
    errors; cancellation propagates with pending state already stored.
    """
    if capture is None:
        return True, None
    head, tree = _resolve_current_ids(cwd, run)
    if head is None or tree is None:
        return True, None
    local_changes = _collect_changed_paths(
        cwd, run, capture["merge_base"], capture["old_head"]
    )
    upstream_changes = _collect_changed_paths(
        cwd, run, capture["merge_base"], capture["upstream_tip"]
    )
    incoming = _build_context(
        capture, outcome, head, tree, local_changes, upstream_changes
    )
    if incoming is None:
        return True, None
    merged = _merge_contexts(_load_pending_context(payload), incoming)
    if merged is None:
        return True, None
    _store_pending_context(payload, merged)
    return _evaluate_context(payload, merged, capture["repository_root"])


def stash_rebase_gate_for_conflict(
    cwd: str,
    run: Callable[..., Any],
    payload: dict[str, Any],
    capture: dict[str, str] | None,
) -> None:
    """Retain pending context when a rebase stops for manual resolution.

    Uses the pre-rebase IDs so a later resume can refresh the context for
    the repaired HEAD; manual resolution cannot bypass the check.
    """
    if capture is None:
        return
    try:
        tree = _run_git(
            run, ["git", "rev-parse", f"{capture['old_head']}^{{tree}}"], cwd
        )
        if tree is None:
            return
        local_changes = _collect_changed_paths(
            cwd, run, capture["merge_base"], capture["old_head"]
        )
        upstream_changes = _collect_changed_paths(
            cwd, run, capture["merge_base"], capture["upstream_tip"]
        )
        incoming = _build_context(
            capture,
            "conflict",
            capture["old_head"],
            tree,
            local_changes,
            upstream_changes,
        )
        if incoming is None:
            return
        merged = _merge_contexts(_load_pending_context(payload), incoming)
        if merged is not None:
            _store_pending_context(payload, merged)
    except Exception:
        return


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
    pending = _load_pending_context(payload)
    if pending is None:
        return True, None
    repo_root = str(pending.get("repository_root", "")) or cwd
    if not _hook_configured_for_path(repo_root):
        _store_pending_context(payload, None)
        return True, None
    head, tree = _resolve_current_ids(cwd, run)
    if head is None or tree is None:
        return True, None
    context = pending
    if head != pending.get("current_head") or tree != pending.get("current_tree"):
        repair_paths = _collect_changed_paths(
            cwd, run, str(pending.get("current_head", "")), head
        )
        if not pending.get("current_head"):
            return True, None
        try:
            from sase.core.rebase_gate import (
                ContextUpdateWire,
                update_rebase_gate_context,
            )

            update: ContextUpdateWire = {
                "schema_version": 1,
                "repository_root": str(pending.get("repository_root", "")),
                "current_head": head,
                "current_tree": tree,
                "changed_paths": repair_paths,
            }
            refreshed = update_rebase_gate_context(cast(ContextWire, pending), update)
        except Exception:
            return True, None
        context = cast(dict[str, Any], refreshed)
        _store_pending_context(payload, context)
    return _evaluate_context(payload, context, repo_root)
