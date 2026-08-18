"""Prompt-name helpers for agent retry and relaunch.

These used to live under ``sase.ace.tui`` so ACE could rewrite a stored prompt
for ``,x``. The CLI restart path needs the same rewrite without importing the
TUI package, so the functions live here and the TUI module re-exports them.
"""

from __future__ import annotations

_PROMPT_EXCERPT_CHARS = 120


class KillAndEditPromptError(Exception):
    """A kill-and-edit rewrite that must not be launched."""

    def __init__(
        self,
        reason: str,
        *,
        agent_name: str | None = None,
        produced: str | None = None,
    ) -> None:
        label = agent_name or "(unnamed)"
        excerpt = _prompt_excerpt(produced) if produced else None
        if excerpt:
            message = (
                f"Cannot relaunch '{label}': {reason} (rewrite produced {excerpt!r})"
            )
        else:
            message = f"Cannot relaunch '{label}': {reason}"
        super().__init__(message)
        self.reason = reason
        self.agent_name = agent_name
        self.produced = produced


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


def ensure_forced_name_reuse(prompt: str, agent_name: str) -> str:
    """Return *prompt* with a forced-reuse ``%id`` for *agent_name*."""
    from sase.xprompt.directive_edit import set_prompt_name

    named = set_prompt_name(prompt, agent_name)
    return force_name_reuse_in_prompt(named, replacement_name=agent_name)


def prepare_kill_and_edit_prompt(
    raw_prompt: str,
    agent_name: str | None,
    *,
    family_name: str | None = None,
    role_suffix: str | None = None,
    phase_bead_id: str | None = None,
    is_family_root: bool = False,
) -> str:
    """Return the exact editable prompt for a kill-and-edit relaunch.

    Both the focused-agent and marked-agent routes use this boundary so name
    aliases, templates, and already-forced directives cannot drift between
    the single- and multi-pane workflows.

    Family roots are named under the family reference and forced to reuse
    that name. Non-root serial-family members keep the exact-member
    ``family=`` rewrite. A rewrite that would drop clan membership without a
    parent to inherit from, self-attach ``family=`` to the relaunched agent,
    or omit forced name reuse raises :class:`KillAndEditPromptError`.
    """
    facing_agent = _facing_name(agent_name)
    facing_family = _facing_name(family_name)
    if is_family_root:
        rewritten = _force_named_reuse(
            raw_prompt,
            _root_reuse_name(facing_family, facing_agent),
            agent_name=agent_name,
        )
    elif family_name and role_suffix:
        rewritten = _rewrite_family_member_or_preserve_clan(
            raw_prompt,
            facing_family=facing_family,
            role_suffix=role_suffix,
            phase_bead_id=phase_bead_id,
            facing_agent=facing_agent,
            agent_name=agent_name,
        )
    else:
        rewritten = _force_named_reuse(
            raw_prompt,
            _non_family_reuse_name(facing_agent),
            agent_name=agent_name,
        )
    _verify_kill_and_edit_prompt(
        raw_prompt,
        rewritten,
        agent_name=agent_name,
        family_name=family_name,
        is_family_root=is_family_root,
    )
    return rewritten


def _facing_name(name: str | None) -> str | None:
    if not name:
        return None
    presented = prompt_facing_agent_name(name)
    return presented or None


def _root_reuse_name(
    facing_family: str | None,
    facing_agent: str | None,
) -> str | None:
    if facing_family:
        return facing_family
    if not facing_agent:
        return None
    from sase.plan_chain import agent_family_base

    return agent_family_base(facing_agent, include_legacy_dash=True) or facing_agent


def _non_family_reuse_name(facing_agent: str | None) -> str | None:
    if not facing_agent:
        return None
    from sase.plan_chain import AGENT_FAMILY_SEPARATOR, agent_family_base

    # Legacy callers without family metadata retain the old base-name
    # behavior. Real family rows take the explicit family branch.
    if AGENT_FAMILY_SEPARATOR in facing_agent:
        return agent_family_base(facing_agent) or facing_agent
    return facing_agent


def _force_named_reuse(
    raw_prompt: str,
    reuse_name: str | None,
    *,
    agent_name: str | None,
) -> str:
    if reuse_name:
        try:
            return ensure_forced_name_reuse(raw_prompt, reuse_name)
        except ValueError as exc:
            raise KillAndEditPromptError(
                str(exc),
                agent_name=agent_name or reuse_name,
                produced=raw_prompt,
            ) from exc
    return force_name_reuse_in_prompt(raw_prompt)


