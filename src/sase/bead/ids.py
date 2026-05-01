"""Issue ID generation using prefix + base36 counter."""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterable
from pathlib import Path

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
_lock = threading.Lock()


def to_base36(n: int) -> str:
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


def from_base36(s: str) -> int:
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
            issue_id = f"{self.prefix}-{to_base36(self._counter)}"
            self._counter += 1
            return issue_id


def max_top_level_counter(issue_prefix: str, beads_dirs: Iterable[Path]) -> int:
    """Return the highest allocated top-level counter in workspace JSONL files."""
    pattern = re.compile(rf"^{re.escape(issue_prefix)}-([0-9a-z]+)$")
    max_counter = 0
    for issue_id in _iter_jsonl_issue_ids(beads_dirs):
        match = pattern.fullmatch(issue_id)
        if match is None:
            continue
        try:
            max_counter = max(max_counter, from_base36(match.group(1)))
        except ValueError:
            continue
    return max_counter


def max_child_counter(parent_id: str, beads_dirs: Iterable[Path]) -> int:
    """Return the highest direct child counter for *parent_id* in JSONL files."""
    prefix = f"{parent_id}."
    max_counter = 0
    for issue_id in _iter_jsonl_issue_ids(beads_dirs):
        if not issue_id.startswith(prefix):
            continue
        suffix = issue_id[len(prefix) :]
        if "." in suffix:
            continue
        try:
            max_counter = max(max_counter, int(suffix))
        except ValueError:
            continue
    return max_counter


def _iter_jsonl_issue_ids(beads_dirs: Iterable[Path]) -> Iterable[str]:
    """Yield issue IDs from workspace JSONL files, skipping malformed records."""
    seen_paths: set[Path] = set()
    for beads_dir in beads_dirs:
        jsonl_path = (Path(beads_dir) / "issues.jsonl").resolve()
        if jsonl_path in seen_paths:
            continue
        seen_paths.add(jsonl_path)
        if not jsonl_path.exists():
            continue
        try:
            lines = jsonl_path.read_text().splitlines()
        except OSError:
            continue
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
                yield issue_id
