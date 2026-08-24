"""Noninteractive agent operation runners."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import Any, Literal

from sase.ops.cli import add_operation_io_flags, load_request
from sase.ops.commands.common import OperationCommandResult, run_and_finish
from sase.ops.names import (
    AGENT_CLEANUP,
    AGENT_DRAIN,
    AGENT_PERSIST_DIRECTIVE,
    AGENT_REVERT,
)


def add_agent_operation_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register focused noninteractive agent operation commands."""
    cleanup = subparsers.add_parser(
        "persist-cleanup",
        help="Persist kill, dismiss, or save cleanup from a private request sidecar",
        description=(
            "Apply one JSON-shaped agent cleanup persistence spec. Identities "
            "and cleanup-plan details come from the private request sidecar."
        ),
    )
    add_operation_io_flags(cleanup)

    persist = subparsers.add_parser(
        "persist-directive",
        help="Persist an agent directive update from a private request sidecar",
        description=(
            "Apply one JSON-shaped agent-directive persistence spec. The "
            "artifacts directory is positional; mutation details come from "
            "the private request sidecar."
        ),
    )
    persist.add_argument(
        "artifacts_dir",
        help="Agent artifacts directory that owns the directive files",
    )
    add_operation_io_flags(persist)

    revert = subparsers.add_parser(
        "revert",
        help="Execute a previously previewed agent commit revert",
        description=(
            "Revert an agent's commits using identifiers from the command "
            "line and optional SHA/workspace details from the request sidecar."
        ),
    )
    revert.add_argument("name", help="Agent name whose commits should be reverted")
    add_operation_io_flags(revert)


def handle_agent_operation(args: argparse.Namespace) -> int:
    """Dispatch one focused agent operation command."""
    sub = getattr(args, "agent_subcommand", None)
    if sub == "drain":
        return run_and_finish(
            operation=AGENT_DRAIN,
            body=lambda: _run_drain(args),
            args=args,
            print_message=False,
        )
    if sub == "persist-directive":
        return run_and_finish(
            operation=AGENT_PERSIST_DIRECTIVE,
            body=lambda: _run_persist_directive(args),
            args=args,
        )
    if sub == "revert":
        return run_and_finish(
            operation=AGENT_REVERT,
            body=lambda: _run_revert(args),
            args=args,
        )
    if sub == "persist-cleanup":
        return run_and_finish(
            operation=AGENT_CLEANUP,
            body=lambda: _run_persist_cleanup(args),
            args=args,
        )
    return 2


def _run_drain(args: argparse.Namespace) -> OperationCommandResult:
    from sase.agents.cli_drain import run_agents_drain

    result = run_agents_drain(args)
    return OperationCommandResult(
        success=result.success,
        message=result.message,
        payload=result.payload,
        exit_code=result.exit_code,
    )


def _persist_directive_from_payload(
    payload: Mapping[str, Any],
    *,
    artifacts_dir: str,
) -> Any:
    """Build and apply one persist-directive spec from JSON-shaped payload."""
    from sase.ace.tui.actions.agents._directive_persistence import (
        persist_agent_directive_update,
    )

    spec = _spec_from_payload(payload, artifacts_dir=artifacts_dir)
    return persist_agent_directive_update(spec)


def _run_persist_directive(
    args: argparse.Namespace,
) -> tuple[bool, str, Mapping[str, Any]]:
    request = load_request(AGENT_PERSIST_DIRECTIVE, args, required=True)
    payload = dict(request.payload)
    updates = payload.get("updates")
    if isinstance(updates, list) and updates:
        results = []
        for item in updates:
            if not isinstance(item, dict):
                continue
            item_dir = str(item.get("artifacts_dir") or args.artifacts_dir)
            result = _persist_directive_from_payload(item, artifacts_dir=item_dir)
            results.append(
                {
                    "artifacts_dir": item_dir,
                    "meta_updated": result.meta_updated,
                    "ready_updated": result.ready_updated,
                    "tribe_updated": result.tribe_updated,
                    "waiting_updated": result.waiting_updated,
                }
            )
        return (
            True,
            f"Persisted {len(results)} agent directive update(s)",
            {"updates": results},
        )
    artifacts_dir = str(payload.get("artifacts_dir") or args.artifacts_dir)
    result = _persist_directive_from_payload(payload, artifacts_dir=artifacts_dir)
    return (
        True,
        f"Persisted agent directive in {artifacts_dir}",
        {
            "artifacts_dir": artifacts_dir,
            "meta_updated": result.meta_updated,
            "ready_updated": result.ready_updated,
            "tribe_updated": result.tribe_updated,
            "waiting_updated": result.waiting_updated,
        },
    )


