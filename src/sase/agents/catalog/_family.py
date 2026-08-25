"""Name-based family/role derivation for agent-family (``--``) members.

Deliberately independent from :mod:`sase.plan_chain`, whose
``agent_family_base``/``agent_family_role_for_suffix`` helpers classify
suffixes against a fixed plan-chain vocabulary (``--plan``, ``--code``,
``--mon-*``, feedback rounds, phase questions, ...) and also treat ``.``
as a family separator for legacy spellings. The catalog's family/member
kind is defined purely structurally (any ``--``-suffixed name), so it must
recognize members plan_chain's vocabulary does not, such as clan-flavored
``--<digit>`` suffixes.
"""

from __future__ import annotations

_FAMILY_SEPARATOR = "--"


def family_and_role(name: str) -> tuple[str | None, str | None]:
    """Split *name* into its family base and role, if it is a family member.

    The family base is everything before the last ``--``; the role is the
    leading alphabetic run of the suffix token (``mon-0`` -> ``mon``), or
    ``None`` for a purely numeric suffix (``001--2`` -> no role).
    """
    if _FAMILY_SEPARATOR not in name:
        return None, None
    family, _, suffix_token = name.rpartition(_FAMILY_SEPARATOR)
    if not family or not suffix_token:
        return None, None
    return family, _alpha_prefix(suffix_token)


def _alpha_prefix(token: str) -> str | None:
    prefix_chars: list[str] = []
    for char in token:
        if not char.isalpha():
            break
        prefix_chars.append(char)
    return "".join(prefix_chars) or None
