"""Prompt-name helpers for agent retry/relaunch entry points."""

from __future__ import annotations


def prompt_facing_agent_name(agent_name: str) -> str:
    """Return the editable-prompt spelling of a durable agent name."""
    from sase.core.agent_identity_facade import present_agent_name

    return present_agent_name(agent_name)


def rewrite_retry_prompt_name(
    raw_prompt: str,
    retry_name: str,
    *,
    current_agent_name: str | None = None,
) -> str:
    """Rewrite a retry name and demote any existing clan declaration."""
    from sase.agent.multi_prompt_references import extract_static_clan_directive
    from sase.agent.retry_prompt import rewrite_retry_prompt_name as rewrite_name
    from sase.xprompt.directive_edit import rewrite_prompt_clan_member_name

    if extract_static_clan_directive(raw_prompt) is not None:
        return rewrite_prompt_clan_member_name(
            raw_prompt,
            retry_name,
            current_agent_name=current_agent_name,
        )
    return rewrite_name(raw_prompt, retry_name)


def force_name_reuse_in_prompt(
    raw_prompt: str,
    replacement_name: str | None = None,
) -> str:
    """Force name reuse and demote any existing clan declaration."""
    from sase.agent.multi_prompt_references import extract_static_clan_directive
    from sase.agent.retry_prompt import force_name_reuse_in_prompt as force_reuse
    from sase.xprompt.directive_edit import (
        demote_prompt_clan_declaration,
        rewrite_prompt_clan_member_name,
    )

    clan = extract_static_clan_directive(raw_prompt)
    if clan is not None and replacement_name is not None:
        return rewrite_prompt_clan_member_name(
            raw_prompt,
            replacement_name,
            current_agent_name=replacement_name,
            force_reuse=True,
        )

    rewritten = force_reuse(raw_prompt, replacement_name=replacement_name)
    return (
        demote_prompt_clan_declaration(rewritten)
        if clan is not None and clan.declared
        else rewritten
    )


def prepare_kill_and_edit_prompt(
    raw_prompt: str,
    agent_name: str | None,
    *,
    family_name: str | None = None,
    role_suffix: str | None = None,
    phase_bead_id: str | None = None,
) -> str:
    """Return the exact editable prompt for a kill-and-edit relaunch.

    Both the focused-agent and marked-agent routes use this boundary so name
    aliases, templates, and already-forced directives cannot drift between
    the single- and multi-pane workflows.
    """
    if family_name and role_suffix:
        from sase.xprompt.directive_edit import rewrite_prompt_family_member_name

        return rewrite_prompt_family_member_name(
            raw_prompt,
            prompt_facing_agent_name(family_name),
            role_suffix,
            force_reuse=True,
            bead_id=phase_bead_id,
        )

    # A clan member lives in a ``<clan>.<suffix>`` hood. Preserve that full
    # name so forced reuse targets the real member rather than its clan.
    replacement_name = prompt_facing_agent_name(agent_name) if agent_name else None
    if replacement_name:
        from sase.plan_chain import AGENT_FAMILY_SEPARATOR, agent_family_base

        # Legacy callers without family metadata retain the old base-name
        # behavior. Real family rows take the explicit branch above.
        if AGENT_FAMILY_SEPARATOR in replacement_name:
            replacement_name = agent_family_base(replacement_name) or replacement_name
    return force_name_reuse_in_prompt(raw_prompt, replacement_name=replacement_name)
