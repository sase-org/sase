"""Opt-in zsh-history backfill as Footprint ``derived.history`` rows."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shlex
from typing import Any

from sase.footprint._cli import resolve_command_ids
from sase.footprint.derived_rows import coverage_row, daily_row, local_day
from sase.footprint.ids import cli_option_id

ORIGIN = "derived.history"
_SURFACE = "cli"
_ACTOR = "human"
_VIA = "cli"
_EXTENDED = re.compile(r"^: (\d+):(\d+);(.*)$")


@dataclass(frozen=True)
class _HistoryPreview:
    """Counts produced by a history parse before confirmation."""

    path: Path
    commands: Counter[str]
    options: int
    skipped_untimestamped: int
    skipped_other: int
    rows: tuple[dict[str, Any], ...]
    coverage: tuple[dict[str, Any], ...]
    days: tuple[str, ...]

    @property
    def imported(self) -> int:
        return sum(self.commands.values())


def default_history_path() -> Path:
    """Return ``$HISTFILE`` or ``~/.zsh_history``."""
    configured = os.environ.get("HISTFILE")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".zsh_history"


def extract_history_rows(
    path: Path,
    *,
    parser: Any,
    today: str,
) -> _HistoryPreview:
    """Parse *path* into derived CLI rows without storing the source lines."""
    counts: dict[tuple[str, str], int] = defaultdict(int)
    dur_sum: dict[tuple[str, str], int] = defaultdict(int)
    dur_max: dict[tuple[str, str], int] = defaultdict(int)
    commands: Counter[str] = Counter()
    options = 0
    skipped_untimestamped = 0
    skipped_other = 0
    for epoch, duration_s, argv in _iter_sase_commands(path):
        if epoch is None:
            skipped_untimestamped += 1
            continue
        if argv is None:
            skipped_other += 1
            continue
        day = local_day(epoch)
        if day is None:
            skipped_other += 1
            continue
        try:
            feature_id, dests = resolve_command_ids(parser, argv)
        except (OSError, ValueError):
            skipped_other += 1
            continue
        dur_ms = max(0, int(duration_s) * 1000)
        counts[(day, feature_id)] += 1
        dur_sum[(day, feature_id)] += dur_ms
        dur_max[(day, feature_id)] = max(dur_max[(day, feature_id)], dur_ms)
        commands[feature_id] += 1
        for dest in dests:
            option_id = cli_option_id(feature_id, dest)
            counts[(day, option_id)] += 1
            options += 1

    rows = [
        daily_row(
            day,
            feature_id,
            actor=_ACTOR,
            via=_VIA,
            n=n,
            dur_ms_sum=dur_sum.get((day, feature_id), 0),
            dur_ms_max=dur_max.get((day, feature_id), 0),
        )
        for (day, feature_id), n in sorted(counts.items())
    ]
    days = sorted({day for day, _feature in counts} | {today})
    coverage = [
        coverage_row(
            day,
            _SURFACE,
            records=sum(
                n for (row_day, _feature), n in counts.items() if row_day == day
            ),
            human_active=int(any(row_day == day for row_day, _feature in counts)),
        )
        for day in days
    ]
    return _HistoryPreview(
        path=path,
        commands=commands,
        options=options,
        skipped_untimestamped=skipped_untimestamped,
        skipped_other=skipped_other,
        rows=tuple(rows),
        coverage=tuple(coverage),
        days=tuple(days),
    )


def _iter_sase_commands(
    path: Path,
) -> list[tuple[int | None, int, list[str] | None]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    events: list[tuple[int | None, int, list[str] | None]] = []
    pending = ""
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        if pending:
            line = pending + line
            pending = ""
        if line.endswith("\\"):
            pending = line[:-1]
            continue
        parsed = _parse_line(line)
        if parsed is not None:
            events.append(parsed)
    if pending:
        parsed = _parse_line(pending)
        if parsed is not None:
            events.append(parsed)
    return events


def _parse_line(line: str) -> tuple[int | None, int, list[str] | None] | None:
    stripped = line.strip()
    if not stripped:
        return None
    match = _EXTENDED.match(stripped)
    if match is None:
        if _starts_with_sase(stripped):
            return None, 0, None
        return None
    epoch = int(match.group(1))
    duration_s = int(match.group(2))
    command = match.group(3).strip()
    if not _starts_with_sase(command):
        return None
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return epoch, duration_s, None
    if not tokens:
        return epoch, duration_s, None
    return epoch, duration_s, tokens[1:]


def _starts_with_sase(command: str) -> bool:
    return command == "sase" or command.startswith("sase ")


__all__ = [
    "ORIGIN",
    "default_history_path",
    "extract_history_rows",
]
