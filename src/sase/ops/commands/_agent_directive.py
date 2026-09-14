"""Agent directive persistence operation helpers."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import Any

from sase.ops.cli import load_request
from sase.ops.names import AGENT_PERSIST_DIRECTIVE


def persist_directive_from_payload(
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


def run_persist_directive(
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
            result = persist_directive_from_payload(item, artifacts_dir=item_dir)
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
    result = persist_directive_from_payload(payload, artifacts_dir=artifacts_dir)
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
            update_wait_runners=bool(
                wait.get(
                    "update_queue_capacity", wait.get("update_wait_runners", False)
                )
            ),
            wait_runners=wait.get("queue_capacity", wait.get("wait_runners")),
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
            update_wait_runners=bool(
                waiting_payload.get(
                    "update_queue_capacity",
                    waiting_payload.get("update_wait_runners", False),
                )
            ),
            wait_runners=waiting_payload.get(
                "queue_capacity", waiting_payload.get("wait_runners")
            ),
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


def _capacity_from_payload(payload: Mapping[str, Any]) -> int | None:
    """Read canonical `capacity` or persisted `runners` from a mutator spec."""
    from sase.xprompt.queue_directive import validate_queue_capacity

    if payload.get("capacity") is not None:
        return validate_queue_capacity(payload["capacity"])
    if payload.get("runners") is not None:
        return validate_queue_capacity(payload["runners"])
    return None


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
        from sase.xprompt.directive_edit import (
            PromptWaitDirective,
            set_prompt_wait_and_queue,
        )

        wait = spec.get("wait")
        if not isinstance(wait, dict):
            return lambda prompt: set_prompt_wait_and_queue(prompt, None)
        directive = PromptWaitDirective(
            agents=tuple(wait.get("agents") or ()),
            time_token=wait.get("time_token"),
            capacity=_capacity_from_payload(wait),
            priority=wait.get("priority"),
            weight=wait.get("weight"),
            beads=tuple(wait.get("beads") or ()),
        )
        return lambda prompt: set_prompt_wait_and_queue(prompt, directive)
    if kind == "set_queue":
        from sase.xprompt.directive_edit import set_prompt_queue

        return lambda prompt: set_prompt_queue(
            prompt,
            capacity=_capacity_from_payload(spec),
            priority=spec.get("priority"),
            weight=spec.get("weight"),
        )
    if kind == "set_tribe":
        from sase.xprompt.directive_edit import set_prompt_tribe

        tribe = spec.get("tribe")
        return lambda prompt: set_prompt_tribe(prompt, tribe)
    if kind == "set_clan_tribe":
        from sase.xprompt.directive_edit import set_prompt_clan_tribe

        tribe = spec.get("tribe")
        return lambda prompt: set_prompt_clan_tribe(prompt, tribe)
    return None


__all__ = ["persist_directive_from_payload", "run_persist_directive"]