def _spec_from_payload(payload: Mapping[str, Any], *, artifacts_dir: str) -> Any:
    from sase.ace.tui.actions.agents._directive_persistence import (
        AgentDirectivePersistenceSpec,
        AgentMetaPatch,
        AgentTribeStorePatch,
        ReadyMarkerPatch,
        wait_meta_patch_for_token,
        waiting_marker_patch_for_token,
    )

    meta_set = payload.get("meta_set")
    meta_remove = payload.get("meta_remove")
    meta_patch = None
    if isinstance(meta_set, dict) or isinstance(meta_remove, list):
        meta_patch = AgentMetaPatch(
            set_values=dict(meta_set) if isinstance(meta_set, dict) else {},
            remove_keys=tuple(str(item) for item in meta_remove)
            if isinstance(meta_remove, list)
            else (),
        )
    if payload.get("wait") and meta_patch is None:
        wait = payload["wait"] if isinstance(payload.get("wait"), dict) else {}
        meta_patch = wait_meta_patch_for_token(
            wait_names=tuple(wait.get("names") or ()),
            wait_beads=tuple(wait.get("beads") or ()),
            time_token=wait.get("time_token")
            if isinstance(wait.get("time_token"), str)
            else None,
            update_wait_runners=bool(wait.get("update_wait_runners", False)),
            wait_runners=wait.get("wait_runners"),
            update_wait_priority=bool(wait.get("update_wait_priority", False)),
            wait_priority=wait.get("wait_priority"),
        )
    waiting = None
    if isinstance(payload.get("waiting"), dict):
        waiting_payload = payload["waiting"]
        waiting = waiting_marker_patch_for_token(
            wait_names=tuple(waiting_payload.get("names") or ()),
            wait_beads=tuple(waiting_payload.get("beads") or ()),
            time_token=waiting_payload.get("time_token")
            if isinstance(waiting_payload.get("time_token"), str)
            else None,
            update_wait_runners=bool(waiting_payload.get("update_wait_runners", False)),
            wait_runners=waiting_payload.get("wait_runners"),
            update_wait_priority=bool(
                waiting_payload.get("update_wait_priority", False)
            ),
            wait_priority=waiting_payload.get("wait_priority"),
        )
    ready = None
    if isinstance(payload.get("ready"), dict):
        ready = ReadyMarkerPatch(
            resolved_deps=tuple(payload["ready"].get("resolved_deps") or ()),
            unwait=bool(payload["ready"].get("unwait", False)),
        )
    tribe = None
    if isinstance(payload.get("tribe"), dict) and payload["tribe"].get("identity"):
        identity = payload["tribe"]["identity"]
        tribe = AgentTribeStorePatch(
            identity=tuple(identity),
            tribe=payload["tribe"].get("tribe"),
        )
    return AgentDirectivePersistenceSpec(
        artifacts_dir=artifacts_dir,
        prompt_mutator=_prompt_mutator_from_spec(payload.get("prompt")),
        meta_patch=meta_patch,
        tribe_patch=tribe,
        waiting_marker=waiting,
        ready_marker=ready,
    )


def _prompt_mutator_from_spec(spec: object) -> Any:
    if not isinstance(spec, dict):
        return None
    kind = spec.get("kind")
    if kind == "set_name":
        from sase.xprompt.directive_edit import set_prompt_name

        name = str(spec.get("name") or "")
        return lambda prompt: set_prompt_name(prompt, name)
    if kind == "set_auto_mode":
        from sase.xprompt.directive_edit import set_prompt_auto_mode

        mode = spec.get("mode")
        return lambda prompt: set_prompt_auto_mode(prompt, mode)
    if kind == "set_wait":
        from sase.xprompt.directive_edit import PromptWaitDirective, set_prompt_wait

        wait = spec.get("wait")
        if not isinstance(wait, dict):
            return lambda prompt: set_prompt_wait(prompt, None)
        directive = PromptWaitDirective(
            agents=tuple(wait.get("agents") or ()),
            time_token=wait.get("time_token"),
            runners=wait.get("runners"),
            priority=wait.get("priority"),
            beads=tuple(wait.get("beads") or ()),
        )
        return lambda prompt: set_prompt_wait(prompt, directive)
    if kind == "set_tribe":
        from sase.xprompt.directive_edit import set_prompt_tribe

        tribe = spec.get("tribe")
        return lambda prompt: set_prompt_tribe(prompt, tribe)
    if kind == "set_clan_tribe":
        from sase.xprompt.directive_edit import set_prompt_clan_tribe

        tribe = spec.get("tribe")
        return lambda prompt: set_prompt_clan_tribe(prompt, tribe)
    return None