def _rewrite_family_member_or_preserve_clan(
    raw_prompt: str,
    *,
    facing_family: str | None,
    role_suffix: str,
    phase_bead_id: str | None,
    facing_agent: str | None,
    agent_name: str | None,
) -> str:
    from sase.xprompt.directive_edit import rewrite_prompt_family_member_name

    if not facing_family:
        raise KillAndEditPromptError(
            "cannot rewrite a family member without a family name",
            agent_name=agent_name,
            produced=raw_prompt,
        )
    try:
        rewritten = rewrite_prompt_family_member_name(
            raw_prompt,
            facing_family,
            role_suffix,
            force_reuse=True,
            bead_id=phase_bead_id,
        )
    except ValueError as exc:
        raise KillAndEditPromptError(
            str(exc),
            agent_name=agent_name,
            produced=raw_prompt,
        ) from exc
    if _family_rewrite_drops_unrecoverable_clan(
        raw_prompt,
        rewritten,
        facing_family=facing_family,
        facing_agent=facing_agent,
        role_suffix=role_suffix,
    ):
        # The family reference is the relaunch identity; the shell suffix
        # (``--plan``, ``--0``) must not become the clan member name.
        return _force_named_reuse(
            raw_prompt,
            facing_family,
            agent_name=agent_name,
        )
    return rewritten


def _family_rewrite_drops_unrecoverable_clan(
    raw_prompt: str,
    rewritten: str,
    *,
    facing_family: str,
    facing_agent: str | None,
    role_suffix: str,
) -> bool:
    """Return True when a family rewrite deleted the only copy of clan membership.

    Genuine non-root members inherit clan context from the family parent, so
    dropping ``%clan`` / ``clan=`` there is correct. A root or self-attach
    has no such parent: refuse the family form and keep the clan path.
    """
    original_clan = _prompt_clan_name(raw_prompt)
    if original_clan is None or _prompt_clan_name(rewritten) is not None:
        return False
    if facing_agent and facing_family == facing_agent:
        return True
    return _is_family_origin_suffix(role_suffix)


def _is_family_origin_suffix(role_suffix: str | None) -> bool:
    if not role_suffix:
        return False
    from sase.plan_chain import (
        PLAN_CHAIN_PLAN_SUFFIX,
        agent_family_suffix_token,
        canonical_plan_chain_suffix,
    )

    canonical = canonical_plan_chain_suffix(role_suffix) or role_suffix
    if canonical == PLAN_CHAIN_PLAN_SUFFIX or canonical.startswith(
        f"{PLAN_CHAIN_PLAN_SUFFIX}-"
    ):
        return True
    return agent_family_suffix_token(canonical) == "0"


def _prompt_clan_name(prompt: str) -> str | None:
    from sase.agent.multi_prompt_references import extract_static_clan_directive

    clan = extract_static_clan_directive(prompt)
    return clan.name if clan is not None else None


def _verify_kill_and_edit_prompt(
    raw_prompt: str,
    rewritten: str,
    *,
    agent_name: str | None,
    family_name: str | None,
    is_family_root: bool,
) -> None:
    from sase.xprompt.directives import DirectiveError, extract_prompt_directives

    try:
        _, directives = extract_prompt_directives(rewritten)
    except DirectiveError as exc:
        raise KillAndEditPromptError(
            f"rewrite is not a valid prompt identity ({exc})",
            agent_name=agent_name,
            produced=rewritten,
        ) from exc

    facing_agent = _facing_name(agent_name)
    facing_family = _facing_name(family_name)
    presented_row = facing_family if is_family_root else facing_agent
    family_parent = _facing_name(directives.family_attach_parent)
    original_clan = _prompt_clan_name(raw_prompt)

    if family_parent:
        _verify_family_form(
            rewritten,
            family_parent=family_parent,
            facing_family=facing_family,
            facing_agent=facing_agent,
            presented_row=presented_row,
            is_family_root=is_family_root,
            name_force_reuse=directives.name_force_reuse,
            agent_name=agent_name,
        )
    elif directives.clan:
        _verify_clan_form(
            rewritten,
            clan=directives.clan,
            joined_name=directives.name,
            presented_row=presented_row or facing_agent,
            name_force_reuse=directives.name_force_reuse,
            agent_name=agent_name,
        )
    else:
        _verify_plain_form(
            rewritten,
            named=directives.name,
            presented_row=presented_row or facing_agent,
            name_force_reuse=directives.name_force_reuse,
            agent_name=agent_name,
        )

    if original_clan and not directives.clan:
        if family_parent and not is_family_root and family_parent != presented_row:
            return
        raise KillAndEditPromptError(
            "rewrite dropped clan membership",
            agent_name=agent_name,
            produced=rewritten,
        )


