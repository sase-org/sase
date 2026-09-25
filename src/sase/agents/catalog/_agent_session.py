"""Name-based agent-session/role derivation for agent-session (``--``) members.

Deliberately independent from :mod:`sase.plan_chain`, whose
``agent_session_base``/``agent_session_role_for_suffix`` helpers classify
suffixes against a fixed plan-chain vocabulary (``--plan``, ``--code``,
``--mon-*``, feedback rounds, phase questions, ...) and also treat ``.``
as an agent-session separator for legacy spellings. The catalog's
agent-session/member kind is defined purely structurally (any
``--``-suffixed name), so it must recognize members plan_chain's vocabulary
does not, such as clan-flavored ``--<digit>`` suffixes.
"""

from __future__ import annotations

_AGENT_SESSION_SEPARATOR = "--"


def agent_session_and_role(name: str) -> tuple[str | None, str | None]:
    """Split *name* into its agent-session base and role, if it is a member.

    The agent-session base is everything before the last ``--``; the role is
    the leading alphabetic run of the suffix token (``mon-0`` -> ``mon``), or
    ``None`` for a purely numeric suffix (``001--2`` -> no role).
    """
    if _AGENT_SESSION_SEPARATOR not in name:
        return None, None
    agent_session, _, suffix_token = name.rpartition(_AGENT_SESSION_SEPARATOR)
    if not agent_session or not suffix_token:
        return None, None
    return agent_session, _alpha_prefix(suffix_token)


def _alpha_prefix(token: str) -> str | None:
    prefix_chars: list[str] = []
    for char in token:
        if not char.isalpha():
            break
        prefix_chars.append(char)
    return "".join(prefix_chars) or None
