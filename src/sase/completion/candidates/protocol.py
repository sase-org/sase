"""Wire format for pre-argparse completion candidates.

One candidate per line, ``value<TAB>description``, description optional. This
maps directly onto zsh ``_describe`` and degrades to plain words in bash and
fish. Every provider gets identical prefix-filter and result-limit semantics
through :func:`filter_candidates` rather than reimplementing them.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

DEFAULT_LIMIT = 200


@dataclass(frozen=True, slots=True)
class Candidate:
    """One completion candidate: a value and an optional short description."""

    value: str
    description: str = ""


def _sanitize_field(field: str) -> str:
    """Strip characters that would corrupt the tab-separated wire format."""
    return field.replace("\t", " ").replace("\n", " ").replace("\r", " ")


def candidate_to_line(candidate: Candidate) -> str:
    """Render one candidate as a ``value<TAB>description`` wire line."""
    value = _sanitize_field(candidate.value)
    description = _sanitize_field(candidate.description)
    return f"{value}\t{description}" if description else value


def candidate_from_line(line: str) -> Candidate:
    """Parse one ``value<TAB>description`` wire line back into a candidate."""
    value, _, description = line.partition("\t")
    return Candidate(value, description)


def render_candidates(candidates: Iterable[Candidate]) -> str:
    """Render candidates as newline-joined wire lines; empty for none."""
    return "\n".join(candidate_to_line(candidate) for candidate in candidates)


def filter_candidates(
    candidates: Iterable[Candidate], prefix: str, limit: int
) -> list[Candidate]:
    """Apply the shared prefix filter and result limit every provider gets."""
    matched = (
        [candidate for candidate in candidates if candidate.value.startswith(prefix)]
        if prefix
        else list(candidates)
    )
    return matched[:limit] if limit >= 0 else matched


__all__ = [
    "DEFAULT_LIMIT",
    "Candidate",
    "candidate_from_line",
    "candidate_to_line",
    "filter_candidates",
    "render_candidates",
]
