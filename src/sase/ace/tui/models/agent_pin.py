"""Agent pin tribe — the constant that derives ``pinned``.

Pinning is implemented as ``Agent.tribe == DEFAULT_PINNED_TRIBE`` (no separate
``pinned`` field), so this module holds the canonical tribe string.
"""

from __future__ import annotations

DEFAULT_PINNED_TRIBE = "pinned"
