"""Bounded streaming capture for a monitored command's output."""

from __future__ import annotations

#: Retain at most this many bytes of output (head + tail).
MONITOR_MAX_OUTPUT_BYTES = 2 * 1024 * 1024

_ELISION_TEMPLATE = "\n… {elided} bytes elided …\n"


class OutputCapture:
    """Stream a monitored command's merged output into a log file.

    Every chunk is written to *output_path* (and flushed) immediately, so the
    TUI's ``get_live_reply_content()`` shows output live with no new
    plumbing -- the file on disk is never truncated. The *retained* in-memory
    view (what the terminal marker and a later follow-up prompt draw from)
    is capped at ``max_bytes``: once exceeded, the middle collapses to a
    head + tail split with an explicit elision marker so a chatty command
    cannot fill the artifacts store or blow up a follow-up prompt.
    """

    def __init__(
        self,
        output_path: str,
        *,
        max_bytes: int = MONITOR_MAX_OUTPUT_BYTES,
    ) -> None:
        self._max_bytes = max_bytes
        self._half = max_bytes // 2
        self._buffer = bytearray()
        self._head: bytes = b""
        self._tail = bytearray()
        self._truncated = False
        self._total_bytes = 0
        self._file = open(output_path, "ab", buffering=0)

    def append(self, text: str) -> None:
        """Append *text* to the log file and the retained output view."""
        encoded = text.encode("utf-8", errors="replace")
        self._file.write(encoded)
        self._total_bytes += len(encoded)
        if not self._truncated:
            self._buffer += encoded
            if len(self._buffer) > self._max_bytes:
                self._truncated = True
                self._head = bytes(self._buffer[: self._half])
                self._tail = bytearray(self._buffer[-self._half :])
                self._buffer = bytearray()
        else:
            self._tail += encoded
            overflow = len(self._tail) - self._half
            if overflow > 0:
                del self._tail[:overflow]

    def close(self) -> None:
        self._file.close()

    @property
    def truncated(self) -> bool:
        """Return whether the retained view has elided any output."""
        return self._truncated

    @property
    def total_bytes(self) -> int:
        """Return the total number of bytes written, including elided ones."""
        return self._total_bytes

    def retained_text(self) -> str:
        """Return the retained output, with an elision marker if truncated."""
        if not self._truncated:
            return self._buffer.decode("utf-8", errors="replace")
        elided = max(self._total_bytes - len(self._head) - len(self._tail), 0)
        marker = _ELISION_TEMPLATE.format(elided=elided)
        return (
            self._head.decode("utf-8", errors="replace")
            + marker
            + self._tail.decode("utf-8", errors="replace")
        )


__all__ = ["MONITOR_MAX_OUTPUT_BYTES", "OutputCapture"]
