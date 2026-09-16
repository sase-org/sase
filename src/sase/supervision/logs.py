"""Bounded-log output pumping for a supervised child's combined stdout/stderr."""

from collections.abc import Callable
from typing import BinaryIO

_READ_CHUNK_BYTES = 64 * 1024


def pump_output(
    stream: BinaryIO,
    append: Callable[[bytes], None],
    *,
    chunk_size: int = _READ_CHUNK_BYTES,
) -> None:
    """Drain *stream* into *append* until EOF, then close the stream.

    Prefers ``read1()`` over ``read()`` when available: ``read1()`` returns
    whatever bytes one underlying read produced instead of blocking for
    *chunk_size* bytes or EOF, so a quiet child's output still reaches the
    log promptly.
    """
    read_chunk = getattr(stream, "read1", stream.read)
    try:
        while True:
            chunk = read_chunk(chunk_size)
            if not chunk:
                break
            append(chunk)
    finally:
        stream.close()
