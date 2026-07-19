"""Prompt-name helpers for agent retry/relaunch entry points."""

from __future__ import annotations


def rewrite_retry_prompt_name(raw_prompt: str, retry_name: str) -> str:
    """Rewrite a retry name and demote any existing clan declaration."""
    from sase.agent.retry_prompt import rewrite_retry_prompt_name as rewrite_name
    from sase.xprompt.directive_edit import demote_prompt_clan_declaration

    return demote_prompt_clan_declaration(rewrite_name(raw_prompt, retry_name))


def force_name_reuse_in_prompt(
    raw_prompt: str,
    replacement_name: str | None = None,
) -> str:
    """Force name reuse and demote any existing clan declaration."""
    from sase.agent.retry_prompt import force_name_reuse_in_prompt as force_reuse
    from sase.xprompt.directive_edit import demote_prompt_clan_declaration

    return demote_prompt_clan_declaration(
        force_reuse(raw_prompt, replacement_name=replacement_name)
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
