"""Kitty graphics protocol primitives used by the ace TUI."""

from __future__ import annotations

import base64
import hashlib
import unicodedata
from collections.abc import Mapping
from pathlib import Path

ESC = "\x1b"
ST = ESC + "\\"
KITTY_PLACEHOLDER = chr(0x10EEEE)
_MAX_TRUECOLOR_ID = 0xFFFFFF
_PLACEHOLDER_MARKS = tuple(
    chr(codepoint)
    for codepoint in range(0x0300, 0x2000)
    if unicodedata.combining(chr(codepoint)) == 230
)


def generate_image_id(key: str | Path | bytes) -> int:
    """Generate a non-zero 24-bit Kitty image ID from a stable key."""
    if isinstance(key, bytes):
        payload = key
    else:
        payload = str(key).encode("utf-8", "surrogatepass")
    digest = hashlib.blake2b(payload, digest_size=4).digest()
    value = int.from_bytes(digest, "big") & _MAX_TRUECOLOR_ID
    return value or 1


def build_apc_sequence(control: Mapping[str, str | int], payload: bytes = b"") -> str:
    """Build a Kitty APC escape sequence with base64-encoded payload bytes."""
    control_data = ",".join(f"{key}={value}" for key, value in control.items())
    encoded_payload = base64.b64encode(payload).decode("ascii") if payload else ""
    return f"{ESC}_G{control_data};{encoded_payload}{ST}"


def tmux_passthrough_wrap(sequence: str) -> str:
    """Wrap a terminal escape sequence for tmux DCS passthrough."""
    return f"{ESC}Ptmux;{sequence.replace(ESC, ESC + ESC)}{ST}"


def _maybe_wrap(sequence: str, *, tmux: bool) -> str:
    return tmux_passthrough_wrap(sequence) if tmux else sequence


def build_png_upload_sequences(
    png_bytes: bytes,
    image_id: int,
    *,
    chunk_size: int = 4096,
    tmux: bool = False,
) -> list[str]:
    """Build chunked Kitty direct-transfer upload sequences for PNG bytes."""
    if not png_bytes:
        raise ValueError("png_bytes must not be empty")
    if image_id <= 0 or image_id > _MAX_TRUECOLOR_ID:
        raise ValueError("image_id must fit in 24 bits for placeholder encoding")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    payload = base64.b64encode(png_bytes).decode("ascii")
    chunks = [
        payload[index : index + chunk_size]
        for index in range(0, len(payload), chunk_size)
    ]
    sequences: list[str] = []
    for index, chunk in enumerate(chunks):
        more = 1 if index < len(chunks) - 1 else 0
        if index == 0:
            control: dict[str, str | int] = {
                "a": "t",
                "f": 100,
                "t": "d",
                "i": image_id,
                "q": 2,
                "m": more,
            }
        else:
            control = {"m": more}
        sequence = f"{ESC}_G{','.join(f'{key}={value}' for key, value in control.items())};{chunk}{ST}"
        sequences.append(_maybe_wrap(sequence, tmux=tmux))
    return sequences


def build_place_sequence(
    image_id: int,
    placement_id: int,
    *,
    columns: int,
    rows: int,
    tmux: bool = False,
) -> str:
    """Build a virtual placement sequence for Unicode-placeholder rendering."""
    if columns <= 0 or rows <= 0:
        raise ValueError("columns and rows must be positive")
    sequence = build_apc_sequence(
        {
            "a": "p",
            "i": image_id,
            "p": placement_id,
            "U": 1,
            "c": columns,
            "r": rows,
            "q": 2,
        }
    )
    return _maybe_wrap(sequence, tmux=tmux)


def build_delete_sequence(image_id: int, *, tmux: bool = False) -> str:
    """Build a sequence that frees a previously uploaded Kitty image."""
    sequence = build_apc_sequence({"a": "d", "d": "I", "i": image_id, "q": 2})
    return _maybe_wrap(sequence, tmux=tmux)


def _placeholder_mark(value: int) -> str:
    if value < 0 or value >= len(_PLACEHOLDER_MARKS):
        raise ValueError(
            f"placeholder coordinate {value} exceeds the v1 limit of {len(_PLACEHOLDER_MARKS) - 1}"
        )
    return _PLACEHOLDER_MARKS[value]


def _placeholder_cell(row: int, column: int) -> str:
    """Return one Kitty Unicode-placeholder cell for *row* and *column*."""
    return f"{KITTY_PLACEHOLDER}{_placeholder_mark(row)}{_placeholder_mark(column)}"


def placeholder_grid(columns: int, rows: int) -> list[str]:
    """Return text rows containing explicit Kitty placeholder coordinates."""
    if columns <= 0 or rows <= 0:
        raise ValueError("columns and rows must be positive")
    return [
        "".join(_placeholder_cell(row, column) for column in range(columns))
        for row in range(rows)
    ]
