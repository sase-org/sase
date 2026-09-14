"""Thin binding seam for sudo manifest hashing and risk badges."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from sase.notification_gates.durability import canonical_json_bytes


class SudoCoreBinding(Protocol):
    """Core-backed operations the sudo workflow needs."""

    def manifest_sha256(self, manifest: Mapping[str, Any]) -> str:
        """Return the canonical manifest digest."""

    def risk_badges(self, commands: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
        """Return display badges for the reviewed command set."""


@dataclass(frozen=True)
class _PythonSudoCoreBinding:
    """Local seam used until the Rust binding surface lands."""

    def manifest_sha256(self, manifest: Mapping[str, Any]) -> str:
        return hashlib.sha256(canonical_json_bytes(dict(manifest))).hexdigest()

    def risk_badges(self, commands: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
        badges: set[str] = {"sudo"}
        joined = " ".join(
            " ".join(str(part) for part in command.get("argv", []))
            for command in commands
        ).lower()
        if any(word in joined for word in ("apt", "dnf", "yum", "pacman", "brew")):
            badges.add("packages")
        if any(word in joined for word in ("systemctl", "service", "launchctl")):
            badges.add("services")
        if any(word in joined for word in (" rm ", " chmod ", " chown ", " mkfs ")):
            badges.add("destructive")
        if any(word in joined for word in ("curl", "wget", "scp", "rsync")):
            badges.add("network")
        return tuple(sorted(badges))


DEFAULT_SUDO_CORE = _PythonSudoCoreBinding()


__all__ = ["DEFAULT_SUDO_CORE", "SudoCoreBinding"]
