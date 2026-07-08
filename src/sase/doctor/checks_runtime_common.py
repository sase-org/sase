"""Shared helpers for runtime-facing ``sase doctor`` checks."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any


def which_from_env(env: Mapping[str, str]) -> Callable[[str], str | None]:
    path = env.get("PATH", "")
    return lambda command: shutil.which(command, path=path)


def optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def resolve_command_from_env(command: str | None, env: Mapping[str, str]) -> str | None:
    if not command:
        return None
    expanded = os.path.expanduser(command)
    resolved = which_from_env(env)(expanded)
    if resolved:
        return resolved
    if os.sep in expanded:
        path = Path(expanded)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def safe_resolve(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


__all__ = [
    "optional_str",
    "resolve_command_from_env",
    "safe_resolve",
    "which_from_env",
]
