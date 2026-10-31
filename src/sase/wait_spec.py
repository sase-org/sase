"""Shared parser for the flat approval and CLI wait spec."""

from __future__ import annotations

import re

from sase.macro.directive_edit import PromptWaitDirective

_IDENTIFIER_RE = re.compile(r"\S+")


class WaitSpecError(ValueError):
    """A deterministic wait-spec parse failure.

    The message is suitable for direct CLI and gate-command output.
    """


def parse_wait_spec(text: str) -> PromptWaitDirective:
    """Parse agent names, ``turn=<agent>``, ``bead=<id>``, and ``hood=<name>`` entries.

    A ``turn=<agent>`` entry waits for that agent's current turn instead of the
    whole session. It is disjoint from plain agent entries: listing the same
    agent both ways is an error.

    Surrounding whitespace is stripped from each entry. Duplicate agents and
    keyed values are dropped while preserving first-seen order. Empty entries,
    values containing whitespace, empty keyed values, and any other
    ``key=value`` form raise :class:`WaitSpecError`.
    """
    agents: list[str] = []
    turn_agents: list[str] = []
    beads: list[str] = []
    hoods: list[str] = []
    seen_agents: set[str] = set()
    seen_turn_agents: set[str] = set()
    seen_beads: set[str] = set()
    seen_hoods: set[str] = set()
    for raw in text.split(","):
        entry = raw.strip()
        if not entry:
            raise WaitSpecError("wait spec contains an empty entry")
        if "=" in entry:
            key, _, value = entry.partition("=")
            if key == "turn":
                _require_identifier(
                    value,
                    empty_message=(
                        "wait spec turn= requires a non-empty, whitespace-free "
                        "agent name"
                    ),
                )
                if value not in seen_turn_agents:
                    seen_turn_agents.add(value)
                    turn_agents.append(value)
                continue
            if key == "bead":
                _require_identifier(
                    value,
                    empty_message=(
                        "wait spec bead= requires a non-empty, whitespace-free bead ID"
                    ),
                )
                if value not in seen_beads:
                    seen_beads.add(value)
                    beads.append(value)
                continue
            if key == "hood":
                _require_identifier(
                    value,
                    empty_message=(
                        "wait spec hood= requires a non-empty, whitespace-free hood name"
                    ),
                )
                if value not in seen_hoods:
                    seen_hoods.add(value)
                    hoods.append(value)
                continue
            if not key:
                raise WaitSpecError(
                    "wait spec does not accept a leading '=' "
                    "(only agent names, turn=<agent>, bead=<id>, and "
                    "hood=<name> are allowed)"
                )
            raise WaitSpecError(
                f"wait spec does not accept {key}= "
                "(only agent names, turn=<agent>, bead=<id>, and "
                "hood=<name> are allowed)"
            )
        _require_identifier(
            entry,
            empty_message=(
                f"wait spec entries must be non-empty and whitespace-free: {entry!r}"
            ),
        )
        if entry not in seen_agents:
            seen_agents.add(entry)
            agents.append(entry)
    for name in turn_agents:
        if name in seen_agents:
            raise WaitSpecError(
                f"wait spec lists {name!r} both as an agent and as turn=<agent> "
                "(an agent can only wait one way)"
            )
    merged_agents = list(agents)
    merged_agents.extend(name for name in turn_agents if name not in seen_agents)
    return PromptWaitDirective(
        agents=tuple(merged_agents),
        beads=tuple(beads),
        hoods=tuple(hoods),
        turn_target_agents=tuple(turn_agents),
    )


def wait_spec_from_name_lists(
    agents: object = (),
    beads: object = (),
    hoods: object = (),
    turn_agents: object = (),
) -> PromptWaitDirective | None:
    """Rebuild a wait spec from already-parsed wait target lists.

    Only lists of non-empty strings are accepted. Empty or malformed values
    yield ``None``, matching ``plan_approval_result_from_gate_response``.
    ``turn_agents`` names the turn-targeted subset; names missing from
    ``agents`` are appended so the turn set stays inside the agent set.
    """
    parsed_agents = _nonempty_string_tuple(agents)
    parsed_beads = _nonempty_string_tuple(beads)
    parsed_hoods = _nonempty_string_tuple(hoods)
    parsed_turn = _nonempty_string_tuple(turn_agents)
    if parsed_turn:
        merged = list(parsed_agents)
        merged.extend(name for name in parsed_turn if name not in parsed_agents)
        parsed_agents = tuple(merged)
    if not parsed_agents and not parsed_beads and not parsed_hoods:
        return None
    return PromptWaitDirective(
        agents=parsed_agents,
        beads=parsed_beads,
        hoods=parsed_hoods,
        turn_target_agents=parsed_turn,
    )


def format_wait_spec(spec: PromptWaitDirective) -> str:
    """Return the canonical round-trip form of *spec*.

    Session agents come first, then ``turn=<agent>`` entries, then
    ``bead=<id>`` entries, then ``hood=<name>`` entries, comma-joined with no
    surrounding whitespace.
    """
    turn_set = set(spec.turn_target_agents)
    parts = [agent for agent in spec.agents if agent not in turn_set]
    parts.extend(f"turn={agent}" for agent in spec.agents if agent in turn_set)
    seen = set(spec.agents)
    parts.extend(
        f"turn={agent}" for agent in spec.turn_target_agents if agent not in seen
    )
    parts.extend(f"bead={bead_id}" for bead_id in spec.beads)
    parts.extend(f"hood={hood}" for hood in spec.hoods)
    return ",".join(parts)


def _nonempty_string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    names: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            return ()
        names.append(item)
    return tuple(names)


def _require_identifier(value: str, *, empty_message: str) -> None:
    if not value or _IDENTIFIER_RE.fullmatch(value) is None:
        raise WaitSpecError(empty_message)


__all__ = [
    "WaitSpecError",
    "format_wait_spec",
    "parse_wait_spec",
    "wait_spec_from_name_lists",
]
