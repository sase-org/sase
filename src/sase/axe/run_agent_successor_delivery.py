"""Detached staged-successor delivery."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sase.axe._run_agent_successor_shared import read_successor_json
from sase.axe.run_agent_successor_types import (
    STAGED_SUCCESSOR_ID_ENV,
    STAGED_SUCCESSOR_ORIGIN_DIR_ENV,
    SuccessorDeliveryResult,
)


def mark_staged_successor_started(
    origin_artifacts_dir: str,
    staged_id: str,
) -> bool:
    """Record provider-start evidence for a previously prepared successor."""
    from sase.agent.staged_handoff import (
        acquire_adoption_lock,
        read_staged_successor,
        update_staged_successor_locked,
    )

    with acquire_adoption_lock(Path(origin_artifacts_dir)):
        record = read_staged_successor(origin_artifacts_dir, staged_id=staged_id)
        if record is None:
            return False
        if record["delivery_state"] in {"started", "terminal"}:
            return True
        update_staged_successor_locked(
            origin_artifacts_dir,
            staged_id,
            delivery_state="started",
        )
        return True


def mark_detached_successor_started_from_environment() -> bool:
    """Consume detached-successor provenance and mark it before provider work."""
    origin = os.environ.pop(STAGED_SUCCESSOR_ORIGIN_DIR_ENV, None)
    staged_id = os.environ.pop(STAGED_SUCCESSOR_ID_ENV, None)
    if not isinstance(origin, str) or not origin:
        return False
    if not isinstance(staged_id, str) or not staged_id:
        return False
    if not mark_staged_successor_started(origin, staged_id):
        raise RuntimeError("detached staged successor identity is missing")
    return True


def _successor_destination_observation(
    record: dict[str, Any],
) -> tuple[str, int | None, str | None]:
    """Inspect only durable metadata for an existing successor destination."""
    from sase.agent.process_tree import process_is_running
    from sase.core.process_identity import process_identity_matches

    successor = record["successor"]
    artifacts_dir = Path(successor["artifacts_dir"])
    if not artifacts_dir.exists():
        return "absent", None, None
    meta = read_successor_json(artifacts_dir / "agent_meta.json")
    if meta is None:
        return (
            "unknown",
            None,
            "successor artifacts exist without readable agent metadata",
        )
    if (
        meta.get("name") != successor["agent_name"]
        or meta.get("staged_handoff_id") != record["staged_id"]
        or meta.get("staged_successor_launch_id") != successor["launch_identity"]
    ):
        return (
            "unknown",
            None,
            "successor artifacts do not match the persisted identity",
        )
    if (artifacts_dir / "done.json").is_file():
        return "terminal", None, None
    pid = meta.get("pid")
    if type(pid) is not int or pid <= 0:
        return "created", None, None
    identity = meta.get("process_identity")
    if process_is_running(pid) and process_identity_matches(pid, identity):
        return "live", pid, None
    return "dead", pid, None


def deliver_staged_successor_detached(
    origin_artifacts_dir: str,
    staged_id: str,
) -> SuccessorDeliveryResult:
    """Launch a recorded successor once through the normal detached runner path.

    The submitted marker is written before invoking the launcher. If the
    runner dies in that window, a later caller observes the same identity and
    holds for evidence instead of submitting a second provider turn.
    """
    from dataclasses import asdict

    from sase.agent.staged_handoff import (
        acquire_adoption_lock,
        read_staged_successor,
        update_staged_successor_locked,
    )

    origin = Path(origin_artifacts_dir)
    with acquire_adoption_lock(origin):
        record = read_staged_successor(str(origin), staged_id=staged_id)
        if record is None:
            return SuccessorDeliveryResult(
                "held", "", "", reason="staged successor identity is missing"
            )
        successor = record["successor"]
        agent_name = successor["agent_name"]
        artifacts_dir = successor["artifacts_dir"]
        observed, pid, reason = _successor_destination_observation(record)
        if observed == "terminal":
            if record["delivery_state"] != "terminal":
                update_staged_successor_locked(
                    str(origin), staged_id, delivery_state="terminal"
                )
            return SuccessorDeliveryResult("terminal", agent_name, artifacts_dir)
        if observed == "live":
            return SuccessorDeliveryResult("owned", agent_name, artifacts_dir, pid=pid)
        if observed == "unknown":
            return SuccessorDeliveryResult(
                "held", agent_name, artifacts_dir, reason=reason
            )
        if record["delivery_state"] in {"submitted", "started"}:
            return SuccessorDeliveryResult(
                "held",
                agent_name,
                artifacts_dir,
                pid=pid,
                reason=(
                    "successor launch was already submitted but no live or terminal "
                    "destination can be proven"
                ),
            )

        if observed == "dead" and record["delivery_state"] in {
            "prepared",
            "created",
        }:
            # The originating runner made the child artifacts, but no provider
            # start was recorded. Reuse that exact timestamp and directory.
            if record["delivery_state"] == "prepared":
                record = update_staged_successor_locked(
                    str(origin), staged_id, delivery_state="created"
                )
                successor = record["successor"]
        elif observed == "created":
            pass
        elif observed == "absent":
            if record["delivery_state"] != "prepared":
                return SuccessorDeliveryResult(
                    "held",
                    agent_name,
                    artifacts_dir,
                    reason="successor artifacts disappeared after creation",
                )
            source_meta = read_successor_json(origin / "agent_meta.json")
            if source_meta is None:
                return SuccessorDeliveryResult(
                    "held",
                    agent_name,
                    artifacts_dir,
                    reason="origin agent metadata is unavailable",
                )
            from sase.axe.run_agent_helpers import create_followup_artifacts
            from sase.axe.run_agent_exec_plan_artifacts import (
                store_followup_prompt_artifact,
            )

            try:
                creation_meta = dict(source_meta)
                followup_model = successor.get("followup_model")
                if isinstance(followup_model, dict):
                    model_meta = followup_model.get("meta")
                    if (
                        isinstance(model_meta, list)
                        and len(model_meta) == 2
                        and all(
                            value is None or isinstance(value, str)
                            for value in model_meta
                        )
                        and isinstance(model_meta[1], str)
                    ):
                        creation_meta["model"] = model_meta[1]
                        if model_meta[0]:
                            creation_meta["llm_provider"] = model_meta[0]
                        model_alias = followup_model.get("model_alias")
                        model_alias_trail = followup_model.get("model_alias_trail")
                        model_alias_origin = followup_model.get("model_alias_origin")
                        if isinstance(model_alias, str) and model_alias:
                            creation_meta["model_alias"] = model_alias
                        else:
                            creation_meta.pop("model_alias", None)
                        if isinstance(model_alias_trail, list) and model_alias_trail:
                            creation_meta["model_alias_trail"] = model_alias_trail
                        else:
                            creation_meta.pop("model_alias_trail", None)
                        if isinstance(model_alias_origin, str) and model_alias_origin:
                            creation_meta["model_alias_origin"] = model_alias_origin
                        else:
                            creation_meta.pop("model_alias_origin", None)
                created = create_followup_artifacts(
                    successor["project_name"],
                    creation_meta,
                    successor["role_suffix"],
                    successor["origin_artifacts_timestamp"],
                    workspace_num=successor.get("workspace_num"),
                    agent_name_override=agent_name,
                    workflow_name=successor.get("workflow_name"),
                    agent_session_role=successor.get("agent_session_role"),
                    relationships=successor["relationships"],
                    stamp_creating_process=False,
                    prev_artifacts_dir=str(origin),
                    timestamp=successor["launch_timestamp"],
                )
                if str(Path(created)) != str(Path(artifacts_dir)):
                    raise RuntimeError(
                        "created successor artifacts do not match the persisted identity"
                    )
                prompt = _read_staged_launch_prompt(successor)
                store_followup_prompt_artifact(
                    created,
                    prompt,
                    label=successor.get("prompt_artifact_label") or "Piped prompt",
                )
            except Exception as exc:  # noqa: BLE001 - keep the stage recoverable.
                return SuccessorDeliveryResult(
                    "held",
                    agent_name,
                    artifacts_dir,
                    reason=f"successor preparation failed: {type(exc).__name__}: {exc}",
                )
            record = update_staged_successor_locked(
                str(origin), staged_id, delivery_state="created"
            )
            successor = record["successor"]
        else:
            return SuccessorDeliveryResult(
                "held",
                agent_name,
                artifacts_dir,
                reason="successor destination state is unknown",
            )

        # A created-but-not-submitted directory may still be owned by the
        # originating runner. Do not launch while that process is live.
        source_meta = read_successor_json(origin / "agent_meta.json") or {}
        origin_pid = source_meta.get("pid")
        origin_identity = source_meta.get("process_identity")
        if type(origin_pid) is int and origin_pid > 0:
            from sase.agent.process_tree import process_is_running
            from sase.core.process_identity import process_identity_matches

            if process_is_running(origin_pid) and process_identity_matches(
                origin_pid, origin_identity
            ):
                return SuccessorDeliveryResult(
                    "held",
                    agent_name,
                    artifacts_dir,
                    reason="originating runner is still live and may own the continuation",
                )

        record = update_staged_successor_locked(
            str(origin), staged_id, delivery_state="submitted"
        )
        successor = record["successor"]
        try:
            prompt = _read_staged_launch_prompt(successor)
            vcs_ref_raw = successor.get("vcs_ref")
            vcs_ref: tuple[str, str] | None = None
            if isinstance(vcs_ref_raw, list) and len(vcs_ref_raw) == 2:
                vcs_ref = (str(vcs_ref_raw[0]), str(vcs_ref_raw[1]))
            extra_env = {
                STAGED_SUCCESSOR_ORIGIN_DIR_ENV: str(origin),
                STAGED_SUCCESSOR_ID_ENV: staged_id,
            }
            attach_data = successor.get("attach_plan")
            if isinstance(attach_data, dict):
                from sase.agent._agent_session_attach_types import (
                    AgentSessionAttachDirective,
                    AgentSessionAttachLaunchPlan,
                )
                from sase.agent.detached_child import spawn_agent_session_successor

                attach_plan = AgentSessionAttachLaunchPlan(**attach_data)
                directive = AgentSessionAttachDirective(
                    parent=attach_plan.parent_arg,
                    suffix=attach_plan.suffix_arg,
                )
                spawn_result = spawn_agent_session_successor(
                    directive,
                    project_name=successor["project_name"],
                    project_file=successor["project_file"],
                    prompt=prompt,
                    workspace_dir=successor["workspace_dir"],
                    workspace_num=successor.get("workspace_num") or 0,
                    transfer_from_pid=None,
                    cl_name=successor["cl_name"],
                    agent_session_role=successor.get("agent_session_role"),
                    update_target=successor.get("update_target") or "",
                    history_sort_key=successor.get("history_sort_key") or "",
                    is_home_mode=bool(successor.get("is_home_mode")),
                    vcs_ref=vcs_ref,
                    timestamp=successor["launch_timestamp"],
                    extra_env=extra_env,
                    resolve_plan=lambda *_args, **_kwargs: attach_plan,
                )
            else:
                from sase.agent.detached_child import spawn_detached_child

                spawn_result = spawn_detached_child(
                    project_name=successor["project_name"],
                    project_file=successor["project_file"],
                    prompt=prompt,
                    workspace_dir=successor["workspace_dir"],
                    workspace_num=successor.get("workspace_num") or 0,
                    cl_name=successor["cl_name"],
                    transfer_from_pid=None,
                    update_target=successor.get("update_target") or "",
                    history_sort_key=successor.get("history_sort_key") or "",
                    is_home_mode=bool(successor.get("is_home_mode")),
                    vcs_ref=vcs_ref,
                    timestamp=successor["launch_timestamp"],
                    extra_env={
                        **extra_env,
                        "SASE_AGENT_PLANNED_NAME": agent_name,
                    },
                )
        except Exception as exc:  # noqa: BLE001 - submitted is deliberately sticky.
            return SuccessorDeliveryResult(
                "held",
                agent_name,
                artifacts_dir,
                reason=f"successor launch outcome is uncertain: {type(exc).__name__}: {exc}",
            )
        update_staged_successor_locked(
            str(origin),
            staged_id,
            delivery_state="submitted",
            updates={"launch_pid": int(spawn_result.pid)},
        )
        return SuccessorDeliveryResult(
            "submitted",
            agent_name,
            artifacts_dir,
            pid=int(spawn_result.pid),
        )


def _read_staged_launch_prompt(successor: dict[str, Any]) -> str:
    """Read the exact prompt destined for a detached successor launch."""
    prompt_ref = successor.get("launch_prompt_ref") or successor.get("prompt_ref")
    if not isinstance(prompt_ref, str) or not prompt_ref:
        raise RuntimeError("persisted staged successor launch prompt is missing")
    prompt = Path(prompt_ref).read_text(encoding="utf-8")
    expected = successor.get("launch_prompt_digest")
    if expected is not None:
        from sase.agent.staged_handoff import successor_prompt_digest

        if expected != successor_prompt_digest(prompt):
            raise RuntimeError(
                "persisted staged successor launch prompt digest differs"
            )
    return prompt


__all__ = [
    "deliver_staged_successor_detached",
    "mark_detached_successor_started_from_environment",
    "mark_staged_successor_started",
]
