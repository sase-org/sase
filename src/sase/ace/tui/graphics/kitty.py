"""Kitty graphics protocol primitives used by the ace TUI."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping
from pathlib import Path

ESC = "\x1b"
ST = ESC + "\\"
KITTY_PLACEHOLDER = chr(0x10EEEE)
_MAX_TRUECOLOR_ID = 0xFFFFFF
# Kitty's rowcolumn-diacritics.txt table for Unicode placeholder coordinates.
_PLACEHOLDER_COORDINATE_CODEPOINTS = (
    0x0305,
    0x030D,
    0x030E,
    0x0310,
    0x0312,
    0x033D,
    0x033E,
    0x033F,
    0x0346,
    0x034A,
    0x034B,
    0x034C,
    0x0350,
    0x0351,
    0x0352,
    0x0357,
    0x035B,
    0x0363,
    0x0364,
    0x0365,
    0x0366,
    0x0367,
    0x0368,
    0x0369,
    0x036A,
    0x036B,
    0x036C,
    0x036D,
    0x036E,
    0x036F,
    0x0483,
    0x0484,
    0x0485,
    0x0486,
    0x0487,
    0x0592,
    0x0593,
    0x0594,
    0x0595,
    0x0597,
    0x0598,
    0x0599,
    0x059C,
    0x059D,
    0x059E,
    0x059F,
    0x05A0,
    0x05A1,
    0x05A8,
    0x05A9,
    0x05AB,
    0x05AC,
    0x05AF,
    0x05C4,
    0x0610,
    0x0611,
    0x0612,
    0x0613,
    0x0614,
    0x0615,
    0x0616,
    0x0617,
    0x0657,
    0x0658,
    0x0659,
    0x065A,
    0x065B,
    0x065D,
    0x065E,
    0x06D6,
    0x06D7,
    0x06D8,
    0x06D9,
    0x06DA,
    0x06DB,
    0x06DC,
    0x06DF,
    0x06E0,
    0x06E1,
    0x06E2,
    0x06E4,
    0x06E7,
    0x06E8,
    0x06EB,
    0x06EC,
    0x0730,
    0x0732,
    0x0733,
    0x0735,
    0x0736,
    0x073A,
    0x073D,
    0x073F,
    0x0740,
    0x0741,
    0x0743,
    0x0745,
    0x0747,
    0x0749,
    0x074A,
    0x07EB,
    0x07EC,
    0x07ED,
    0x07EE,
    0x07EF,
    0x07F0,
    0x07F1,
    0x07F3,
    0x0816,
    0x0817,
    0x0818,
    0x0819,
    0x081B,
    0x081C,
    0x081D,
    0x081E,
    0x081F,
    0x0820,
    0x0821,
    0x0822,
    0x0823,
    0x0825,
    0x0826,
    0x0827,
    0x0829,
    0x082A,
    0x082B,
    0x082C,
    0x082D,
    0x0951,
    0x0953,
    0x0954,
    0x0F82,
    0x0F83,
    0x0F86,
    0x0F87,
    0x135D,
    0x135E,
    0x135F,
    0x17DD,
    0x193A,
    0x1A17,
    0x1A75,
    0x1A76,
    0x1A77,
    0x1A78,
    0x1A79,
    0x1A7A,
    0x1A7B,
    0x1A7C,
    0x1B6B,
    0x1B6D,
    0x1B6E,
    0x1B6F,
    0x1B70,
    0x1B71,
    0x1B72,
    0x1B73,
    0x1CD0,
    0x1CD1,
    0x1CD2,
    0x1CDA,
    0x1CDB,
    0x1CE0,
    0x1DC0,
    0x1DC1,
    0x1DC3,
    0x1DC4,
    0x1DC5,
    0x1DC6,
    0x1DC7,
    0x1DC8,
    0x1DC9,
    0x1DCB,
    0x1DCC,
    0x1DD1,
    0x1DD2,
    0x1DD3,
    0x1DD4,
    0x1DD5,
    0x1DD6,
    0x1DD7,
    0x1DD8,
    0x1DD9,
    0x1DDA,
    0x1DDB,
    0x1DDC,
    0x1DDD,
    0x1DDE,
    0x1DDF,
    0x1DE0,
    0x1DE1,
    0x1DE2,
    0x1DE3,
    0x1DE4,
    0x1DE5,
    0x1DE6,
    0x1DFE,
    0x20D0,
    0x20D1,
    0x20D4,
    0x20D5,
    0x20D6,
    0x20D7,
    0x20DB,
    0x20DC,
    0x20E1,
    0x20E7,
    0x20E9,
    0x20F0,
    0x2CEF,
    0x2CF0,
    0x2CF1,
    0x2DE0,
    0x2DE1,
    0x2DE2,
    0x2DE3,
    0x2DE4,
    0x2DE5,
    0x2DE6,
    0x2DE7,
    0x2DE8,
    0x2DE9,
    0x2DEA,
    0x2DEB,
    0x2DEC,
    0x2DED,
    0x2DEE,
    0x2DEF,
    0x2DF0,
    0x2DF1,
    0x2DF2,
    0x2DF3,
    0x2DF4,
    0x2DF5,
    0x2DF6,
    0x2DF7,
    0x2DF8,
    0x2DF9,
    0x2DFA,
    0x2DFB,
    0x2DFC,
    0x2DFD,
    0x2DFE,
    0x2DFF,
    0xA66F,
    0xA67C,
    0xA67D,
    0xA6F0,
    0xA6F1,
    0xA8E0,
    0xA8E1,
    0xA8E2,
    0xA8E3,
    0xA8E4,
    0xA8E5,
    0xA8E6,
    0xA8E7,
    0xA8E8,
    0xA8E9,
    0xA8EA,
    0xA8EB,
    0xA8EC,
    0xA8ED,
    0xA8EE,
    0xA8EF,
    0xA8F0,
    0xA8F1,
    0xAAB0,
    0xAAB2,
    0xAAB3,
    0xAAB7,
    0xAAB8,
    0xAABE,
    0xAABF,
    0xAAC1,
    0xFE20,
    0xFE21,
    0xFE22,
    0xFE23,
    0xFE24,
    0xFE25,
    0xFE26,
    0x10A0F,
    0x10A38,
    0x1D185,
    0x1D186,
    0x1D187,
    0x1D188,
    0x1D189,
    0x1D1AA,
    0x1D1AB,
    0x1D1AC,
    0x1D1AD,
    0x1D242,
    0x1D243,
    0x1D244,
)
_PLACEHOLDER_MARKS = tuple(
    chr(codepoint) for codepoint in _PLACEHOLDER_COORDINATE_CODEPOINTS
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
