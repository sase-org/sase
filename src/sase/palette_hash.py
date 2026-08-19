"""Stable hash-into-a-frozen-palette index shared by accent colors.

Project accents, provider-kind accents, and monitor-status pair accents all
need the same ``sha256(key)[:8] % len(palette)`` primitive. Keeping it in
one place is what makes those colors identical across the TUI and both
CLIs, and what keeps a later palette-hash tweak from moving only one of
them.

This is hash-only: two keys may land on the same slot. Callers that need
uniqueness (enabled-project accents, whose set is enumerable) probe
forward themselves. Open sets such as monitor status pairs must not,
because a pair's color has to stay the same regardless of which other
pairs happen to be on screen.
"""

from __future__ import annotations

import hashlib


def hash_palette_index(key: str, modulo: int) -> int:
    """Return a stable palette index for ``key`` in a palette of size ``modulo``.

    The index is ``int.from_bytes(sha256(utf-8 key)[:8], "big") % modulo``.
    """
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % modulo
