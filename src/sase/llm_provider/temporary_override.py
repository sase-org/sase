"""Temporary default LLM provider/model override.

A small, process-shared state file that lets the user set a temporary
default provider/model for new agent launches without editing
``~/.config/sase/sase.yml``.

The state lives at ``~/.sase/llm_override.json`` so all sase processes
on the same machine see the same active override. Writes are atomic
(temp file + ``os.replace``); reads are best-effort self-cleaning —
expired or malformed files are deleted on next access.

The override only changes the *default* provider/model. Explicit
``%model`` prompt directives and an explicit ``provider_name`` argument
to :func:`invoke_agent` continue to win.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from sase.core.paths import sase_home

from .types import ModelRole, ModelTier

_STATE_FILENAME_BY_ROLE: dict[ModelRole, str] = {
    "primary": "llm_override.json",
    "worker": "llm_worker_override.json",
}


def _state_filename(role: ModelRole) -> str:
    try:
        return _STATE_FILENAME_BY_ROLE[role]
    except KeyError:
        raise ValueError(f"unknown model role: {role!r}") from None


def _state_path(role: ModelRole = "primary") -> Path:
    """Return the absolute path to the override state file.

    Resolved lazily so ``$SASE_HOME`` and test redirection are honored per-call.
    """
    return sase_home() / _state_filename(role)


@dataclass(frozen=True)
class TemporaryLLMOverride:
    """Active temporary default provider/model override.

    ``pre_override_*`` captures the ``(provider, model)`` that was the
    effective default *immediately before* this override was set. It's
    consumed by the ``"other"`` alias short-circuit in
    :func:`sase.llm_provider.config.resolve_model_alias` so that
    ``%model:@other`` resolves to the displaced model rather than the
    statically-configured alias target. Legacy state files (written
    before this field existed) leave all three as ``None``.
    """

    provider: str
    model: str
    raw_model: str
    created_at: float
    expires_at: float | None
    source: str
    pre_override_provider: str | None = None
    pre_override_model: str | None = None
    pre_override_raw_model: str | None = None


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


def _delete_state_best_effort(role: ModelRole = "primary") -> None:
    try:
        _state_path(role).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _load_state(role: ModelRole = "primary") -> dict | None:
    """Load and validate the state file.

    Returns the parsed dict on success, or ``None`` if the file is
    missing, unreadable, malformed, or missing required fields.
    Malformed files are deleted best-effort.
    """
    path = _state_path(role)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        return None

    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        _delete_state_best_effort(role)
        return None

    if not isinstance(data, dict):
        _delete_state_best_effort(role)
        return None

    required = ("provider", "model", "raw_model", "created_at", "source")
    if not all(k in data for k in required):
        _delete_state_best_effort(role)
        return None
    if not all(
        isinstance(data[k], str) for k in ("provider", "model", "raw_model", "source")
    ):
        _delete_state_best_effort(role)
        return None
    if not isinstance(data["created_at"], (int, float)):
        _delete_state_best_effort(role)
        return None

    expires_at = data.get("expires_at")
    if expires_at is not None and not isinstance(expires_at, (int, float)):
        _delete_state_best_effort(role)
        return None

    for key in (
        "pre_override_provider",
        "pre_override_model",
        "pre_override_raw_model",
    ):
        value = data.get(key)
        if value is not None and not isinstance(value, str):
            data[key] = None

    return data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_active_temporary_override(
    now: float | None = None,
    *,
    role: ModelRole = "primary",
) -> TemporaryLLMOverride | None:
    """Return the active override, or ``None`` if none/expired.

    Expired or malformed state files are deleted best-effort so callers
    don't need to wait for a TUI session to clean them up.
    """
    data = _load_state(role)
    if data is None:
        return None

    expires_at = data.get("expires_at")
    if expires_at is not None:
        current = time.time() if now is None else now
        if current >= expires_at:
            _delete_state_best_effort(role)
            return None

    return TemporaryLLMOverride(
        provider=data["provider"],
        model=data["model"],
        raw_model=data["raw_model"],
        created_at=float(data["created_at"]),
        expires_at=float(expires_at) if expires_at is not None else None,
        source=data["source"],
        pre_override_provider=data.get("pre_override_provider"),
        pre_override_model=data.get("pre_override_model"),
        pre_override_raw_model=data.get("pre_override_raw_model"),
    )


def set_temporary_override(
    raw_model: str,
    duration_seconds: float | None,
    *,
    source: str,
    role: ModelRole = "primary",
) -> TemporaryLLMOverride:
    """Write a temporary override for *raw_model* lasting *duration_seconds*.

    *raw_model* is resolved via the existing ``resolve_model_provider()``
    rules: ``"codex/o3"`` selects codex explicitly, ``"opus"`` infers
    claude from plugin metadata, and an unknown bare model is accepted
    but runs on the current default provider (mirroring ``%model``).

    *duration_seconds=None* writes an override with no expiry (the
    "until cleared" case).

    Raises:
        ValueError: If *raw_model* is empty/whitespace, *duration_seconds*
            is non-positive, or *source* is empty.
    """
    if not raw_model or not raw_model.strip():
        raise ValueError("raw_model is empty")
    if duration_seconds is not None and duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive or None")
    if not source or not source.strip():
        raise ValueError("source is empty")

    cleaned = raw_model.strip()

    # Lazy import to avoid an import cycle (registry imports from this
    # module's siblings via __init__.py).
    from .registry import resolve_model_provider

    # Snapshot the model that's effectively active right now, BEFORE we
    # overwrite the state file. If a prior override is on disk it's
    # honored (via resolve_effective_default_provider_model); otherwise
    # the configured default is captured. The "other" alias resolves
    # against this snapshot for the duration of the new override.
    prior = get_active_temporary_override(role=role)
    if role == "worker":
        snap_provider, snap_model = resolve_effective_worker_provider_model()
    else:
        snap_provider, snap_model = resolve_effective_default_provider_model()
    pre_override_provider: str | None = snap_provider
    pre_override_model: str | None = snap_model
    pre_override_raw_model: str | None = (
        prior.raw_model if prior is not None else snap_model
    )

    resolved_provider, resolved_model = resolve_model_provider(cleaned)
    if resolved_provider is None:
        resolved_provider = snap_provider

    now = time.time()
    expires_at = now + duration_seconds if duration_seconds is not None else None

    override = TemporaryLLMOverride(
        provider=resolved_provider,
        model=resolved_model,
        raw_model=cleaned,
        created_at=now,
        expires_at=expires_at,
        source=source.strip(),
        pre_override_provider=pre_override_provider,
        pre_override_model=pre_override_model,
        pre_override_raw_model=pre_override_raw_model,
    )
    _atomic_write_json(_state_path(role), asdict(override))
    return override


def clear_temporary_override(*, role: ModelRole = "primary") -> bool:
    """Remove the override state file.

    Returns ``True`` if a file was removed, ``False`` if none existed.
    """
    path = _state_path(role)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return True


def resolve_effective_default_provider_model(
    model_tier: ModelTier = "large",
) -> tuple[str, str]:
    """Return the ``(provider_name, model_name)`` to use for new launches.

    If an active temporary override exists, its concrete provider/model
    is returned. Otherwise resolves via the configured default provider
    and its ``resolve_model_name(model_tier)``.
    """
    override = get_active_temporary_override()
    if override is not None:
        return override.provider, override.model

    from .registry import get_default_provider_name, get_provider

    provider_name = get_default_provider_name()
    provider = get_provider(provider_name)
    return provider_name, provider.resolve_model_name(model_tier)


@dataclass(frozen=True)
class WorkerModelResolution:
    """Resolved worker-lane provider/model plus the provenance of the choice.

    ``source`` is one of:

    - ``"override"``: an active worker temporary override supplied the lane.
    - ``"config"``: a matching ``llm_provider.worker_models`` entry supplied
      the lane; ``matched_key`` is the key that matched (exact
      ``provider/model``, bare model, or provider) and ``configured_target``
      is its raw configured value.
    - ``"primary"``: no override/config matched, so the worker lane falls
      through to the supplied primary lane.

    ``primary_provider``/``primary_model`` echo the primary lane the worker
    was resolved against, regardless of which branch won.
    """

    provider: str
    model: str
    source: str
    primary_provider: str
    primary_model: str
    matched_key: str | None = None
    configured_target: str | None = None


def resolve_worker_provider_model_for_primary(
    primary_provider: str,
    primary_model: str,
    model_tier: ModelTier = "large",
) -> WorkerModelResolution:
    """Resolve the worker-lane provider/model for a known primary lane.

    Precedence mirrors :func:`resolve_effective_worker_provider_model`: an
    active worker temporary override wins first, then a matching
    ``llm_provider.worker_models`` entry for ``primary_provider``/
    ``primary_model``, then the supplied primary lane as a fallback.

    Unlike :func:`resolve_effective_worker_provider_model`, the primary lane
    is supplied by the caller rather than read from the current effective
    default, so this can resolve the worker lane for a *specific* planner
    context (e.g. a plan handoff) rather than the global current default.

    ``model_tier`` is accepted for parity with the sibling resolvers; the
    worker mapping lookup itself does not depend on it.
    """
    override = get_active_temporary_override(role="worker")
    if override is not None:
        return WorkerModelResolution(
            provider=override.provider,
            model=override.model,
            source="override",
            primary_provider=primary_provider,
            primary_model=primary_model,
        )

    from .config import get_configured_worker_model_entry_for_primary
    from .registry import (
        get_configured_default_provider_name,
        resolve_model_provider,
    )

    entry = get_configured_worker_model_entry_for_primary(
        primary_provider,
        primary_model,
    )
    if entry is not None and entry[1].strip() != "worker":
        matched_key, configured = entry
        resolved_provider, resolved_model = resolve_model_provider(configured)
        if resolved_model.strip() != "worker":
            if resolved_provider is None:
                resolved_provider = get_configured_default_provider_name()
            return WorkerModelResolution(
                provider=resolved_provider,
                model=resolved_model,
                source="config",
                primary_provider=primary_provider,
                primary_model=primary_model,
                matched_key=matched_key,
                configured_target=configured,
            )

    return WorkerModelResolution(
        provider=primary_provider,
        model=primary_model,
        source="primary",
        primary_provider=primary_provider,
        primary_model=primary_model,
    )


def resolve_effective_worker_provider_model(
    model_tier: ModelTier = "large",
) -> tuple[str, str]:
    """Return the ``(provider_name, model_name)`` for worker-lane launches.

    Worker-specific state wins first. If no worker-model mapping matches
    the current primary lane, the worker lane falls through to that primary
    lane.
    """
    primary_provider, primary_model = resolve_effective_default_provider_model(
        model_tier
    )
    resolution = resolve_worker_provider_model_for_primary(
        primary_provider,
        primary_model,
        model_tier,
    )
    return resolution.provider, resolution.model
