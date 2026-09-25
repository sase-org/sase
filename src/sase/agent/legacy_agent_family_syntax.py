"""Compatibility normalizers for retired agent-family user syntax.

Keep every temporary alias for the agent-session terminology migration in this
module. Durable readers may request the unconditional legacy path; authored
input follows the ``legacy_agent_family_syntax`` sunset flag.
"""

from __future__ import annotations

from collections.abc import Mapping

from sase.agent._agent_session_attach_types import (
    AGENT_SESSION_ATTACH_ENV,
    LEGACY_AGENT_FAMILY_ATTACH_ENV,
)
from sase.feature_flags import FeatureFlag, current_flags

_LEGACY_DIRECTIVE_KEY = "family"
_SESSION_DIRECTIVE_KEY = "session"
_LEGACY_FORK = "family"
_SESSION_FORK = "session"


def _legacy_agent_family_syntax_enabled() -> bool:
    """Return whether retired user-authored agent-family syntax is accepted."""
    return current_flags().enabled(FeatureFlag.legacy_agent_family_syntax)


def _retired_agent_family_syntax_message(legacy: str, replacement: str) -> str:
    """Return the consistent replacement hint for one retired spelling."""
    return f"{legacy} is retired; use {replacement}"


def normalize_agent_session_directive_args(
    named_args: Mapping[str, str],
) -> dict[str, str]:
    """Normalize the old ``family=`` %id keyword to ``session=`` when allowed."""
    normalized = dict(named_args)
    has_legacy = _LEGACY_DIRECTIVE_KEY in normalized
    has_canonical = _SESSION_DIRECTIVE_KEY in normalized
    if has_legacy and has_canonical:
        raise ValueError("family= and session= cannot be combined; use only session=.")
    if not has_legacy:
        return normalized
    if not _legacy_agent_family_syntax_enabled():
        raise ValueError(_retired_agent_family_syntax_message("family=", "session="))
    normalized[_SESSION_DIRECTIVE_KEY] = normalized.pop(_LEGACY_DIRECTIVE_KEY)
    return normalized


def normalize_agent_session_fork(
    value: object,
    *,
    persisted: bool = False,
) -> object:
    """Normalize a gate fork value, preserving old durable records unconditionally."""
    if value != _LEGACY_FORK:
        return value
    if persisted or _legacy_agent_family_syntax_enabled():
        return _SESSION_FORK
    raise ValueError(
        _retired_agent_family_syntax_message('"fork": "family"', '"fork": "session"')
    )


def normalize_persisted_agent_session_fork(value: object) -> object:
    """Normalize a pre-rename durable gate fork regardless of the sunset flag."""
    return normalize_agent_session_fork(value, persisted=True)


def agent_session_attach_env_value(env: Mapping[str, str]) -> str | None:
    """Read the canonical attach payload, or a permitted legacy fallback."""
    canonical = env.get(AGENT_SESSION_ATTACH_ENV)
    if canonical:
        return canonical
    legacy = env.get(LEGACY_AGENT_FAMILY_ATTACH_ENV)
    if legacy and _legacy_agent_family_syntax_enabled():
        return legacy
    return None


__all__ = [
    "agent_session_attach_env_value",
    "normalize_agent_session_directive_args",
    "normalize_agent_session_fork",
    "normalize_persisted_agent_session_fork",
]