def _run_revert(args: argparse.Namespace) -> tuple[bool, str, Mapping[str, Any]]:
    from sase.ace.revert_agent_execute import (
        execute_agent_revert,
        execute_agents_revert,
    )

    request = load_request(AGENT_REVERT, args)
    payload = dict(request.payload)
    artifacts_dir = payload.get("artifacts_dir")
    preview = payload.get("preview")
    result: Any
    if payload.get("bulk"):
        result = execute_agents_revert(_bulk_preview_from_payload(payload, args.name))
    elif isinstance(preview, dict):
        result = execute_agent_revert(_single_preview_from_payload(preview, args.name))
    else:
        workspace = payload.get("workspace_dir")
        shas = payload.get("shas")
        result = execute_agent_revert(
            str(workspace) if isinstance(workspace, str) else "",
            tuple(str(item) for item in shas) if isinstance(shas, list) else None,
            agent_name=args.name,
            artifacts_dir=str(artifacts_dir)
            if isinstance(artifacts_dir, str)
            else None,
        )
    success = bool(getattr(result, "success", False))
    message = str(
        getattr(result, "message", "") or ("Reverted" if success else "Revert failed")
    )
    error = getattr(result, "error", None)
    if not success and error:
        message = str(error)
    return (
        success,
        message,
        {
            "name": args.name,
            "reverted_shas": list(getattr(result, "reverted_shas", ()) or ()),
            "error": None if success else message,
        },
    )


# The dead in-process kill/dismiss/save workers each hard-coded their own
# ``schedule_agents_refresh_source`` on failure so the optimistic UI update
# got a corrective reload -- and, for single-agent dismiss only, an extra
# off-thread notification-count refresh. The durable path applies the same
# payload out of process, so this table is what lets a persistence failure
# still trigger the same recovery effects instead of leaving stale
# optimistic state on screen. Keyed by ``transaction`` (not ``action``)
# because single-dismiss and bulk-dismiss shared an action but disagreed
# about the notification refresh.
_CLEANUP_ERROR_RECOVERY: Mapping[str, tuple[str, bool]] = {
    "single_kill": ("kill_error_recovery", False),
    "bulk_kill": ("kill_error_recovery", False),
    "single_dismiss": ("dismiss_error_recovery", True),
    "bulk_dismiss": ("dismiss_error_recovery", False),
    "save": ("mark_error_recovery", False),
}


def _apply_cleanup_payload_for_result(
    payload: Mapping[str, Any],
) -> tuple[bool, str, Mapping[str, Any]]:
    """Apply one cleanup payload and report the durable-proc result shape.

    Shared by ``sase agent persist-cleanup`` and the in-process test harnesses
    so both exercise the exact same persistence call and failure-recovery
    surface, rather than tests re-deriving it against a code path production
    does not run.
    """
    action = str(payload.get("action") or "cleanup")
    transaction = str(payload.get("transaction") or action)
    try:
        _apply_cleanup_payload(payload)
    except Exception as exc:
        refresh_source, refresh_notifications = _CLEANUP_ERROR_RECOVERY.get(
            transaction, (f"{action}_error_recovery", False)
        )
        return (
            False,
            f"{action.capitalize()} cleanup failed: {exc}",
            {
                "action": action,
                "notify": True,
                "refresh_notifications": refresh_notifications,
                "schedule_agents_refresh_source": refresh_source,
                "severity": "error",
            },
        )
    return (
        True,
        str(payload.get("message") or f"Persisted {action}"),
        {
            "action": action,
            "notify": bool(payload.get("notify", False)),
            "refresh_notifications": bool(payload.get("refresh_notifications", False)),
            "schedule_agents_refresh_source": payload.get(
                "schedule_agents_refresh_source"
            ),
            "severity": payload.get("severity"),
        },
    )


def _run_persist_cleanup(
    args: argparse.Namespace,
) -> tuple[bool, str, Mapping[str, Any]]:
    request = load_request(AGENT_CLEANUP, args, required=True)
    return _apply_cleanup_payload_for_result(dict(request.payload))


