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

from .types import ModelTier

_STATE_FILENAME = "llm_override.json"


def _state_path() -> Path:
    """Return the absolute path to the override state file.

    Resolved lazily so ``conftest.py``'s ``~/.sase/`` redirection (and
    user-set ``$HOME``) is honored per-call.
    """
    return Path(os.path.expanduser(f"~/.sase/{_STATE_FILENAME}"))


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


def _load_state() -> dict | None:
    """Load and validate the state file.

    Returns the parsed dict on success, or ``None`` if the file is
    missing, unreadable, malformed, or missing required fields.
    Malformed files are deleted best-effort.
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

    required = ("provider", "model", "raw_model", "created_at", "source")
    if not all(k in data for k in required):
        _delete_state_best_effort()
        return None
    if not all(
        isinstance(data[k], str) for k in ("provider", "model", "raw_model", "source")
    ):
        _delete_state_best_effort()
        return None
    if not isinstance(data["created_at"], (int, float)):
        _delete_state_best_effort()
        return None

    expires_at = data.get("expires_at")
    if expires_at is not None and not isinstance(expires_at, (int, float)):
        _delete_state_best_effort()
        return None

    return data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_active_temporary_override(
    now: float | None = None,
) -> TemporaryLLMOverride | None:
    """Return the active override, or ``None`` if none/expired.

    Expired or malformed state files are deleted best-effort so callers
    don't need to wait for a TUI session to clean them up.
    """
    data = _load_state()
    if data is None:
        return None

    expires_at = data.get("expires_at")
    if expires_at is not None:
        current = time.time() if now is None else now
        if current >= expires_at:
            _delete_state_best_effort()
            return None

    return TemporaryLLMOverride(
        provider=data["provider"],
        model=data["model"],
        raw_model=data["raw_model"],
        created_at=float(data["created_at"]),
        expires_at=float(expires_at) if expires_at is not None else None,
        source=data["source"],
    )


def set_temporary_override(
    raw_model: str,
    duration_seconds: float | None,
    *,
    source: str,
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
    from .registry import get_default_provider_name, resolve_model_provider

    resolved_provider, resolved_model = resolve_model_provider(cleaned)
    if resolved_provider is None:
        resolved_provider = get_default_provider_name()

    now = time.time()
    expires_at = now + duration_seconds if duration_seconds is not None else None

    override = TemporaryLLMOverride(
        provider=resolved_provider,
        model=resolved_model,
        raw_model=cleaned,
        created_at=now,
        expires_at=expires_at,
        source=source.strip(),
    )
    _atomic_write_json(_state_path(), asdict(override))
    return override


def clear_temporary_override() -> bool:
    """Remove the override state file.

    Returns ``True`` if a file was removed, ``False`` if none existed.
    """
    path = _state_path()
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
