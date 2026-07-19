"""Prompt-name helpers for agent retry/relaunch entry points."""

from __future__ import annotations


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
) -> str:
    """Return the exact editable prompt for a kill-and-edit relaunch.

    Both the focused-agent and marked-agent routes use this boundary so name
    aliases, templates, and already-forced directives cannot drift between
    the single- and multi-pane workflows.
    """
    return force_name_reuse_in_prompt(raw_prompt, replacement_name=agent_name)
