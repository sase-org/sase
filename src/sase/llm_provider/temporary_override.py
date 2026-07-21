"""Temporary, per-alias LLM provider/model overrides.

A small, process-shared state file that lets the user set time-bound
temporary overrides for model aliases (the ``default`` alias plus any
role/user alias) without editing ``~/.config/sase/sase.yml``.

The state lives at ``~/.sase/llm_override.json`` so all sase processes
on the same machine see the same active overrides. The on-disk schema is
versioned: ``{"version": 2, "overrides": {"<alias>": {...}}}``. A legacy
v1 flat object (a single, top-level override) is migrated on read into
``overrides.default`` so an override set by an older build keeps working.
Writes are atomic (temp file + ``os.replace``); reads are best-effort
self-cleaning — expired or malformed entries are pruned and the file is
removed once no override remains.

The ``default`` override keeps its existing behavior: it only changes the
no-``%model`` launch default (explicit ``%model`` directives and an
explicit ``provider_name`` argument to :func:`invoke_agent` still win, and
an explicit ``@default`` reference ignores it). Overrides on any other
alias take effect wherever that alias is resolved (see
:func:`sase.llm_provider.config.resolve_model_alias`).
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import fcntl
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home

from .config import DEFAULT_MODEL_ALIAS_NAME
from .types import ModelTier

_STATE_FILENAME = "llm_override.json"
_LOCK_FILENAME = "llm_override.lock"

#: On-disk schema version for the per-alias override state file.
_STATE_VERSION = 2


def _state_path() -> Path:
    """Return the absolute path to the override state file.

    Resolved lazily so ``$SASE_HOME`` and test redirection are honored per-call.
    """
    return sase_home() / _STATE_FILENAME


@contextmanager
def _locked_state() -> Iterator[None]:
    """Serialize state reads that may clean up and all read/modify/write cycles."""
    lock_path = sase_home() / _LOCK_FILENAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


@dataclass(frozen=True)
class TemporaryLLMOverride:
    """Active temporary default provider/model override."""

    provider: str
    model: str
    raw_model: str
    created_at: float
    expires_at: float | None
    source: str


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
# State file IO
# ---------------------------------------------------------------------------


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write *data* as JSON to *path* atomically (temp file + replace + fsync)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _delete_state_best_effort() -> None:
    try:
        _state_path().unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _read_state_dict() -> dict | None:
    """Read and JSON-parse the state file's top-level object.

    Returns the parsed dict, or ``None`` when the file is missing, unreadable,
    not valid JSON, or not a JSON object. Unparseable / non-object files are
    deleted best-effort so a corrupt file never wedges future launches.
    """
    path = _state_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        return None

    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        _delete_state_best_effort()
        return None

    if not isinstance(data, dict):
        _delete_state_best_effort()
        return None
    return data


def _extract_raw_entries(data: dict) -> tuple[dict[str, Any] | None, bool]:
    """Split a parsed state dict into ``{alias: entry_dict}`` + a canonical flag.

    Handles both schema versions:

    * **v2** (``{"version": 2, "overrides": {...}}``) — the ``overrides`` map is
      returned directly. ``canonical`` is ``True`` only when the file is already
      in fully canonical v2 form (correct version, a dict of string-keyed
      entries, and no stray top-level keys), so a steady-state read never
      rewrites the file.
    * **v1** (a flat, top-level single override) — migrated in-memory into
      ``{"default": data}`` with ``canonical=False`` so the next write upgrades
      the file to v2.

    Returns ``(None, True)`` when the structure is unrecoverable (a v2 file whose
    ``overrides`` is not a dict), signalling the caller to delete the file.
    """
    if data.get("version") == _STATE_VERSION or "overrides" in data:
        overrides = data.get("overrides")
        if not isinstance(overrides, dict):
            return None, True
        cleaned = {k: v for k, v in overrides.items() if isinstance(k, str)}
        canonical = (
            data.get("version") == _STATE_VERSION
            and len(cleaned) == len(overrides)
            and set(data.keys()) <= {"version", "overrides"}
        )
        return cleaned, canonical

    # Legacy v1 flat object: a single top-level override → overrides.default.
    return {DEFAULT_MODEL_ALIAS_NAME: data}, False


def _entry_from_dict(entry: object) -> TemporaryLLMOverride | None:
    """Validate one raw override entry into a :class:`TemporaryLLMOverride`.

    Returns ``None`` for any structurally invalid entry (missing or wrong-typed
    fields) so a single bad entry never crashes a launch. Unknown extra keys
    (for example retired ``pre_override_*`` snapshot keys) are ignored.
    """
    if not isinstance(entry, dict):
        return None
    required = ("provider", "model", "raw_model", "created_at", "source")
    if not all(k in entry for k in required):
        return None
    if not all(
        isinstance(entry[k], str) for k in ("provider", "model", "raw_model", "source")
    ):
        return None
    created_at = entry["created_at"]
    if not _is_finite_number(created_at):
        return None
    expires_at = entry.get("expires_at")
    if expires_at is not None and not _is_finite_number(expires_at):
        return None
    return TemporaryLLMOverride(
        provider=entry["provider"],
        model=entry["model"],
        raw_model=entry["raw_model"],
        created_at=float(created_at),
        expires_at=float(expires_at) if expires_at is not None else None,
        source=entry["source"],
    )


def _is_finite_number(value: object) -> bool:
    """Return whether *value* is a finite JSON timestamp number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _serialize_overrides(overrides: dict[str, TemporaryLLMOverride]) -> dict:
    """Render the active override map as the canonical v2 state dict."""
    return {
        "version": _STATE_VERSION,
        "overrides": {alias: asdict(o) for alias, o in overrides.items()},
    }


