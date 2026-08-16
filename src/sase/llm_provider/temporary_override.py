"""Temporary, per-alias LLM provider/model overrides.

A small, process-shared state file that lets the user set time-bound
temporary overrides for model aliases and launch settings without editing
``~/.config/sase/sase.yml``.

Each entry snapshots the resolved provider/model and optional canonical effort
while retaining the original raw reference. Alias overrides take effect
wherever that alias is resolved, while namespaced setting overrides cover
launch defaults. Explicit ``%model`` directives and an explicit
``provider_name`` argument to :func:`invoke_agent` still win (see
:func:`sase.llm_provider.config.resolve_model_alias`).

This module is the public entry point. The pieces behind it live in siblings:

* :mod:`sase.llm_provider.temporary_override_state` — the versioned,
  lock-serialized, self-cleaning state file at ``~/.sase/llm_override.json``.
* :mod:`sase.llm_provider.temporary_override_peek` — the lock-free, time-gated
  display read used by keystroke paths.
* :mod:`sase.llm_provider.temporary_override_defaults` — effective launch
  default resolution, which folds the namespaced default-launch setting
  override into ``llm_provider.default_model`` precedence.
"""

from __future__ import annotations

import math
import re
import time

from .model_launch_settings import (
    DEFAULT_MODEL_FIELD,
    launch_model_setting_override_key,
)
from .temporary_override_defaults import (
    resolve_effective_default_provider_model,
    resolve_effective_default_provider_model_with_effort,
    resolve_effective_default_provider_model_with_trail,
)
from .temporary_override_peek import (
    peek_active_alias_overrides,
    peek_active_temporary_override,
)
from .temporary_override_state import (
    TemporaryLLMOverride,
    load_active_overrides,
    remove_alias_override,
    store_alias_override,
)

__all__ = [
    "TemporaryLLMOverride",
    "clear_alias_override",
    "clear_temporary_override",
    "get_active_alias_override",
    "get_active_alias_overrides",
    "get_active_temporary_override",
    "parse_override_duration",
    "peek_active_alias_overrides",
    "peek_active_temporary_override",
    "resolve_effective_default_provider_model",
    "resolve_effective_default_provider_model_with_effort",
    "resolve_effective_default_provider_model_with_trail",
    "set_alias_override",
    "set_alias_override_until",
    "set_temporary_override",
]


# ---------------------------------------------------------------------------
# Duration parsing
# ---------------------------------------------------------------------------

_DURATION_UNITS = {"h": 3600.0, "m": 60.0, "s": 1.0}
_DURATION_TOKEN_RE = re.compile(r"(\d+)\s*([hms])")
_DURATION_FULL_RE = re.compile(r"^(?:\d+\s*[hms]\s*)+$")


def parse_override_duration(value: str) -> float | None:
    """Parse a user-facing duration into seconds.

    Accepts: ``"15m"``, ``"1h"``, ``"1h30m"``, ``"90m"``, ``"2h15m30s"``.
    Bare numbers default to minutes (``"45"`` → 2700.0). The case-insensitive
    sentinel ``"until cleared"`` (and ``"until_cleared"``) returns ``None`` —
    meaning "no expiry, persists until cleared".

    Raises:
        ValueError: If the input is empty or doesn't match a known format.
    """
    if not value or not value.strip():
        raise ValueError("duration is empty")

    token = value.strip().lower()
    if token in ("until cleared", "until_cleared"):
        return None

    if token.isdigit():
        return float(int(token) * 60)

    compact = token.replace(" ", "")
    if not _DURATION_FULL_RE.match(compact):
        raise ValueError(f"invalid duration: {value!r}")

    total = 0.0
    for amount, unit in _DURATION_TOKEN_RE.findall(compact):
        total += int(amount) * _DURATION_UNITS[unit]
    if total <= 0:
        raise ValueError(f"duration must be positive: {value!r}")
    return total


# ---------------------------------------------------------------------------
# Public API — per-alias overrides
# ---------------------------------------------------------------------------


def get_active_alias_overrides(
    now: float | None = None,
) -> dict[str, TemporaryLLMOverride]:
    """Return every currently-active override, keyed by alias name.

    Expired or malformed entries are pruned and the state file is removed once
    no active override remains (best-effort self-cleaning), so callers never
    observe stale overrides.
    """
    return load_active_overrides(now)


def get_active_alias_override(
    alias: str,
    now: float | None = None,
) -> TemporaryLLMOverride | None:
    """Return the active override for *alias*, or ``None`` if none/expired."""
    return load_active_overrides(now).get(alias)


