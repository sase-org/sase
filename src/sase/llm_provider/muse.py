"""Meta Muse Code (`muse`) LLM provider implementation.

This module is the stable public import path (``sase.llm_provider.muse``)
and re-exports the provider class. The implementation lives in focused
siblings:

- ``muse_provider`` -- :class:`MuseProvider` and its invoke loop
- ``_muse_directive`` -- single-turn directive and wait-guard helpers
- ``_muse_launch`` -- executable, sandbox, and prompt-file helpers

(Model catalog, short aliases, advisories, and tier defaults live in the
bundled ``models.yml`` manifest; see ``model_manifest.py``. Both tiers map
to the full-price model on purpose — a tier mapping is SASE's own default
choice of model, so it must never send a user's proprietary source into
Meta's training corpus on the user's behalf.)
"""

from __future__ import annotations

from .muse_provider import MuseProvider

__all__ = ["MuseProvider"]