def _load_active_overrides_unlocked(
    now: float | None = None,
) -> dict[str, TemporaryLLMOverride]:
    """Return the active (non-expired) per-alias overrides, self-cleaning state.

    Performs the v1→v2 read migration, drops invalid/expired entries, and keeps
    the file honest: it deletes the file when no active override remains and
    rewrites it (atomically) whenever the on-disk contents differ from the
    pruned/migrated result. A steady-state read of a canonical file with only
    active entries performs no write.
    """
    data = _read_state_dict()
    if data is None:
        return {}

    raw_entries, canonical = _extract_raw_entries(data)
    if raw_entries is None:
        _delete_state_best_effort()
        return {}

    current = time.time() if now is None else now
    active: dict[str, TemporaryLLMOverride] = {}
    changed = not canonical
    for alias, entry in raw_entries.items():
        override = _entry_from_dict(entry)
        if override is None:
            changed = True
            continue
        if override.expires_at is not None and current >= override.expires_at:
            changed = True
            continue
        active[alias] = override

    if not active:
        _delete_state_best_effort()
        return {}
    if changed:
        _atomic_write_json(_state_path(), _serialize_overrides(active))
    return active


def _load_active_overrides(
    now: float | None = None,
) -> dict[str, TemporaryLLMOverride]:
    """Return active overrides while serializing self-cleaning file writes."""
    with _locked_state():
        return _load_active_overrides_unlocked(now)


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
    return _load_active_overrides(now)


def get_active_alias_override(
    alias: str,
    now: float | None = None,
) -> TemporaryLLMOverride | None:
    """Return the active override for *alias*, or ``None`` if none/expired."""
    return _load_active_overrides(now).get(alias)