def set_alias_override(
    alias: str,
    raw_model: str,
    duration_seconds: float | None,
    *,
    source: str,
) -> TemporaryLLMOverride:
    """Set a temporary override on *alias* for *raw_model* lasting *duration_seconds*.

    Overrides on other aliases are preserved (and any expired ones pruned).
    *raw_model* is resolved via the existing
    ``resolve_model_provider_with_effort()`` rules:
    ``"codex/o3"`` selects codex explicitly, ``"opus"`` infers claude from
    plugin metadata, and an unknown bare model is accepted but runs on the
    current effective default provider (mirroring ``%model``).

    *duration_seconds=None* writes an override with no expiry (the
    "until cleared" case).

    Raises:
        ValueError: If *alias*, *raw_model*, or *source* is empty/whitespace, or
            *duration_seconds* is non-positive.
    """
    created_at = time.time()
    if duration_seconds is not None and (
        not math.isfinite(duration_seconds) or duration_seconds <= 0
    ):
        raise ValueError("duration_seconds must be finite and positive or None")
    expires_at = created_at + duration_seconds if duration_seconds is not None else None
    return _write_alias_override(
        alias,
        raw_model,
        created_at=created_at,
        expires_at=expires_at,
        source=source,
    )


def set_alias_override_until(
    alias: str,
    raw_model: str,
    expires_at: float,
    *,
    source: str,
) -> TemporaryLLMOverride:
    """Set a temporary override on *alias* until the exact Unix *expires_at*.

    The supplied expiry is stored unchanged. It must be finite and strictly
    later than the operation's captured creation time. Overrides on other
    aliases are preserved, with the same provider/model resolution and atomic
    v2 serialization used by :func:`set_alias_override`.

    Raises:
        ValueError: If any text argument is empty/whitespace, or *expires_at*
            is non-finite or no longer in the future.
    """
    created_at = time.time()
    if not math.isfinite(expires_at):
        raise ValueError("expires_at must be finite")
    if expires_at <= created_at:
        raise ValueError("expires_at must be in the future")
    return _write_alias_override(
        alias,
        raw_model,
        created_at=created_at,
        expires_at=expires_at,
        source=source,
    )


def _write_alias_override(
    alias: str,
    raw_model: str,
    *,
    created_at: float,
    expires_at: float | None,
    source: str,
) -> TemporaryLLMOverride:
    """Resolve, validate, and atomically write one alias override."""
    if not alias or not alias.strip():
        raise ValueError("alias is empty")
    if not raw_model or not raw_model.strip():
        raise ValueError("raw_model is empty")
    if not source or not source.strip():
        raise ValueError("source is empty")
    if expires_at is not None and (
        not math.isfinite(expires_at) or expires_at <= created_at
    ):
        raise ValueError("expires_at must be finite and later than created_at")

    cleaned_alias = alias.strip()
    cleaned = raw_model.strip()

    # Lazy import to avoid an import cycle (registry imports from this
    # module's siblings via __init__.py).
    from .registry import (
        get_default_provider_name,
        raise_if_provider_temporarily_disabled,
        resolve_model_provider_with_effort,
    )

    resolved_provider, resolved_model, resolved_effort = (
        resolve_model_provider_with_effort(cleaned)
    )
    if resolved_provider is None:
        resolved_provider = get_default_provider_name()
    raise_if_provider_temporarily_disabled(resolved_provider)

    override = TemporaryLLMOverride(
        provider=resolved_provider,
        model=resolved_model,
        raw_model=cleaned,
        created_at=created_at,
        expires_at=expires_at,
        source=source.strip(),
        effort=resolved_effort,
    )

    store_alias_override(cleaned_alias, override)
    return override


def clear_alias_override(alias: str) -> bool:
    """Clear the temporary override on *alias*.

    Returns ``True`` if an entry for *alias* was present and removed (whether or
    not it had already expired), ``False`` if no such entry existed. Other
    aliases' overrides are preserved; the file is deleted once empty.
    """
    cleaned_alias = (alias or "").strip()
    if not cleaned_alias:
        return False
    return remove_alias_override(cleaned_alias)


# ---------------------------------------------------------------------------
# Public API — back-compat launch-default wrappers
# ---------------------------------------------------------------------------
#
# The no-``%model`` default launch lane and the existing TUI override indicator
# operate on a single global override. These wrappers keep that surface working
# while storing the value under a namespaced launch-setting key, so a
# user-defined custom ``@default`` alias cannot collide with launch-default
# state.


def get_active_temporary_override(
    now: float | None = None,
) -> TemporaryLLMOverride | None:
    """Return the active default-launch override, or ``None`` if none/expired."""
    return get_active_alias_override(
        launch_model_setting_override_key(DEFAULT_MODEL_FIELD),
        now,
    )


def set_temporary_override(
    raw_model: str,
    duration_seconds: float | None,
    *,
    source: str,
) -> TemporaryLLMOverride:
    """Set the default-launch temporary override (back-compat wrapper)."""
    return set_alias_override(
        launch_model_setting_override_key(DEFAULT_MODEL_FIELD),
        raw_model,
        duration_seconds,
        source=source,
    )


def clear_temporary_override() -> bool:
    """Clear the default-launch temporary override (back-compat wrapper)."""
    return clear_alias_override(launch_model_setting_override_key(DEFAULT_MODEL_FIELD))
