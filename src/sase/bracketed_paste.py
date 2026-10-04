"""Normalize bracketed paste bodies before Textual parses them."""

from __future__ import annotations

import re


_START = "\x1b[200~"
_END = "\x1b[201~"
_KEY = re.compile(
    r"\x1b\[(?:27;(\d+);(\d+)~|"
    r"(\d+)(?::\d*)*(?:;(\d+)(?::\d+)?)?u)"
)
_CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_MODIFIER_BITS = 1 | 2 | 4


def _decode_extended_key(match: re.Match[str]) -> str:
    """Decode one CSI-u or xterm modifyOtherKeys sequence."""
    if match.group(1) is not None:
        modifier = int(match.group(1))
        codepoint = int(match.group(2))
    else:
        codepoint = int(match.group(3))
        modifier = int(match.group(4) or "1")

    if modifier < 1 or codepoint > 0x10FFFF:
        return ""

    bits = modifier - 1
    if bits & ~_MODIFIER_BITS:
        return ""

    if bits & 4:
        if codepoint in (0x20, ord("2"), ord("@")):
            return ""
        if codepoint == ord("?"):
            return "\x7f"
        if 0x40 <= codepoint <= 0x5F or ord("a") <= codepoint <= ord("z"):
            return chr(codepoint & 0x1F)

    return chr(codepoint)


def _normalize_paste_body(body: str) -> str:
    """Restore text tmux re-encoded as extended keys inside a paste."""
    decoded = _KEY.sub(_decode_extended_key, body)
    without_csi = _CSI.sub("", decoded)
    return without_csi.replace("\x1b", "").replace("\x00", "")


class BracketedPasteNormalizer:
    """Stream bracketed pastes while leaving ordinary input untouched."""

    def __init__(self) -> None:
        self._tail = ""
        self._in_paste = False
        self._buffer = ""

    def feed(self, data: str) -> str:
        """Return data safe to pass to Textual's parser."""
        output: list[str] = []
        while data:
            if not self._in_paste:
                scan = self._tail + data
                start = scan.find(_START)
                if start < 0:
                    output.append(data)
                    self._tail = scan[-(len(_START) - 1) :]
                    break

                cut = start + len(_START) - len(self._tail)
                output.append(data[:cut])
                data = data[cut:]
                self._tail = ""
                self._buffer = ""
                self._in_paste = True
            else:
                self._buffer += data
                data = ""
                end = self._buffer.find(_END)
                if end < 0:
                    break

                output.append(_normalize_paste_body(self._buffer[:end]) + _END)
                data = self._buffer[end + len(_END) :]
                self._buffer = ""
                self._in_paste = False

        return "".join(output)


__all__ = ["BracketedPasteNormalizer"]