def set_alias_override(
    alias: str,
    raw_model: str,
    duration_seconds: float | None,
    *,
    source: str,
) -> TemporaryLLMOverride:
    """Set a temporary override on *alias* for *raw_model* lasting *duration_seconds*.

    Overrides on other aliases are preserved (and any expired ones pruned).
    *raw_model* is resolved via the existing ``resolve_model_provider()`` rules:
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
    from .registry import resolve_model_provider

    resolved_provider, resolved_model = resolve_model_provider(cleaned)
    if resolved_provider is None:
        resolved_provider, _ = resolve_effective_default_provider_model()

    override = TemporaryLLMOverride(
        provider=resolved_provider,
        model=resolved_model,
        raw_model=cleaned,
        created_at=created_at,
        expires_at=expires_at,
        source=source.strip(),
    )

    with _locked_state():
        overrides = _load_active_overrides_unlocked(now=created_at)
        overrides[cleaned_alias] = override
        _atomic_write_json(_state_path(), _serialize_overrides(overrides))
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

    with _locked_state():
        data = _read_state_dict()
        if data is None:
            return False
        raw_entries, _ = _extract_raw_entries(data)
        if raw_entries is None:
            _delete_state_best_effort()
            return False
        if cleaned_alias not in raw_entries:
            return False

        rebuilt: dict[str, TemporaryLLMOverride] = {}
        for key, entry in raw_entries.items():
            if key == cleaned_alias:
                continue
            override = _entry_from_dict(entry)
            if override is not None:
                rebuilt[key] = override
        if rebuilt:
            _atomic_write_json(_state_path(), _serialize_overrides(rebuilt))
        else:
            _delete_state_best_effort()
        return True


# ---------------------------------------------------------------------------
# Public API — back-compat ``default`` wrappers
# ---------------------------------------------------------------------------
#
# The no-``%model`` default launch lane and the existing TUI override indicator
# operate on a single global override. These wrappers keep that surface working
# by targeting the ``default`` key in the per-alias map, so default behavior is
# unchanged.


def get_active_temporary_override(
    now: float | None = None,
) -> TemporaryLLMOverride | None:
    """Return the active ``default`` override, or ``None`` if none/expired."""
    return get_active_alias_override(DEFAULT_MODEL_ALIAS_NAME, now)


def set_temporary_override(
    raw_model: str,
    duration_seconds: float | None,
    *,
    source: str,
) -> TemporaryLLMOverride:
    """Set the ``default`` temporary override (back-compat wrapper)."""
    return set_alias_override(
        DEFAULT_MODEL_ALIAS_NAME, raw_model, duration_seconds, source=source
    )


def clear_temporary_override() -> bool:
    """Clear the ``default`` temporary override (back-compat wrapper)."""
    return clear_alias_override(DEFAULT_MODEL_ALIAS_NAME)


def resolve_effective_default_provider_model(
    model_tier: ModelTier = "large",
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
) -> tuple[str, str]:
    """Return the ``(provider_name, model_name)`` to use for new launches.

    Precedence for a launch with no explicit ``%model`` directive:

    1. a launch-family ``default`` alias override;
    2. an active primary temporary override (the user's recent explicit choice);
    3. otherwise the ``@default`` alias — a configured
       ``llm_provider.model_aliases.builtin.default`` target, or the configured/
       autodetected provider's ``resolve_model_name(model_tier)`` default.

    This keeps the temporary override winning the "new launch default" slot
    while routing every no-directive launch through the ``@default`` alias so a
    configured default model is never silently bypassed.
    """
    from .launch_alias_overrides import active_launch_alias_overrides

    launch_overrides = active_launch_alias_overrides(model_alias_overrides)
    if DEFAULT_MODEL_ALIAS_NAME in launch_overrides:
        from .registry import (
            get_configured_default_provider_name,
            resolve_model_provider,
        )

        provider, model = resolve_model_provider(
            "@default", launch_overrides, consume=consume
        )
        return provider or get_configured_default_provider_name(), model

    override = get_active_temporary_override()
    if override is not None:
        return override.provider, override.model

    from .registry import resolve_default_alias_provider_model

    return resolve_default_alias_provider_model(
        model_tier,
        launch_overrides,
        consume=consume,
    )


def resolve_effective_default_provider_model_with_effort(
    model_tier: ModelTier = "large",
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
) -> tuple[str, str, str | None]:
    """Resolve the effective launch default including alias-borne effort."""
    from .launch_alias_overrides import active_launch_alias_overrides

    launch_overrides = active_launch_alias_overrides(model_alias_overrides)
    if DEFAULT_MODEL_ALIAS_NAME in launch_overrides:
        from .registry import (
            get_configured_default_provider_name,
            resolve_model_provider_with_effort,
        )

        provider, model, effort = resolve_model_provider_with_effort(
            "@default", launch_overrides, consume=consume
        )
        return provider or get_configured_default_provider_name(), model, effort

    override = get_active_temporary_override()
    if override is not None:
        return override.provider, override.model, None

    from .registry import resolve_default_alias_provider_model_with_effort

    return resolve_default_alias_provider_model_with_effort(
        model_tier,
        launch_overrides,
        consume=consume,
    )
