"""Bounded streaming capture for a monitored command's output."""

from __future__ import annotations

#: Retain at most this many bytes of output (head + tail).
MONITOR_MAX_OUTPUT_BYTES = 2 * 1024 * 1024

_ELISION_TEMPLATE = "\n… {elided} bytes elided …\n"


class OutputCapture:
    """Retain a bounded in-memory view of a monitored command's bytes.

    The full live log is written separately through the monitor's bounded log
    pipe. This accumulator keeps the head + tail view used by terminal
    markers and follow-up prompts, decoding only when the retained text is
    requested.
    """

    def __init__(
        self,
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

    def append_bytes(self, chunk: bytes) -> None:
        """Append *chunk* to the retained output view."""
        self._total_bytes += len(chunk)
        if not self._truncated:
            self._buffer += chunk
            if len(self._buffer) > self._max_bytes:
                self._truncated = True
                self._head = bytes(self._buffer[: self._half])
                self._tail = bytearray(self._buffer[-self._half :])
                self._buffer = bytearray()
        else:
            self._tail += chunk
            overflow = len(self._tail) - self._half
            if overflow > 0:
                del self._tail[:overflow]

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
