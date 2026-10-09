"""Shared helpers for the ``test_dispatch_federation_*`` test modules.

Split from ``tests.test_dispatch_federation``. Public helpers used by more
than one split module live here under public names so no new module imports
a ``_``-prefixed name from another new module.
"""

from __future__ import annotations

__all__ = ["installation_id"]


def installation_id(hex_char: str) -> str:
    """Build a deterministic pinned installation id for tests."""
    return f"sase_inst_v1_{hex_char * 64}"