def _verify_family_form(
    rewritten: str,
    *,
    family_parent: str,
    facing_family: str | None,
    facing_agent: str | None,
    presented_row: str | None,
    is_family_root: bool,
    name_force_reuse: bool,
    agent_name: str | None,
) -> None:
    if not name_force_reuse:
        raise KillAndEditPromptError(
            "family rewrite is missing forced name reuse",
            agent_name=agent_name,
            produced=rewritten,
        )
    if is_family_root or (presented_row and family_parent == presented_row):
        raise KillAndEditPromptError(
            f"family={family_parent} attaches the agent to itself",
            agent_name=agent_name or presented_row,
            produced=rewritten,
        )
    if facing_family and family_parent != facing_family:
        raise KillAndEditPromptError(
            f"family={family_parent} does not match family {facing_family}",
            agent_name=agent_name,
            produced=rewritten,
        )
    if facing_agent:
        from sase.plan_chain import agent_family_base

        shell_family = _facing_name(
            agent_family_base(facing_agent, include_legacy_dash=True)
        )
        if shell_family and shell_family != family_parent:
            raise KillAndEditPromptError(
                f"family={family_parent} does not match agent {facing_agent}",
                agent_name=agent_name,
                produced=rewritten,
            )


def _verify_clan_form(
    rewritten: str,
    *,
    clan: str,
    joined_name: str | None,
    presented_row: str | None,
    name_force_reuse: bool,
    agent_name: str | None,
) -> None:
    if not name_force_reuse:
        raise KillAndEditPromptError(
            "clan rewrite is missing forced name reuse",
            agent_name=agent_name,
            produced=rewritten,
        )
    if not joined_name:
        raise KillAndEditPromptError(
            "clan rewrite has no member identity",
            agent_name=agent_name,
            produced=rewritten,
        )
    prefix = f"{clan}."
    if not joined_name.startswith(prefix) or not joined_name[len(prefix) :]:
        raise KillAndEditPromptError(
            f"clan rewrite '{joined_name}' is not a member of '{clan}'",
            agent_name=agent_name,
            produced=rewritten,
        )
    if presented_row and not _names_match_relaunched(joined_name, presented_row):
        raise KillAndEditPromptError(
            f"clan rewrite '{joined_name}' does not name '{presented_row}'",
            agent_name=agent_name,
            produced=rewritten,
        )


def _verify_plain_form(
    rewritten: str,
    *,
    named: str | None,
    presented_row: str | None,
    name_force_reuse: bool,
    agent_name: str | None,
) -> None:
    if not named:
        raise KillAndEditPromptError(
            "rewrite has no %id identity",
            agent_name=agent_name,
            produced=rewritten,
        )
    if not name_force_reuse:
        raise KillAndEditPromptError(
            "rewrite is missing forced name reuse",
            agent_name=agent_name,
            produced=rewritten,
        )
    if presented_row and not _names_match_relaunched(named, presented_row):
        raise KillAndEditPromptError(
            f"rewrite '%id:{named}' does not name '{presented_row}'",
            agent_name=agent_name,
            produced=rewritten,
        )


def _names_match_relaunched(actual: str, expected: str) -> bool:
    facing_actual = _facing_name(actual)
    facing_expected = _facing_name(expected)
    if facing_actual == facing_expected:
        return True
    from sase.plan_chain import agent_family_base

    expected_base = agent_family_base(
        facing_expected or expected,
        include_legacy_dash=True,
    )
    return facing_actual is not None and facing_actual == _facing_name(expected_base)


def _prompt_excerpt(text: str, limit: int = _PROMPT_EXCERPT_CHARS) -> str:
    single_line = text.replace("\n", " ").strip()
    if len(single_line) <= limit:
        return single_line
    return single_line[: max(limit - 1, 1)] + "…"