def _apply_cleanup_payload(payload: Mapping[str, Any]) -> None:
    from sase.ace.tui.actions.cleanup_payload import (
        agent_from_json,
        agents_from_json,
        identities_from_json,
    )

    transaction = str(payload.get("transaction") or "")
    dismissed_snapshot = identities_from_json(payload.get("dismissed_identities"))
    added = identities_from_json(payload.get("added_identities"))
    agents_with_children = agents_from_json(payload.get("agents_with_children"))
    cleanup_plan = _cleanup_plan_from_payload(payload.get("cleanup_plan"))
    if cleanup_plan is not None:
        from sase.monitor.cleanup import execute_monitor_stop_intents

        execute_monitor_stop_intents(cleanup_plan)
    recent_group = _recent_group_from_payload(payload.get("recent_group"))
    if transaction == "single_kill":
        from sase.ace.tui.actions.agents._kill_transactions import (
            persist_single_kill_transaction,
        )

        agent_payload = payload.get("agent")
        if isinstance(agent_payload, dict):
            persist_single_kill_transaction(
                agent_from_json(agent_payload),
                str(payload.get("kind") or "running"),  # type: ignore[arg-type]
                agents_with_children,
                dismissed_snapshot,
                cleanup_plan,
                agents_from_json(payload.get("related_agents")),
            )
        return
    if transaction == "bulk_kill":
        from sase.ace.tui.actions.agents._kill_persistence import BulkKillItem
        from sase.ace.tui.actions.agents._kill_transactions import (
            persist_bulk_kill_transaction,
        )

        kill_items = []
        for item in payload.get("kill_items") or []:
            if not isinstance(item, dict) or not isinstance(item.get("agent"), dict):
                continue
            kill_items.append(
                BulkKillItem(
                    agent=agent_from_json(item["agent"]),
                    kind=str(item.get("kind") or "running"),  # type: ignore[arg-type]
                    identities=identities_from_json(item.get("identities")),
                )
            )
        persist_bulk_kill_transaction(
            kill_items,
            agents_from_json(payload.get("dismissable")),
            dismissed_snapshot,
            agents_with_children,
            cleanup_plan,
            recent_group,
        )
        return
    if transaction == "single_dismiss":
        from sase.ace.tui.actions.agents._dismissing import (
            persist_single_dismiss_transaction,
        )

        agent_payload = payload.get("agent")
        if isinstance(agent_payload, dict):
            persist_single_dismiss_transaction(
                agent_from_json(agent_payload),
                dismissed_snapshot,
                agents_with_children,
                cleanup_plan,
                added,
                recent_group,
            )
        return
    if transaction == "bulk_dismiss":
        from sase.ace.tui.actions.agents._dismissing import (
            persist_bulk_dismiss_transaction,
        )

        persist_bulk_dismiss_transaction(
            agents_from_json(payload.get("agents")),
            dismissed_snapshot,
            agents_with_children,
            cleanup_plan,
            added,
            recent_group,
        )
        return
    if transaction == "save":
        from sase.ace.tui.actions.agents._marking import (
            persist_marked_agent_group_save,
        )

        group = _recent_group_from_payload(payload.get("group"))
        if group is not None:
            persist_marked_agent_group_save(
                agents_from_json(payload.get("agents")),
                dismissed_snapshot,
                added,
                group,
                payload.get("group_name")
                if isinstance(payload.get("group_name"), str)
                else None,
            )
        return
    if dismissed_snapshot:
        from sase.ace.dismissed_agents import save_dismissed_agents
        from sase.core.agent_artifact_index_lifecycle import (
            sync_dismissed_agent_artifact_index,
        )

        if save_dismissed_agents(dismissed_snapshot):
            sync_dismissed_agent_artifact_index(dismissed_snapshot)
    if cleanup_plan is not None:
        from sase.ace.tui.actions.agents._dismiss_persistence import (
            persist_cleanup_side_effect_intents,
        )

        persist_cleanup_side_effect_intents(cleanup_plan, agents_with_children)


def _cleanup_plan_from_payload(raw: object) -> Any:
    if not isinstance(raw, dict):
        return None
    from sase.core.agent_cleanup_wire import cleanup_plan_from_dict

    return cleanup_plan_from_dict(raw)


def _recent_group_from_payload(raw: object) -> Any:
    if not isinstance(raw, dict):
        return None
    from sase.core.agent_group_archive_wire import saved_agent_group_from_dict

    return saved_agent_group_from_dict(raw)


def serialize_revert_preview(preview: Any) -> dict[str, Any]:
    """Serialize a single-agent revert preview for the durable request."""
    return {
        "agent_name": preview.agent_name,
        "commits": [_serialize_commit(item) for item in preview.commits],
        "repos": [_serialize_repo(item) for item in preview.repos],
        "scope": preview.scope,
        "workspace_dir": preview.workspace_dir,
    }


