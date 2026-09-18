"""Shared parser for the flat approval and CLI wait spec."""

from __future__ import annotations

import re

from sase.xprompt.directive_edit import PromptWaitDirective

_IDENTIFIER_RE = re.compile(r"\S+")


class WaitSpecError(ValueError):
    """A deterministic wait-spec parse failure.

    The message is suitable for direct CLI and gate-command output.
    """


def parse_wait_spec(text: str) -> PromptWaitDirective:
    """Parse agent names, ``bead=<id>``, and ``hood=<name>`` wait entries.

    Surrounding whitespace is stripped from each entry. Duplicate agents and
    keyed values are dropped while preserving first-seen order. Empty entries,
    values containing whitespace, empty keyed values, and any other
    ``key=value`` form raise :class:`WaitSpecError`.
    """
    agents: list[str] = []
    beads: list[str] = []
    hoods: list[str] = []
    seen_agents: set[str] = set()
    seen_beads: set[str] = set()
    seen_hoods: set[str] = set()
    for raw in text.split(","):
        entry = raw.strip()
        if not entry:
            raise WaitSpecError("wait spec contains an empty entry")
        if "=" in entry:
            key, _, value = entry.partition("=")
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
                    "(only agent names, bead=<id>, and hood=<name> are allowed)"
                )
            raise WaitSpecError(
                f"wait spec does not accept {key}= "
                "(only agent names, bead=<id>, and hood=<name> are allowed)"
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
    return PromptWaitDirective(
        agents=tuple(agents), beads=tuple(beads), hoods=tuple(hoods)
    )


def wait_spec_from_name_lists(
    agents: object = (),
    beads: object = (),
    hoods: object = (),
) -> PromptWaitDirective | None:
    """Rebuild a wait spec from already-parsed wait target lists.

    Only lists of non-empty strings are accepted. Empty or malformed values
    yield ``None``, matching ``plan_approval_result_from_gate_response``.
    """
    parsed_agents = _nonempty_string_tuple(agents)
    parsed_beads = _nonempty_string_tuple(beads)
    parsed_hoods = _nonempty_string_tuple(hoods)
    if not parsed_agents and not parsed_beads and not parsed_hoods:
        return None
    return PromptWaitDirective(
        agents=parsed_agents,
        beads=parsed_beads,
        hoods=parsed_hoods,
    )


def format_wait_spec(spec: PromptWaitDirective) -> str:
    """Return the canonical round-trip form of *spec*.

    Agents come first, then ``bead=<id>`` entries, then ``hood=<name>`` entries,
    comma-joined with no surrounding whitespace.
    """
    parts = list(spec.agents)
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
