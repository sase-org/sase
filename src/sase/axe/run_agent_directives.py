"""Directive extraction and agent metadata setup for the run agent runner."""

import json
import os
from typing import Any, NamedTuple

from sase.axe.chop_agents import agent_meta_from_chop_env
from sase.axe.run_agent_markers import _write_agent_meta


class _AgentInfo(NamedTuple):
    """Result of directive extraction and metadata writing."""

    name: str | None
    wait_names: list[str]
    wait_duration: float | None
    wait_until: str | None
    model: str | None
    llm_provider: str | None
    vcs_provider: str | None
    hidden: bool
    approve: bool
    plan: bool
    tag: str | None
    meta: dict[str, Any]
    local_xprompts: dict[str, Any]


def extract_directives_and_write_meta(
    prompt: str,
    workspace_dir: str,
    artifacts_dir: str,
    cl_name: str | None = None,
    *,
    raw_resolved_prompt: str | None = None,
) -> _AgentInfo:
    """Extract prompt directives and write agent_meta.json.

    Expands xprompt references, extracts directives (model, name, etc.),
    resolves LLM/VCS providers, writes metadata, and claims agent name.

    Returns _AgentInfo with all extracted info.
    """
    from sase.llm_provider.registry import (
        get_default_provider_name,
        resolve_model_provider,
    )
    from sase.llm_provider.temporary_override import (
        resolve_effective_default_provider_model,
    )
    from sase.vcs_provider._registry import detect_vcs
    from sase.xprompt import process_xprompt_references
    from sase.xprompt.directives import extract_prompt_directives

    # Parse user-prompt frontmatter to extract local xprompts.
    from sase.agent.multi_prompt import parse_multi_prompt
    from sase.agent.names import ensure_historical_auto_name_migration

    ensure_historical_auto_name_migration()

    multi = parse_multi_prompt(prompt)
    prompt_body = "\n---\n".join(multi.segments)

    # Merge env-var-delivered local xprompts (from multi-prompt launcher)
    # with frontmatter-defined ones.  Frontmatter takes precedence.
    env_xprompts_path = os.environ.pop("SASE_AGENT_LOCAL_XPROMPTS", None)
    if env_xprompts_path:
        try:
            from sase.agent.multi_prompt_launcher import deserialize_local_xprompts

            env_xprompts = deserialize_local_xprompts(env_xprompts_path)
            # Frontmatter xprompts take precedence over env-delivered ones.
            multi.local_xprompts = {**env_xprompts, **multi.local_xprompts}
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass
        finally:
            try:
                os.unlink(env_xprompts_path)
            except OSError:
                pass

    # Expand xprompts before extracting directives so that
    # directives embedded in xprompts (e.g. %model:#pro inside
    # #mentor) are discovered for agent metadata.
    expanded_for_directives = process_xprompt_references(
        prompt_body,
        extra_xprompts=multi.local_xprompts or None,
    )
    _, directives = extract_prompt_directives(expanded_for_directives)

    auto_dismiss = os.environ.get("SASE_AGENT_AUTO_DISMISS")

    agent_name = directives.name
    resume_name: str | None = None
    if not directives.name_explicit and not auto_dismiss:
        from sase.agent.names import first_resume_agent_name

        resume_name = first_resume_agent_name(raw_resolved_prompt)

    repeat_name = os.environ.get("SASE_REPEAT_NAME")
    planned_name = os.environ.get("SASE_AGENT_PLANNED_NAME")
    name_requires_lock = bool(
        agent_name or repeat_name or resume_name or not auto_dismiss
    )

    from contextlib import AbstractContextManager, nullcontext

    name_lock_context: AbstractContextManager[None]
    if name_requires_lock:
        from sase.agent.names import agent_name_allocation_lock

        name_lock_context = agent_name_allocation_lock()
    else:
        name_lock_context = nullcontext()

    agent_model = directives.model
    if agent_model:
        resolved_provider, agent_model = resolve_model_provider(agent_model)
        agent_llm_provider = resolved_provider or get_default_provider_name()
    else:
        agent_llm_provider, agent_model = resolve_effective_default_provider_model()

    vcs_name = detect_vcs(workspace_dir)
    if vcs_name:
        from sase.workspace_provider import get_display_name_by_vcs

        agent_vcs_provider = get_display_name_by_vcs(vcs_name)
    else:
        agent_vcs_provider = None

    with name_lock_context:
        if not directives.name_explicit and planned_name and not auto_dismiss:
            agent_name = planned_name
        elif not directives.name_explicit and resume_name is not None:
            from sase.agent.names import allocate_resume_name

            agent_name = allocate_resume_name(resume_name)
        if agent_name is None:
            agent_name = repeat_name
        if agent_name is None and not auto_dismiss:
            from sase.agent.names import get_next_auto_name

            agent_name = get_next_auto_name()

        # Build agent_meta dict.
        agent_meta: dict[str, Any] = {
            "pid": os.getpid(),
            "workspace_dir": workspace_dir,
        }
        if agent_name:
            agent_meta["name"] = agent_name
        if directives.wait:
            agent_meta["wait_for"] = directives.wait
        if directives.wait_duration is not None:
            agent_meta["wait_duration"] = directives.wait_duration
        if directives.wait_until is not None:
            agent_meta["wait_until"] = directives.wait_until
        if agent_model:
            agent_meta["model"] = agent_model
        if agent_llm_provider:
            agent_meta["llm_provider"] = agent_llm_provider
        if agent_vcs_provider:
            agent_meta["vcs_provider"] = agent_vcs_provider
        if directives.approve:
            agent_meta["approve"] = True
        if directives.epic:
            agent_meta["auto_approve_plan_action"] = "epic"
        if directives.hide or auto_dismiss:
            agent_meta["hidden"] = True
        if directives.plan or directives.epic:
            agent_meta["plan"] = True
        if directives.tag:
            agent_meta["tag"] = directives.tag
        agent_meta.update(agent_meta_from_chop_env())
        if cl_name:
            agent_meta["changespec_name"] = cl_name
            agent_meta.setdefault("cl_name", cl_name)

        if agent_name:
            from sase.agent.names import claim_agent_name

            claim_agent_name(
                agent_name,
                artifacts_dir,
                explicit=directives.name_explicit,
                force_reuse=directives.name_force_reuse,
            )
            os.environ["SASE_AGENT_NAME"] = agent_name

        # Write agent_meta.json after the name reservation succeeds so
        # concurrent explicit claims cannot both publish the same name.
        if agent_meta:
            _write_agent_meta(artifacts_dir, agent_meta)

    # Persist the %group directive into ~/.sase/agent_tags.json so the Agents
    # tab picks it up at load time.  The agent's identity is
    # (agent_type=WORKFLOW, cl_name, raw_suffix) — matching how run-agents
    # are loaded via the workflow loader.
    if directives.tag and cl_name:
        from sase.ace.agent_tags import update_agent_tag
        from sase.ace.tui.models.agent import AgentType

        raw_suffix = os.path.basename(artifacts_dir.rstrip(os.sep)) or None
        identity = (AgentType.WORKFLOW, cl_name, raw_suffix)
        update_agent_tag(identity, directives.tag)

    return _AgentInfo(
        name=agent_name,
        wait_names=directives.wait,
        wait_duration=directives.wait_duration,
        wait_until=directives.wait_until,
        model=agent_model,
        llm_provider=agent_llm_provider,
        vcs_provider=agent_vcs_provider,
        hidden=bool(directives.hide or auto_dismiss),
        approve=bool(directives.approve),
        plan=bool(directives.plan or directives.epic),
        tag=directives.tag,
        meta=agent_meta,
        local_xprompts=multi.local_xprompts,
    )