def serialize_bulk_revert_preview(preview: Any) -> dict[str, Any]:
    """Serialize a bulk revert preview for the durable request."""
    return {
        "bulk": True,
        "commits": [_serialize_commit(item) for item in preview.commits],
        "matched_target_names": list(preview.matched_target_names),
        "repos": [_serialize_repo(item) for item in preview.repos],
        "targets": [
            {
                "agent_name": item.agent_name,
                "artifacts_dir": item.artifacts_dir,
                "display_name": item.display_name,
                "family_base": item.family_base,
                "workspace_dir": item.workspace_dir,
            }
            for item in preview.targets
        ],
        "workspace_dir": preview.workspace_dir,
    }


def _serialize_commit(item: Any) -> dict[str, Any]:
    return {
        "commit_agent": item.agent_tag,
        "full_sha": item.full_sha,
        "sha": item.sha,
        "subject": item.subject,
    }


def _serialize_repo(item: Any) -> dict[str, Any]:
    return {
        "blocked_reason": item.blocked_reason,
        "commits": [_serialize_commit(commit) for commit in item.commits],
        "discard_local_changes": item.discard_local_changes,
        "is_primary": item.is_primary,
        "repo_kind": item.repo_kind,
        "repo_label": item.repo_label,
        "source_agent_names": list(item.source_agent_names),
        "workspace_dir": item.workspace_dir,
    }


def _commit_from_payload(item: Mapping[str, Any], name: str) -> Any:
    from sase.ace.revert_agent_models import RevertCommit

    return RevertCommit(
        sha=str(item.get("sha", "")),
        full_sha=str(item.get("full_sha") or item.get("sha", "")),
        subject=str(item.get("subject", "")),
        agent_tag=str(item.get("commit_agent") or item.get("agent_tag") or name),
    )


def _repo_kind_from_payload(raw: object) -> Literal["linked", "external"]:
    if raw == "external":
        return "external"
    return "linked"


def _repos_from_payload(raw: object, name: str) -> tuple[Any, ...]:
    from sase.ace.revert_agent_models import RepoRevertPlan

    if not isinstance(raw, list):
        return ()
    return tuple(
        RepoRevertPlan(
            repo_label=str(item.get("repo_label") or "primary"),
            workspace_dir=str(item.get("workspace_dir") or ""),
            is_primary=bool(item.get("is_primary", False)),
            commits=tuple(
                _commit_from_payload(commit, name)
                for commit in item.get("commits") or []
                if isinstance(commit, dict)
            ),
            blocked_reason=item.get("blocked_reason"),
            repo_kind=_repo_kind_from_payload(item.get("repo_kind")),
            discard_local_changes=bool(item.get("discard_local_changes", False)),
            source_agent_names=tuple(item.get("source_agent_names") or ()),
        )
        for item in raw
        if isinstance(item, dict)
    )


def _single_preview_from_payload(preview: Mapping[str, Any], name: str) -> Any:
    from sase.ace.revert_agent_models import RevertPreview

    return RevertPreview(
        agent_name=str(preview.get("agent_name") or name),
        scope=str(preview.get("scope") or "agent"),
        workspace_dir=str(preview.get("workspace_dir") or ""),
        commits=tuple(
            _commit_from_payload(item, name)
            for item in preview.get("commits") or []
            if isinstance(item, dict)
        ),
        repos=_repos_from_payload(preview.get("repos"), name),
    )


def _bulk_preview_from_payload(payload: Mapping[str, Any], name: str) -> Any:
    from sase.ace.revert_agent_models import BulkRevertPreview, RevertTarget

    targets = tuple(
        RevertTarget(
            agent_name=str(item.get("agent_name") or name),
            display_name=str(
                item.get("display_name") or item.get("agent_name") or name
            ),
            workspace_dir=str(item.get("workspace_dir") or ""),
            family_base=item.get("family_base"),
            artifacts_dir=item.get("artifacts_dir"),
        )
        for item in payload.get("targets") or []
        if isinstance(item, dict)
    )
    return BulkRevertPreview(
        workspace_dir=str(payload.get("workspace_dir") or ""),
        targets=targets,
        commits=tuple(
            _commit_from_payload(item, name)
            for item in payload.get("commits") or []
            if isinstance(item, dict)
        ),
        repos=_repos_from_payload(payload.get("repos"), name),
        matched_target_names=tuple(payload.get("matched_target_names") or ()),
    )


__all__ = ["add_agent_operation_parsers", "handle_agent_operation"]
