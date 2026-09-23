"""Plugin probe floors and CLI fingerprints for adaptive usage refresh."""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

MIN_USAGE_PROBE_INTERVAL_SECONDS = 60.0
MAX_USAGE_PROBE_INTERVAL_SECONDS = 86_400.0

_floors_cache: tuple[tuple[Any, ...], dict[str, float]] | None = None


def usage_probe_floor(provider: str) -> float | None:
    """Return the declared probe floor for *provider*, if any."""
    return usage_probe_floors().get(provider)


def usage_probe_floors() -> dict[str, float]:
    """Return ``{provider: floor_seconds}`` for providers declaring a floor.

    Memoized per config token so repeated admission checks do not rebuild
    registry metadata on every tick.
    """
    global _floors_cache  # noqa: PLW0603

    from sase.config.core import current_config_token

    token = current_config_token()
    cached = _floors_cache
    if cached is not None and cached[0] == token:
        return dict(cached[1])
    floors = _load_probe_floors()
    _floors_cache = (token, floors)
    return dict(floors)


def _load_probe_floors() -> dict[str, float]:
    from sase.llm_provider.registry import get_llm_metadata_payload

    try:
        payload = get_llm_metadata_payload()
    except Exception:
        return {}
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        return {}
    floors: dict[str, float] = {}
    for name, metadata in providers.items():
        if not isinstance(metadata, dict):
            continue
        capabilities = metadata.get("usage_capabilities")
        if not isinstance(capabilities, dict):
            continue
        floor = _validated_floor(capabilities.get("min_probe_interval_seconds"))
        if floor is not None:
            floors[str(name)] = floor
    return floors


def _validated_floor(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if (
        number != number
        or number in (float("inf"), float("-inf"))
        or number < MIN_USAGE_PROBE_INTERVAL_SECONDS
        or number > MAX_USAGE_PROBE_INTERVAL_SECONDS
    ):
        return None
    return number


def usage_cli_fingerprint(provider: str) -> str | None:
    """Return ``"<path>:<mtime_ns>:<size>"`` for *provider*'s CLI, if found.

    The executable is resolved exactly as admission readiness resolves it,
    including the Codex NVM-aware resolver. ``None`` means no fingerprint
    (no CLI configured or not found on disk).
    """
    command = resolve_provider_cli_command(provider)
    if not command:
        return None
    candidate: Path | None = None
    direct = Path(command)
    try:
        if direct.is_file():
            candidate = direct
    except OSError:
        return None
    if candidate is None:
        resolved = shutil.which(command)
        if not resolved:
            return None
        candidate = Path(resolved)
    try:
        stat = candidate.stat()
    except OSError:
        return None
    return f"{candidate}:{stat.st_mtime_ns}:{stat.st_size}"


def resolve_provider_cli_command(
    provider: str, metadata: Mapping[str, Any] | None = None
) -> str:
    """Resolve the CLI command readiness checks inspect.

    *metadata* is the provider's registry metadata; it is looked up when
    omitted so one-argument callers keep working.
    """
    if provider == "codex":
        from sase.llm_provider.codex import resolve_codex_executable

        return resolve_codex_executable()
    resolved: Mapping[str, Any] = metadata if isinstance(metadata, Mapping) else {}
    if metadata is None:
        try:
            from sase.llm_provider.registry import get_llm_metadata_payload

            payload = get_llm_metadata_payload()
            providers = payload.get("providers")
            if isinstance(providers, dict):
                raw = providers.get(provider)
                if isinstance(raw, dict):
                    resolved = raw
        except Exception:
            resolved = {}
    token = re.sub(r"[^A-Za-z0-9]+", "_", provider).strip("_").upper()
    override = os.environ.get(f"SASE_{token}_PATH", "").strip()
    cli_name = resolved.get("autodetect_cli_name")
    return override or (str(cli_name).strip() if cli_name else "")


__all__ = [
    "MAX_USAGE_PROBE_INTERVAL_SECONDS",
    "MIN_USAGE_PROBE_INTERVAL_SECONDS",
    "resolve_provider_cli_command",
    "usage_cli_fingerprint",
    "usage_probe_floor",
    "usage_probe_floors",
]
