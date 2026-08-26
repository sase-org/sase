"""Status-pair presentation helpers for shell kinds."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sase.palette_hash import hash_palette_index

_STATUS_PAIR_KEY_SEP = "\x1f"


@dataclass(frozen=True, slots=True)
class ShellStatusPair:
    """Ordered ``(start, stop)`` label pair for one shell kind."""

    start: str
    stop: str

    @property
    def key(self) -> str:
        """Case-insensitive identity used to pick the pair's accent."""
        return f"{self.start.upper()}{_STATUS_PAIR_KEY_SEP}{self.stop.upper()}"


def clamp_shell_status(
    value: str,
    *,
    max_chars: int,
    ellipsis: str,
    noun: str = "shell status",
) -> str:
    """Strip ``value`` and return at most *max_chars* characters."""
    if "\n" in value or "\r" in value:
        raise ValueError(f"{noun} must be a single line")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{noun} must be non-empty")
    if len(stripped) <= max_chars:
        return stripped
    return stripped[: max_chars - 1] + ellipsis


def clamp_shell_status_or_default(
    value: str | None,
    *,
    default: str,
    max_chars: int,
    ellipsis: str,
    noun: str = "shell status",
) -> str:
    """Return a clamped status, or *default* for missing/invalid input."""
    if value is None:
        return default
    try:
        return clamp_shell_status(
            value,
            max_chars=max_chars,
            ellipsis=ellipsis,
            noun=noun,
        )
    except ValueError:
        return default


def shell_status_pair(
    start: str | None,
    stop: str | None,
    *,
    default_start: str,
    default_stop: str,
    max_chars: int,
    ellipsis: str,
    pair_type: type[ShellStatusPair] = ShellStatusPair,
    noun: str = "shell status",
) -> ShellStatusPair:
    """Clamp both pair halves, filling missing halves from defaults."""
    return pair_type(
        start=clamp_shell_status_or_default(
            start,
            default=default_start,
            max_chars=max_chars,
            ellipsis=ellipsis,
            noun=noun,
        ),
        stop=clamp_shell_status_or_default(
            stop,
            default=default_stop,
            max_chars=max_chars,
            ellipsis=ellipsis,
            noun=noun,
        ),
    )


def shell_status_accent(
    pair: ShellStatusPair,
    *,
    accents: Sequence[str],
) -> str:
    """Return the deterministic accent for *pair* from *accents*."""
    return accents[hash_palette_index(pair.key, len(accents))]


def shell_status_style(
    pair: ShellStatusPair,
    *,
    shell_state: str | None,
    accents: Sequence[str],
    failure_states: set[str] | frozenset[str],
    settled_ok_states: set[str] | frozenset[str],
    failure_style: str,
) -> str:
    """Return the Rich style for a status token in *shell_state*."""
    if shell_state in failure_states:
        return failure_style
    accent = shell_status_accent(pair, accents=accents)
    if shell_state in settled_ok_states:
        return accent
    return f"bold {accent}"


def shell_status_glyph(
    shell_state: str | None,
    *,
    glyphs: Mapping[str, str],
) -> str:
    """Return the outcome glyph for *shell_state*, or ``""`` if none."""
    if shell_state is None:
        return ""
    return glyphs.get(shell_state, "")


def effective_shell_status(
    pair: ShellStatusPair,
    *,
    shell_state: str | None,
    settled: bool,
    terminal_states: set[str] | frozenset[str],
) -> str:
    """Return the displayed label for this pair and state."""
    if settled or shell_state in terminal_states:
        return pair.stop
    return pair.start


__all__ = [
    "ShellStatusPair",
    "clamp_shell_status",
    "clamp_shell_status_or_default",
    "effective_shell_status",
    "shell_status_accent",
    "shell_status_glyph",
    "shell_status_pair",
    "shell_status_style",
]
