"""Safe bounded terminal dump for raw text artifacts."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

MAX_ARTIFACT_TEXT_BYTES = 1_048_576
BINARY_DECODE_FAILURE_RATIO = 0.05
BINARY_FILE_NOTICE = (
    "Artifact appears to be binary; fallback text viewer skipped output.\n"
)


def _dump_artifact_text(
    path: str | Path,
    *,
    limit_bytes: int = MAX_ARTIFACT_TEXT_BYTES,
    binary_decode_failure_ratio: float = BINARY_DECODE_FAILURE_RATIO,
) -> str:
    """Return a safe terminal-ready prefix of *path*."""

    if limit_bytes < 1:
        raise ValueError("limit_bytes must be positive")

    content, truncated = _read_prefix(Path(path), limit_bytes=limit_bytes)
    if b"\x00" in content:
        return BINARY_FILE_NOTICE

    decoded, failed_bytes = _decode_utf8_with_replacement(content)
    if content and failed_bytes / len(content) > binary_decode_failure_ratio:
        return BINARY_FILE_NOTICE

    output = _neutralize_terminal_controls(decoded)
    if truncated:
        output += f"\n[artifact text viewer: truncated after {limit_bytes} bytes]\n"
    return output


def _neutralize_terminal_controls(text: str) -> str:
    """Make terminal control bytes visible instead of executable."""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    parts: list[str] = []
    for character in text:
        codepoint = ord(character)
        if character in {"\n", "\t"}:
            parts.append(character)
        elif codepoint >= 0x20 and codepoint != 0x7F and not 0x80 <= codepoint <= 0x9F:
            parts.append(character)
        else:
            parts.append(_visible_control(codepoint))
    return "".join(parts)


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """CLI entry point for ``python -m sase.ace.tui.graphics.artifact_text_dump``."""

    args = list(sys.argv[1:] if argv is None else argv)
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr

    if len(args) != 2 or args[0] != "--":
        print("usage: artifact_text_dump -- <path>", file=stderr)
        return 2

    try:
        stdout.write(_dump_artifact_text(Path(args[1])))
    except OSError as exc:
        print(f"artifact text viewer: failed to read file: {exc}", file=stderr)
        return 1
    return 0


def _read_prefix(path: Path, *, limit_bytes: int) -> tuple[bytes, bool]:
    with path.open("rb") as file:
        content = file.read(limit_bytes + 1)
    return content[:limit_bytes], len(content) > limit_bytes


def _decode_utf8_with_replacement(content: bytes) -> tuple[str, int]:
    decoded_parts: list[str] = []
    failed_bytes = 0
    position = 0

    while position < len(content):
        remaining = content[position:]
        try:
            decoded_parts.append(remaining.decode("utf-8", errors="strict"))
            break
        except UnicodeDecodeError as exc:
            decoded_parts.append(
                remaining[: exc.start].decode("utf-8", errors="strict")
            )
            decoded_parts.append("\ufffd")
            failed_bytes += max(1, exc.end - exc.start)
            position += exc.end

    return "".join(decoded_parts), failed_bytes


def _visible_control(codepoint: int) -> str:
    if codepoint <= 0xFF:
        return f"\\x{codepoint:02x}"
    return f"\\u{codepoint:04x}"


if __name__ == "__main__":
    raise SystemExit(main())
