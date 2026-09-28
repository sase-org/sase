"""Prompt expansion and directive extraction for the run agent runner.

Expands xprompt references, extracts prompt directives (model, name, waits,
clan membership), and checks bead and clan consistency before tab, tribe,
and provider resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any


@dataclass(frozen=True)
class PreparedPrompt:
    """Expanded prompt and validated launch plans for directive resolution."""

    directives: Any
    expanded_for_directives: str
    fork_reference_prompt: str
    agent_session_attach_plan: Any | None
    clan_membership_plan: Any | None
    batch_predecessor_binding: Any | None


def prepare_prompt(
    prompt_body: str,
    local_xprompts: dict[str, Any],
    *,
    raw_resolved_prompt: str | None,
    preserved_metadata: dict[str, Any],
) -> PreparedPrompt:
    """Expand xprompts and extract directives with clan membership checks."""
    from sase.xprompt import (
        LAUNCH_DEFERRED_XPROMPT_NAMES,
        process_xprompt_references,
    )

    # Expand xprompts before extracting directives so directives embedded in
    # xprompts are discovered for agent metadata.
    expanded_for_directives = process_xprompt_references(
        prompt_body,
        extra_xprompts=local_xprompts or None,
        defer_xprompt_names=LAUNCH_DEFERRED_XPROMPT_NAMES,
    )
    from sase.agent.agent_name_keys import has_unresolved_agent_name_key_marker

    if has_unresolved_agent_name_key_marker(expanded_for_directives):
        raise RuntimeError(
            "Agent prompt still contains an unresolved keyed agent-name marker. "
            "The parent launch pipeline failed to resolve keyed markers before "
            "starting the runner."
        )
    from sase.agent.batch_predecessor import (
        consume_batch_predecessor_context_from_env,
        preserved_batch_predecessor_context,
    )

    batch_predecessor_binding = None
    predecessor_context = consume_batch_predecessor_context_from_env()
    if predecessor_context is None:
        predecessor_context = preserved_batch_predecessor_context(preserved_metadata)
    if predecessor_context is not None:
        from sase.core.agent_launch_facade import bind_batch_predecessor_waits

        batch_predecessor_binding = bind_batch_predecessor_waits(
            expanded_for_directives,
            predecessor_context,
        )
        expanded_for_directives = batch_predecessor_binding.prompt

    from sase.xprompt.directives import extract_prompt_directives

    _, directives = extract_prompt_directives(expanded_for_directives)
    bead_id = directives.bead_id
    if bead_id is not None:
        from sase.bead.work import SASE_BEAD_ID_ENV

        existing_bead_id = os.environ.get(SASE_BEAD_ID_ENV, "")
        if existing_bead_id.strip() and existing_bead_id != bead_id:
            raise RuntimeError(
                f"%id bead association '{bead_id}' does not match "
                f"{SASE_BEAD_ID_ENV}='{existing_bead_id}'"
            )
        os.environ[SASE_BEAD_ID_ENV] = bead_id

    fork_reference_prompt = expanded_for_directives
    if "#fork" not in fork_reference_prompt and raw_resolved_prompt:
        # Compatibility fallback for callers whose supplied catalog does not
        # retain the built-in fork reference during analysis.
        fork_reference_prompt = raw_resolved_prompt

    from sase.agent.agent_session_attach import load_agent_session_attach_plan_from_env

    agent_session_attach_plan = load_agent_session_attach_plan_from_env()
    from sase.agent.clan_membership import (
        ClanMembershipError,
        consume_clan_membership_plan_from_env,
        preserved_clan_membership_plan,
    )

    clan_membership_plan = consume_clan_membership_plan_from_env()
    if clan_membership_plan is None and directives.clan is not None:
        # Refreshed runner pass after a dependency wait: the pre-wait pass
        # already consumed the one-shot env payload and overwrote
        # agent_meta.json, so preserved clan fields exist only on this replay
        # of the identical submitted prompt. Recover the launch identity
        # instead of re-declaring the clan.
        clan_membership_plan = preserved_clan_membership_plan(preserved_metadata)
    if clan_membership_plan is not None and directives.clan is None:
        raise ClanMembershipError(
            "Clan membership payload requires a %clan directive or "
            "%id(..., clan=...) keyword"
        )
    if (
        directives.tribe is not None
        and directives.clan is not None
        and not directives.clan_declared
    ):
        raise ClanMembershipError(
            "Cannot use %id(..., tribe=...) when joining a clan with "
            "%id(..., clan=...); joining a clan joins its tribe. Put tribe= "
            "on the clan's %clan declaration instead."
        )
    if (
        directives.tribe is not None
        and agent_session_attach_plan is not None
        and agent_session_attach_plan.parent_agent_clan
    ):
        raise ClanMembershipError(
            "Cannot use %id(..., tribe=...) on an agent-session attachment that "
            "inherits clan membership; tribe membership belongs to the "
            "inherited clan and must be supplied by a clan member's "
            "%clan(<clan>, tribe=<tribe>) declaration."
        )

    return PreparedPrompt(
        directives=directives,
        expanded_for_directives=expanded_for_directives,
        fork_reference_prompt=fork_reference_prompt,
        agent_session_attach_plan=agent_session_attach_plan,
        clan_membership_plan=clan_membership_plan,
        batch_predecessor_binding=batch_predecessor_binding,
    )


__all__ = ["PreparedPrompt", "prepare_prompt"]
