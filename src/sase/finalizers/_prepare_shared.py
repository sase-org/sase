"""Shared public helpers for conditional completion preparation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import shlex
from pathlib import Path
from typing import Any

from sase.finalizers.declaration import FinalizerDeclarationError


@dataclass(frozen=True)
class PreparedCompletion:
    """One persisted, host-sealed conditional completion intent."""

    intent: dict[str, Any]
    preview: dict[str, Any]
    intent_ref: str
    path: Path


def command_argv(command: object) -> list[str]:
    """Normalize a verification command into an argv list."""

    if isinstance(command, str):
        parts = shlex.split(command)
    elif isinstance(command, Sequence) and not isinstance(command, bytes | bytearray):
        parts = [str(part) for part in command]
    else:
        raise FinalizerDeclarationError(
            "verification command must be an argv list or a shell string",
            code="invalid_verification_command",
        )
    if not parts:
        raise FinalizerDeclarationError(
            "verification command must not be empty",
            code="invalid_verification_command",
        )
    return parts
