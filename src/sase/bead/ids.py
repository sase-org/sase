"""Issue ID generation using prefix + base36 counter."""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterable
from pathlib import Path

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
_lock = threading.Lock()


def _to_base36(n: int) -> str:
    """Convert a non-negative integer to a base36 string."""
    if n < 0:
        raise ValueError("Cannot convert negative number to base36")
    if n == 0:
        return "0"
    digits: list[str] = []
    while n:
        digits.append(_ALPHABET[n % 36])
        n //= 36
    return "".join(reversed(digits))


def _from_base36(s: str) -> int:
    """Convert a base36 string to an integer."""
    return int(s, 36)


class IdGenerator:
    """Thread-safe ID generator using prefix + base36 counter."""

    def __init__(self, prefix: str, counter: int = 1) -> None:
        self.prefix = prefix
        self._counter = counter

    @property
    def counter(self) -> int:
        return self._counter

    def next_id(self, minimum_counter: int | None = None) -> str:
        """Generate the next issue ID, e.g. 'sase-03v'."""
        with _lock:
            if minimum_counter is not None:
                self._counter = max(self._counter, minimum_counter)
            issue_id = f"{self.prefix}-{_to_base36(self._counter)}"
            self._counter += 1
            return issue_id


def max_top_level_counter(issue_prefix: str, beads_dir: Path) -> int:
    """Return the highest allocated top-level counter in one JSONL store."""
    return max_counter_in_ids(issue_prefix, _iter_jsonl_issue_ids(beads_dir))


def max_counter_in_ids(issue_prefix: str, issue_ids: Iterable[str]) -> int:
    """Return the highest top-level counter among *issue_ids*."""
    pattern = re.compile(rf"^{re.escape(issue_prefix)}-([0-9a-z]+)$")
    max_counter = 0
    for issue_id in issue_ids:
        match = pattern.fullmatch(issue_id)
        if match is None:
            continue
        try:
            max_counter = max(max_counter, _from_base36(match.group(1)))
        except ValueError:
            continue
    return max_counter


def issue_id_for_counter(issue_prefix: str, counter: int) -> str:
    """Return the ``<prefix>-<base36>`` id one counter value maps to."""
    return f"{issue_prefix}-{_to_base36(counter)}"


def _iter_jsonl_issue_ids(beads_dir: Path) -> list[str]:
    """Return issue IDs from one JSONL file, skipping malformed records."""
    jsonl_path = (Path(beads_dir) / "issues.jsonl").resolve()
    if not jsonl_path.exists():
        return []
    try:
        lines = jsonl_path.read_text().splitlines()
    except OSError:
        return []
    ids: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        issue_id = data.get("id")
        if isinstance(issue_id, str):
            ids.append(issue_id)
    return ids
