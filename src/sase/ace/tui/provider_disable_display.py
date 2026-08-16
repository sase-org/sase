"""Display helpers for temporary provider disables."""

from __future__ import annotations

import re

from sase.llm_provider.provider_disable import TemporaryProviderDisable

_SOURCE_WHITESPACE_RE = re.compile(r"\s+")


def provider_disable_provenance_label(disable: TemporaryProviderDisable) -> str:
    """Return a user-facing provenance label for a provider disable."""
    source = disable.source.strip()
    normalized = source.casefold()
    if normalized == "ace":
        return "manual"
    if normalized == "usage_limit":
        return "usage-limit automatic"
    readable = source.replace("_", " ").replace("-", " ")
    return _SOURCE_WHITESPACE_RE.sub(" ", readable).strip() or "unknown source"


__all__ = ["provider_disable_provenance_label"]
