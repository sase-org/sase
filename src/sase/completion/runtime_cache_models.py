"""Shared models and constants for the runtime grammar cache."""

from __future__ import annotations

from dataclasses import dataclass

CACHE_SCHEMA_VERSION = 1
CACHE_FORMAT_REVISION = 1


class CompletionCacheError(RuntimeError):
    """User-facing failure while resolving the runtime grammar cache."""


@dataclass(frozen=True, slots=True)
class RuntimeGrammarStatus:
    """Read-only assessment of one shell's runtime grammar cache."""

    shell: str
    status: str
    path: str | None
    structural_digest: str | None
    drift_reasons: tuple[str, ...] = ()
