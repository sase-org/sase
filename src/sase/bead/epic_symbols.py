"""Discover Justfile ``--epic-symbol`` whitelist entries.

Symvision accepts ``--epic-symbol <bead_id>(<symbol>)`` only while that bead
is still open. The exemption goes stale the instant the bead closes, and the
next unrelated ``just check`` is what used to discover the leftover. Parse the
working tree's Justfile so close can surface those entries instead of leaving
them for the next agent.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
import re

from sase.bead.model import Issue, Status

_JUSTFILE_NAMES = ("Justfile", "justfile")
_EPIC_SYMBOL_TOKEN = re.compile(
    r"""--epic-symbol(?:\s+|=)(?:"([^"]+)"|'([^']+)'|(\S+))"""
)
_EPIC_SYMBOL_BODY = re.compile(r"^(?P<bead>[^\s(]+)\((?P<symbol>[^)]+)\)$")


@dataclass(frozen=True, slots=True)
class _EpicSymbolEntry:
    """One ``--epic-symbol <bead_id>(<symbol>)`` flag from a Justfile."""

    bead_id: str
    symbol: str
    source: Path | None = None

    @property
    def raw(self) -> str:
        return f"{self.bead_id}({self.symbol})"

    @property
    def flag(self) -> str:
        return f'--epic-symbol "{self.raw}"'


class _LeftoverEpicSymbolsError(ValueError):
    """Raised when closing would stale remaining ``--epic-symbol`` entries."""


def discover_justfile(start: Path | None = None) -> Path | None:
    """Return the nearest Justfile at or above *start*, stopping at a git root."""
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        for name in _JUSTFILE_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
        if (directory / ".git").exists():
            return None
    return None


def _parse_epic_symbol_entries(
    text: str, *, source: Path | None = None
) -> list[_EpicSymbolEntry]:
    """Parse ``--epic-symbol`` flags from Justfile (or equivalent) text."""
    entries: list[_EpicSymbolEntry] = []
    for match in _EPIC_SYMBOL_TOKEN.finditer(text):
        body = next(group for group in match.groups() if group)
        parsed = _EPIC_SYMBOL_BODY.fullmatch(body)
        if parsed is None:
            continue
        entries.append(
            _EpicSymbolEntry(
                bead_id=parsed.group("bead"),
                symbol=parsed.group("symbol"),
                source=source,
            )
        )
    return entries


def load_epic_symbol_entries(start: Path | None = None) -> list[_EpicSymbolEntry]:
    """Load ``--epic-symbol`` entries from the Justfile nearest *start*."""
    justfile = discover_justfile(start)
    if justfile is None:
        return []
    return _parse_epic_symbol_entries(
        justfile.read_text(encoding="utf-8"), source=justfile
    )


def _entry_owned_by(target_id: str, entry_bead_id: str) -> bool:
    """Return whether *entry_bead_id* is *target_id* or one of its descendants."""
    return entry_bead_id == target_id or entry_bead_id.startswith(f"{target_id}.")


def entries_for_beads(
    entries: Iterable[_EpicSymbolEntry], bead_ids: Iterable[str]
) -> list[_EpicSymbolEntry]:
    """Return entries keyed to any of *bead_ids* or their descendant suffixes."""
    targets = tuple(bead_ids)
    return [
        entry
        for entry in entries
        if any(_entry_owned_by(target_id, entry.bead_id) for target_id in targets)
    ]


def _leftover_epic_symbols_for_close(
    issues: Iterable[Issue],
    entries: Iterable[_EpicSymbolEntry],
) -> list[_EpicSymbolEntry]:
    """Return whitelist entries that would go stale if *issues* closed."""
    open_ids = [issue.id for issue in issues if issue.status is not Status.CLOSED]
    if not open_ids:
        return []
    return entries_for_beads(entries, open_ids)


def _leftover_epic_symbols_error_message(
    leftovers: Iterable[_EpicSymbolEntry],
    *,
    close_ids: Iterable[str],
) -> str:
    """Format the close refusal that names every leftover Justfile entry."""
    entries = list(leftovers)
    targets = ", ".join(close_ids)
    lines = [
        f"refusing to close {targets}: Justfile still has --epic-symbol "
        "entries keyed to this bead (they go stale the instant the bead "
        "closes and turn unrelated agents' just check red):",
        *(f"  {entry.flag}" for entry in entries),
        "",
        "Resolve each symbol (wire it up, privatize it, add a non-test "
        "pragma, or delete it) or re-key the Justfile line to a still-open "
        "bead. List them with:",
        f"  sase bead epic-symbols {next(iter(close_ids), '<id>')}",
    ]
    return "\n".join(lines)


def raise_if_leftover_epic_symbols(
    issues: Iterable[Issue],
    *,
    start: Path | None = None,
) -> None:
    """Refuse a close that would stale remaining ``--epic-symbol`` entries."""
    issue_list = list(issues)
    leftovers = _leftover_epic_symbols_for_close(
        issue_list, load_epic_symbol_entries(start)
    )
    if not leftovers:
        return
    close_ids = [issue.id for issue in issue_list if issue.status is not Status.CLOSED]
    raise _LeftoverEpicSymbolsError(
        _leftover_epic_symbols_error_message(leftovers, close_ids=close_ids)
    )
