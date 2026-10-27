"""Append small, identity-free Footprint records to the local daily spool."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
import os
from pathlib import Path
import stat

from sase import __version__
from sase.footprint.paths import MODE_LOCAL, MODE_TEST, effective_mode, spool_dir

MAX_LINE_BYTES = 512
MAX_DAY_BYTES = 32 * 1024 * 1024
MAX_DROP_BYTES = 1024 * 1024
_PRIVATE_DIRS: set[str] = set()


def append_lines(
    lines: Iterable[str | bytes],
    *,
    mode: str | None = None,
    day: str | None = None,
) -> None:
    """Append records with one ``os.write``; all filesystem errors fail open."""
    active_mode = effective_mode() if mode is None else mode
    if active_mode not in {MODE_LOCAL, MODE_TEST}:
        return

    day_value = day or date.today().isoformat()
    if not _valid_day(day_value):
        return
    path = spool_dir() / f"{day_value}.jsonl"
    records: list[bytes] = []
    for line in lines:
        if isinstance(line, str):
            try:
                value = line.encode("ascii")
            except UnicodeEncodeError:
                continue
        elif isinstance(line, bytes):
            value = line
        else:
            continue
        if not value.endswith(b"\n"):
            value += b"\n"
        if len(value) <= MAX_LINE_BYTES:
            records.append(value)
    if not records:
        return

    if active_mode == MODE_TEST:
        from sase.core.state_write_guard import assert_test_state_write_isolated

        assert_test_state_write_isolated(path, category="Footprint spool")

    payload = b"".join(records)
    for attempt in range(2):
        try:
            _ensure_private_dir(path.parent)
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                file_stat = os.fstat(fd)
                if stat.S_IMODE(file_stat.st_mode) != 0o600:
                    os.fchmod(fd, 0o600)
                size = file_stat.st_size
                if size + len(payload) <= MAX_DAY_BYTES:
                    os.write(fd, payload)
                    return

                remaining = max(0, MAX_DAY_BYTES - size)
                kept = bytearray()
                skipped = 0
                for record in records:
                    if len(kept) + len(record) <= remaining:
                        kept.extend(record)
                    else:
                        skipped += 1
                drop_line = _drop_line(day_value, skipped)
                if size > MAX_DAY_BYTES:
                    kept.clear()
                output = bytes(kept) + drop_line
                if size + len(output) <= MAX_DAY_BYTES + MAX_DROP_BYTES:
                    os.write(fd, output)
                return
            finally:
                os.close(fd)
        except FileNotFoundError:
            if attempt == 0:
                try:
                    _ensure_private_dir(path.parent)
                except OSError:
                    return
                continue
            return
        except OSError:
            return


def _ensure_private_dir(path: Path) -> None:
    for directory in (path.parent, path):
        key = os.fspath(directory)
        if key in _PRIVATE_DIRS:
            continue
        os.makedirs(directory, mode=0o700, exist_ok=True)
        if stat.S_IMODE(os.stat(directory).st_mode) != 0o700:
            os.chmod(directory, 0o700)
        _PRIVATE_DIRS.add(key)


def _drop_line(day: str, count: int) -> bytes:
    version = _safe_version(__version__)
    return f'{{"s":1,"d":"{day}","drop":{count},"ver":"{version}"}}\n'.encode("ascii")


def _safe_version(value: str) -> str:
    safe = (
        character
        for character in value
        if character.isascii() and (character.isalnum() or character in ".-+")
    )
    return "".join(safe)[:32]


def _valid_day(value: str) -> bool:
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


__all__ = [
    "MAX_DAY_BYTES",
    "MAX_DROP_BYTES",
    "MAX_LINE_BYTES",
    "append_lines",
]
