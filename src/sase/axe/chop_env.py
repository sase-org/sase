"""Environment composition and secret-reference resolution for chop scripts."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path

type ChopSecretReference = dict[str, str]
type ChopEnvValue = str | ChopSecretReference

_PASS_TIMEOUT_SECONDS = 15
_TARGET_ENV_INVALID = re.compile(r"[^A-Za-z0-9_]+")


class _ChopSecretResolutionError(ValueError):
    """Raised when a configured chop secret reference cannot be resolved."""


def resolve_chop_env(
    values: Mapping[str, ChopEnvValue],
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Resolve literal and referenced chop environment values at dispatch.

    Secret values are deliberately absent from error messages. References are
    resolved as late as possible so config inventories and persisted run state
    retain only the non-secret reference.
    """
    process_env = os.environ if environ is None else environ
    return {
        name: _resolve_chop_env_value(name, value, environ=process_env)
        for name, value in values.items()
    }


def secret_reference_description(value: ChopEnvValue) -> str | None:
    """Return a non-secret description of a configured reference."""
    if not isinstance(value, dict) or len(value) != 1:
        return None
    provider, reference = next(iter(value.items()))
    if provider not in {"env", "file", "pass"} or not reference:
        return None
    return f"{provider}:{reference}"


def chop_target_env(target_key: str, target: Mapping[str, object]) -> dict[str, str]:
    """Project target fields into deterministic ``SASE_CHOP_TARGET_*`` vars."""
    result = {"SASE_CHOP_TARGET_KEY": target_key}
    for raw_name in sorted(target):
        suffix = _TARGET_ENV_INVALID.sub("_", raw_name).strip("_").upper()
        if not suffix:
            continue
        env_name = f"SASE_CHOP_TARGET_{suffix}"
        if env_name == "SASE_CHOP_TARGET_KEY":
            # The reserved stable identity wins over a target field named key.
            continue
        if env_name in result:
            raise ValueError(
                f"target fields collide when projected to environment: {raw_name}"
            )
        value = target[raw_name]
        if value is None:
            rendered = ""
        elif isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, (str, int, float)):
            rendered = str(value)
        else:
            rendered = json.dumps(value, sort_keys=True, separators=(",", ":"))
        result[env_name] = rendered
    return result


def _resolve_chop_env_value(
    name: str,
    value: ChopEnvValue,
    *,
    environ: Mapping[str, str],
) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict) or len(value) != 1:
        raise _ChopSecretResolutionError(
            f"could not resolve chop env {name}: invalid secret reference"
        )

    provider, reference = next(iter(value.items()))
    if not isinstance(reference, str) or not reference.strip():
        raise _ChopSecretResolutionError(
            f"could not resolve chop env {name}: blank {provider} reference"
        )
    if provider == "env":
        resolved = environ.get(reference, "")
        if not resolved:
            raise _ChopSecretResolutionError(
                f"could not resolve chop env {name}: environment variable "
                f"{reference} is not set"
            )
        return resolved
    if provider == "file":
        path = Path(reference).expanduser()
        try:
            resolved = path.read_text(encoding="utf-8").rstrip("\r\n")
        except OSError as exc:
            raise _ChopSecretResolutionError(
                f"could not resolve chop env {name}: file {path} could not be read: "
                f"{exc.strerror or type(exc).__name__}"
            ) from exc
        if not resolved:
            raise _ChopSecretResolutionError(
                f"could not resolve chop env {name}: file {path} is empty"
            )
        return resolved
    if provider == "pass":
        try:
            completed = subprocess.run(
                ["pass", "show", reference],
                capture_output=True,
                text=True,
                timeout=_PASS_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise _ChopSecretResolutionError(
                f"could not resolve chop env {name}: pass entry {reference} "
                "could not be read"
            ) from exc
        first_line = completed.stdout.splitlines()[0] if completed.stdout else ""
        if completed.returncode != 0 or not first_line:
            raise _ChopSecretResolutionError(
                f"could not resolve chop env {name}: pass entry {reference} "
                "is unavailable"
            )
        return first_line

    raise _ChopSecretResolutionError(
        f"could not resolve chop env {name}: unknown secret provider {provider}"
    )


__all__ = [
    "ChopEnvValue",
    "ChopSecretReference",
    "chop_target_env",
    "resolve_chop_env",
    "secret_reference_description",
]
