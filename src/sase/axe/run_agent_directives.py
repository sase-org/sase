"""Directive extraction and agent metadata setup for the run agent runner."""

import json
import os
import re
from typing import Any, NamedTuple

from sase.axe.chop_agents import agent_meta_from_chop_env
from sase.axe.run_agent_markers import write_agent_meta


class AgentInfo(NamedTuple):
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
) -> AgentInfo:
    """Extract prompt directives and write agent_meta.json.

    Expands xprompt references, extracts directives (model, name, etc.),
    resolves LLM/VCS providers, writes metadata, and claims agent name.

    Returns AgentInfo with all extracted info.
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

    # A top-level `#fork:<name>` implies `%wait:<name>`: the forked agent must
    # not start until its fork target finishes. We add the implied dependency as
    # runner metadata (a local wait_names list) rather than rewriting the prompt
    # text, so prompt history and raw xprompt artifacts stay clean while every
    # launch surface behaves consistently. Bare `#fork` and `#fork_by_chat`
    # resolve their targets dynamically and are excluded. An explicit
    # `%wait:<name>` for the same target is not duplicated.
    from sase.agent.names import first_fork_agent_name

    wait_names = list(directives.wait)
    fork_wait_target = first_fork_agent_name(raw_resolved_prompt)
    if fork_wait_target and fork_wait_target not in wait_names:
        wait_names.append(fork_wait_target)

    auto_dismiss = os.environ.get("SASE_AGENT_AUTO_DISMISS")

    agent_name = directives.name
    resume_name: str | None = None
    wait_name: str | None = None
    if not directives.name_explicit and not auto_dismiss:
        from sase.agent.names import first_resume_agent_name

        resume_name = first_resume_agent_name(raw_resolved_prompt)
        if resume_name is None and len(wait_names) == 1:
            wait_name = wait_names[0]

    repeat_name = os.environ.get("SASE_REPEAT_NAME")
    planned_name = os.environ.get("SASE_AGENT_PLANNED_NAME")
    # Pop: the marker describes this launch only. Leaving it in the
    # environment makes nested launches from this agent treat their own
    # explicit %name directives as generated, silently skipping name
    # collision checks.
    generated_name = os.environ.pop("SASE_AGENT_GENERATED_NAME", None) == "1"
    name_user_explicit = directives.name_explicit and not generated_name
    name_requires_lock = bool(
        agent_name or repeat_name or resume_name or wait_name or not auto_dismiss
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

    # Resolve the effective reasoning effort (explicit %effort/@effort directive
    # beats llm_provider.default_effort) so the Agents tab can render a uniform
    # ``Model: PROVIDER(model) @ <effort>`` suffix that matches the effort the
    # provider adapter actually applied at invocation time.
    from sase.llm_provider.config import resolve_effective_effort

    agent_reasoning_effort, _ = resolve_effective_effort(directives)

    vcs_name = detect_vcs(workspace_dir)
    if vcs_name:
        from sase.workspace_provider import get_display_name_by_vcs

        agent_vcs_provider = get_display_name_by_vcs(vcs_name)
    else:
        agent_vcs_provider = None

    agent_tag: str | None = None
    with name_lock_context:
        agent_name_from_template = False
        if directives.name_explicit and directives.name_template and agent_name:
            from sase.agent.names import (
                allocate_agent_name_template,
                match_agent_name_template,
            )

            if planned_name and match_agent_name_template(agent_name, planned_name):
                agent_name = planned_name
            else:
                agent_name = allocate_agent_name_template(agent_name)
            agent_name_from_template = True

        planned_name_matches_resume = (
            planned_name is not None
            and resume_name is not None
            and _planned_name_matches_resume_target(planned_name, resume_name)
        )
        planned_name_is_usable = (
            planned_name is not None
            and not auto_dismiss
            and (resume_name is None or planned_name_matches_resume)
        )
        if agent_name_from_template:
            pass
        elif not name_user_explicit and planned_name_is_usable:
            agent_name = planned_name
        elif not name_user_explicit and resume_name is not None:
            from sase.agent.names import allocate_resume_name

            agent_name = allocate_resume_name(resume_name)
        elif not name_user_explicit and repeat_name is None and wait_name is not None:
            from sase.agent.names import allocate_wait_name

            agent_name = allocate_wait_name(wait_name)
        if agent_name is None:
            agent_name = repeat_name
        if agent_name is None and not auto_dismiss:
            from sase.agent.names import get_next_auto_name

            agent_name = get_next_auto_name()

        agent_tag = directives.tag
        if agent_tag is None and agent_name:
            from sase.ace.agent_tags import load_agent_tags, match_existing_name_group

            agent_tag = match_existing_name_group(
                agent_name,
                load_agent_tags().values(),
            )

        # Build agent_meta dict.
        agent_meta: dict[str, Any] = {
            "pid": os.getpid(),
            "workspace_dir": workspace_dir,
        }
        if agent_name:
            agent_meta["name"] = agent_name
        if wait_names:
            agent_meta["wait_for"] = wait_names
        if directives.wait_duration is not None:
            agent_meta["wait_duration"] = directives.wait_duration
        if directives.wait_until is not None:
            agent_meta["wait_until"] = directives.wait_until
        if agent_model:
            agent_meta["model"] = agent_model
        if agent_llm_provider:
            agent_meta["llm_provider"] = agent_llm_provider
        if agent_reasoning_effort:
            agent_meta["reasoning_effort"] = agent_reasoning_effort
        if agent_vcs_provider:
            agent_meta["vcs_provider"] = agent_vcs_provider
        if directives.approve:
            agent_meta["approve"] = True
        if directives.epic:
            agent_meta["auto_approve_plan_action"] = "epic"
        if directives.hide or auto_dismiss:
            agent_meta["hidden"] = True
        if directives.epic:
            agent_meta["plan"] = True
        if agent_tag:
            agent_meta["tag"] = agent_tag
        if directives.name_template and directives.name:
            agent_meta["agent_name_template"] = directives.name
        linked_repos = _linked_repos_from_env()
        if linked_repos:
            # Canonical key plus the deprecated alias for existing readers.
            agent_meta["linked_repos"] = linked_repos
            agent_meta["sibling_repos"] = linked_repos
        agent_meta.update(agent_meta_from_chop_env())
        if cl_name:
            agent_meta["changespec_name"] = cl_name
            agent_meta.setdefault("cl_name", cl_name)

        if agent_name:
            from sase.agent.names import claim_agent_name
            from sase.agent.launch_validation import (
                internal_agent_name_bypass_enabled,
                validate_user_agent_name,
            )

            if name_user_explicit and not internal_agent_name_bypass_enabled(
                os.environ
            ):
                validate_user_agent_name(agent_name)

            claim_agent_name(
                agent_name,
                artifacts_dir,
                explicit=name_user_explicit,
                force_reuse=directives.name_force_reuse,
            )
            os.environ["SASE_AGENT_NAME"] = agent_name

        # Write agent_meta.json after the name reservation succeeds so
        # concurrent explicit claims cannot both publish the same name.
        if agent_meta:
            write_agent_meta(artifacts_dir, agent_meta)

    # Persist the %group directive into ~/.sase/agent_tags.json so the Agents
    # tab picks it up at load time.  The agent's identity is
    # (agent_type=WORKFLOW, cl_name, raw_suffix) — matching how run-agents
    # are loaded via the workflow loader.
    if agent_tag and cl_name:
        from sase.ace.tui.models.agent import AgentType

        raw_suffix = os.path.basename(artifacts_dir.rstrip(os.sep)) or None
        identity = (AgentType.WORKFLOW, cl_name, raw_suffix)
        if directives.tag:
            from sase.ace.agent_tags import update_agent_tag

            update_agent_tag(identity, directives.tag)
        elif agent_name:
            from sase.ace.agent_tags import update_agent_tag_from_existing_name_group

            update_agent_tag_from_existing_name_group(identity, agent_name)

    return AgentInfo(
        name=agent_name,
        wait_names=wait_names,
        wait_duration=directives.wait_duration,
        wait_until=directives.wait_until,
        model=agent_model,
        llm_provider=agent_llm_provider,
        vcs_provider=agent_vcs_provider,
        hidden=bool(directives.hide or auto_dismiss),
        approve=bool(directives.approve),
        plan=bool(directives.epic),
        tag=agent_tag,
        meta=agent_meta,
        local_xprompts=multi.local_xprompts,
    )


def _linked_repos_from_env() -> list[dict[str, object]]:
    from sase.linked_repos import linked_repo_metadata_from_env

    return linked_repo_metadata_from_env()


def _planned_name_matches_resume_target(planned_name: str, resume_name: str) -> bool:
    pattern = rf"^{re.escape(resume_name)}\.f\d+(?:\.|$)"
    return re.match(pattern, planned_name) is not None
