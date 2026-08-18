"""Plan a ``sase agent restart`` without mutating anything.

Planning is read-only on purpose: every refusal — a missing prompt, a fan-out,
a container name, an unusable identity — is discovered here, before execution
kills the old row.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.agent._restart_preview import build_restart_preview
from sase.agent._restart_reads import optional_str, read_json_dict, read_raw_prompt
from sase.agent._restart_types import (
    AgentRestartError,
    AgentRestartPlan,
    NameReuseSource,
)
from sase.agent.force_reuse_launch import ForceReuseLaunchPlan


def plan_agent_restart(
    name: str,
    *,
    model_override: str | None = None,
) -> AgentRestartPlan:
    """Read the named agent and build a restart plan, or raise."""
    from sase.agent.force_reuse_launch import plan_force_reuse_launch
    from sase.agent.names import (
        find_named_agent,
        lookup_registered_name,
        preview_agent_name_wipe,
    )
    from sase.agent.relaunch_prompt import ensure_forced_name_reuse
    from sase.core.agent_artifact_paths import parse_agent_artifact_path
    from sase.core.agent_identity_facade import present_agent_name
    from sase.xprompt import extract_vcs_workflow_tag, find_vcs_workflow_tag

    agent = find_named_agent(name)
    if agent is None:
        raise AgentRestartError(
            reason="not_found",
            message=f"No agent found with name '{name}'.",
            hint="List agents with `sase agent list -a`.",
        )

    artifacts_dir = Path(agent.artifacts_dir)
    meta = read_json_dict(artifacts_dir / "agent_meta.json")
    done = read_json_dict(artifacts_dir / "done.json")
    path_info = parse_agent_artifact_path(artifacts_dir)
    if path_info is None:
        project = artifacts_dir.parent.parent.parent.name
        timestamp = artifacts_dir.name
    else:
        project = path_info.project_name
        timestamp = path_info.timestamp

    raw_prompt = _require_raw_prompt(name, artifacts_dir)
    _refuse_multi_segment(name, raw_prompt)

    meta_name = optional_str(meta.get("name")) or agent.name
    presented_name = present_agent_name(meta_name)
    _refuse_container_name(meta_name, presented_name, lookup_registered_name)
    rewritten = _rewrite_prompt_identity(raw_prompt, meta_name, meta)
    if model_override:
        from sase.xprompt.directive_edit import set_prompt_model

        rewritten = set_prompt_model(rewritten, model_override)

    force_reuse_plan, rewritten, name_reuse_source = _plan_name_reuse(
        rewritten,
        meta_name=meta_name,
        presented_name=presented_name,
        plan_force_reuse_launch=plan_force_reuse_launch,
        ensure_forced_name_reuse=ensure_forced_name_reuse,
    )
    wipe_preview = preview_agent_name_wipe(meta_name)

    vcs_tag = extract_vcs_workflow_tag(raw_prompt) or find_vcs_workflow_tag(raw_prompt)
    preview = build_restart_preview(
        agent=agent,
        artifacts_dir=artifacts_dir,
        project=project,
        timestamp=timestamp,
        meta=meta,
        done=done,
        raw_prompt=raw_prompt,
        vcs_tag=vcs_tag,
        presented_name=presented_name,
        name_reuse_source=name_reuse_source,
        model_override=model_override,
        wipe_preview=wipe_preview,
    )
    return AgentRestartPlan(
        name=meta_name,
        lookup_name=name,
        presented_name=presented_name,
        agent=agent,
        artifacts_dir=artifacts_dir,
        project=project,
        meta=meta,
        done=done,
        original_prompt=raw_prompt,
        rewritten_prompt=rewritten,
        force_reuse_plan=force_reuse_plan,
        model_override=model_override,
        preview=preview,
        name_reuse_source=name_reuse_source,
        wipe_preview=wipe_preview,
    )


def _require_raw_prompt(name: str, artifacts_dir: Path) -> str:
    raw_prompt = read_raw_prompt(artifacts_dir / "raw_xprompt.md")
    if raw_prompt is None:
        raise AgentRestartError(
            reason="no_prompt",
            message=(
                f"Agent '{name}' has no raw_xprompt.md, so the CLI cannot "
                "rebuild its launch prompt."
            ),
            hint=(
                "ACE's ,x (kill-and-edit) can still reconstruct a prompt for "
                "historical rows that only have *_prompt.md."
            ),
        )
    return raw_prompt


def _refuse_multi_segment(name: str, raw_prompt: str) -> None:
    from sase.agent.multi_prompt import parse_multi_prompt

    segments = parse_multi_prompt(raw_prompt).segments
    if len(segments) > 1:
        raise AgentRestartError(
            reason="multi_segment",
            message=(
                f"Agent '{name}' stored a multi-segment prompt; refusing to "
                "relaunch a fan-out under one name."
            ),
            hint="Relaunch the segments separately, or use ACE's ,x.",
        )


def _refuse_container_name(
    meta_name: str,
    presented_name: str,
    lookup: Callable[[str], dict[str, Any] | None],
) -> None:
    record = lookup(meta_name)
    if record is None:
        return
    kind = record.get("container_kind")
    if not isinstance(kind, str) or not kind:
        return
    raise AgentRestartError(
        reason="container",
        message=(
            f"'{presented_name}' is a {kind} container; only concrete "
            "members can be restarted."
        ),
        hint=f"Restart a member of the {kind}, not the container name.",
    )


def _rewrite_prompt_identity(
    raw_prompt: str,
    meta_name: str,
    meta: dict[str, Any],
) -> str:
    from sase.agent.relaunch_prompt import (
        KillAndEditPromptError,
        prepare_kill_and_edit_prompt,
    )

    family_name, role_suffix, is_family_root = _family_rewrite_args(meta)
    try:
        return prepare_kill_and_edit_prompt(
            raw_prompt,
            meta_name,
            family_name=family_name,
            role_suffix=role_suffix,
            phase_bead_id=optional_str(meta.get("phase_bead_id")),
            is_family_root=is_family_root,
        )
    except KillAndEditPromptError as exc:
        raise AgentRestartError(
            reason="identity",
            message=str(exc),
            hint=(
                "Fix the stored prompt identity, or relaunch under a new "
                "name with `sase run`."
            ),
        ) from exc


def _family_rewrite_args(
    meta: dict[str, Any],
) -> tuple[str | None, str | None, bool]:
    agent_family = optional_str(meta.get("agent_family"))
    role_suffix = optional_str(meta.get("role_suffix"))
    is_family_root = (
        meta.get("plan_chain_root") is True or meta.get("agent_family_role") == "root"
    )
    if agent_family and meta.get("agent_family_parallel") is not True and role_suffix:
        return agent_family, role_suffix, is_family_root
    if is_family_root:
        return agent_family, role_suffix, True
    return None, None, False


def _plan_name_reuse(
    rewritten: str,
    *,
    meta_name: str,
    presented_name: str,
    plan_force_reuse_launch: Callable[[str], ForceReuseLaunchPlan | None],
    ensure_forced_name_reuse: Callable[[str, str], str],
) -> tuple[ForceReuseLaunchPlan, str, NameReuseSource]:
    force_reuse_plan = _plan_force_reuse(plan_force_reuse_launch, rewritten)
    if force_reuse_plan is not None:
        return force_reuse_plan, rewritten, "prompt"
    if _prompt_fans_out(rewritten):
        raise AgentRestartError(
            reason="fanout",
            message=(
                f"Agent '{presented_name}' stored a fan-out prompt; it has "
                "no single agent to restart."
            ),
            hint="Relaunch the variants separately, or use ACE's ,x.",
        )
    injected = ensure_forced_name_reuse(rewritten, meta_name)
    force_reuse_plan = _plan_force_reuse(plan_force_reuse_launch, injected)
    if force_reuse_plan is None:
        raise AgentRestartError(
            reason="name_not_reusable",
            message=(
                f"Could not establish forced name reuse for agent "
                f"'{presented_name}' after injecting %id."
            ),
            hint="This is an internal restart invariant; retry or use `sase run`.",
        )
    return force_reuse_plan, injected, "injected"


def _plan_force_reuse(
    plan_force_reuse_launch: Callable[[str], ForceReuseLaunchPlan | None],
    prompt: str,
) -> ForceReuseLaunchPlan | None:
    try:
        return plan_force_reuse_launch(prompt)
    except Exception as exc:
        raise AgentRestartError(
            reason="preflight",
            message=str(exc),
            hint="Fix the stored prompt and retry.",
        ) from exc


def _prompt_fans_out(prompt: str) -> bool:
    from sase.xprompt.directives import plan_prompt_fanout_variants

    return plan_prompt_fanout_variants(prompt) is not None
