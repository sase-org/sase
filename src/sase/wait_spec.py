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
    """Parse a comma-separated list of agent names and ``bead=<id>`` entries.

    Surrounding whitespace is stripped from each entry. Duplicate agents and
    beads are dropped while preserving first-seen order. Empty entries, values
    containing whitespace, empty ``bead=``, and any other ``key=value`` form
    raise :class:`WaitSpecError`.
    """
    agents: list[str] = []
    beads: list[str] = []
    seen_agents: set[str] = set()
    seen_beads: set[str] = set()
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
            if not key:
                raise WaitSpecError(
                    "wait spec does not accept a leading '=' "
                    "(only agent names and bead=<id> are allowed)"
                )
            raise WaitSpecError(
                f"wait spec does not accept {key}= "
                "(only agent names and bead=<id> are allowed)"
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
    return PromptWaitDirective(agents=tuple(agents), beads=tuple(beads))


def format_wait_spec(spec: PromptWaitDirective) -> str:
    """Return the canonical round-trip form of *spec*.

    Agents come first, then ``bead=<id>`` entries, comma-joined with no
    surrounding whitespace.
    """
    parts = list(spec.agents)
    parts.extend(f"bead={bead_id}" for bead_id in spec.beads)
    return ",".join(parts)


def _require_identifier(value: str, *, empty_message: str) -> None:
    if not value or _IDENTIFIER_RE.fullmatch(value) is None:
        raise WaitSpecError(empty_message)


__all__ = ["WaitSpecError", "format_wait_spec", "parse_wait_spec"]
