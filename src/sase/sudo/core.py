"""Thin binding seam for sudo manifest, risk, and ledger contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from sase.notification_gates.models import GateError
from sase.core.rust import require_rust_binding


class SudoCoreBinding(Protocol):
    """Core-backed operations the sudo workflow needs."""

    def validate_manifest(self, manifest: Mapping[str, Any]) -> dict[str, Any]:
        """Return the canonical Rust sudo manifest wire object."""

    def manifest_sha256(self, manifest: Mapping[str, Any]) -> str:
        """Return the canonical manifest digest."""

    def risk_badges(self, manifest: Mapping[str, Any]) -> tuple[str, ...]:
        """Return display badges for the reviewed command set."""

    def validate_ledger(
        self,
        ledger: Mapping[str, Any],
        manifest: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the canonical Rust sudo ledger wire object."""

    def validate_handshake(
        self,
        handshake: Mapping[str, Any],
        manifest: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the canonical Rust sudo_exec_started handshake."""


@dataclass(frozen=True)
class _RustSudoCoreBinding:
    """Lazy wrapper around the required ``sase_core_rs`` sudo bindings."""

    def validate_manifest(self, manifest: Mapping[str, Any]) -> dict[str, Any]:
        return _dict_binding("sudo_validate_manifest", dict(manifest))

    def manifest_sha256(self, manifest: Mapping[str, Any]) -> str:
        try:
            return str(require_rust_binding("sudo_manifest_sha256")(dict(manifest)))
        except Exception as exc:
            raise _gate_error("invalid_sudo_manifest", "manifest", exc) from exc

    def risk_badges(self, manifest: Mapping[str, Any]) -> tuple[str, ...]:
        try:
            assessments = require_rust_binding("sudo_derive_risk_badges")(
                dict(manifest)
            )
        except Exception as exc:
            raise _gate_error("invalid_sudo_manifest", "manifest", exc) from exc
        badges: set[str] = set()
        if isinstance(assessments, Sequence) and not isinstance(assessments, str):
            for assessment in assessments:
                if not isinstance(assessment, Mapping):
                    continue
                for badge in assessment.get("badges") or ():
                    if isinstance(badge, str) and badge:
                        badges.add(badge)
                if bool(assessment.get("lockout_prone")):
                    badges.add("lockout-prone")
        return tuple(sorted(badges))

    def validate_ledger(
        self,
        ledger: Mapping[str, Any],
        manifest: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            binding = require_rust_binding("sudo_validate_ledger")
            result = (
                binding(dict(ledger), dict(manifest))
                if manifest is not None
                else binding(dict(ledger))
            )
        except Exception as exc:
            raise _gate_error("invalid_sudo_ledger", "ledger", exc) from exc
        if not isinstance(result, Mapping):
            raise GateError(
                "invalid_sudo_ledger",
                "ledger",
                "sase_core_rs returned a non-object sudo ledger",
            )
        return dict(result)

    def validate_handshake(
        self,
        handshake: Mapping[str, Any],
        manifest: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            binding = require_rust_binding("sudo_validate_handshake")
            result = (
                binding(dict(handshake), dict(manifest))
                if manifest is not None
                else binding(dict(handshake))
            )
        except Exception as exc:
            raise _gate_error("invalid_sudo_handshake", "handshake", exc) from exc
        if not isinstance(result, Mapping):
            raise GateError(
                "invalid_sudo_handshake",
                "handshake",
                "sase_core_rs returned a non-object sudo handshake",
            )
        return dict(result)


def _dict_binding(name: str, value: dict[str, Any]) -> dict[str, Any]:
    try:
        result = require_rust_binding(name)(value)
    except Exception as exc:
        raise _gate_error("invalid_sudo_manifest", "manifest", exc) from exc
    if not isinstance(result, Mapping):
        raise GateError(
            "invalid_sudo_manifest",
            "manifest",
            f"sase_core_rs returned a non-object result for {name}",
        )
    return dict(result)


def _gate_error(code: str, target: str, exc: BaseException) -> GateError:
    return GateError(code, target, str(exc))


DEFAULT_SUDO_CORE = _RustSudoCoreBinding()


__all__ = ["DEFAULT_SUDO_CORE", "SudoCoreBinding"]
