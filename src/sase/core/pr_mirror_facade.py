"""Typed Python facade for the Rust PR mirror classifier."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sase.core.rust import require_rust_binding

PR_MIRROR_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class _PullRequestUrl:
    canonical: str
    host: str
    owner: str
    repo: str
    number: int | None
    parsed: bool


@dataclass(frozen=True)
class PullRequestPatchOwner:
    name: str
    pr_origin: str
    status: str
    pr_url: str = ""
    is_reservation: bool = False

    def to_wire(self) -> dict[str, object]:
        return {
            "name": self.name,
            "pr_origin": self.pr_origin,
            "status": self.status,
            "pr_url": self.pr_url,
            "is_reservation": self.is_reservation,
        }


@dataclass(frozen=True)
class PullRequestImportDecision:
    action: str
    pr_origin: str
    status: str
    destination: str
    patch_name: str | None
    marker_name: str | None
    canonical_url: str
    reason: str


def normalize_pull_request_url(url: str) -> _PullRequestUrl:
    """Normalize *url* through the shared Rust PR URL canonicalizer."""

    binding = require_rust_binding("normalize_pull_request_url")
    raw = binding(url)
    if not isinstance(raw, dict):
        raise TypeError("normalize_pull_request_url returned a non-dict payload")
    _assert_schema(raw)
    return _PullRequestUrl(
        canonical=str(raw.get("canonical") or ""),
        host=str(raw.get("host") or ""),
        owner=str(raw.get("owner") or ""),
        repo=str(raw.get("repo") or ""),
        number=_optional_int(raw.get("number")),
        parsed=bool(raw.get("parsed")),
    )


def classify_pull_request(
    request: Mapping[str, object],
) -> PullRequestImportDecision:
    """Classify one provider PR record against local Patch ownership indexes."""

    binding = require_rust_binding("classify_pull_request")
    raw = binding(dict(request))
    if not isinstance(raw, dict):
        raise TypeError("classify_pull_request returned a non-dict payload")
    _assert_schema(raw)
    return PullRequestImportDecision(
        action=str(raw.get("action") or ""),
        pr_origin=str(raw.get("pr_origin") or ""),
        status=str(raw.get("status") or ""),
        destination=str(raw.get("destination") or ""),
        patch_name=_optional_str(raw.get("patch_name")),
        marker_name=_optional_str(raw.get("marker_name")),
        canonical_url=str(raw.get("canonical_url") or ""),
        reason=str(raw.get("reason") or ""),
    )


def _assert_schema(raw: Mapping[str, object]) -> None:
    schema_version = _int_or_default(raw.get("schema_version"), -1)
    if schema_version != PR_MIRROR_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "unsupported PR mirror wire schema version "
            f"{schema_version}; expected {PR_MIRROR_WIRE_SCHEMA_VERSION}"
        )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _int_or_default(value, 0)


def _int_or_default(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str | bytes | bytearray):
        return int(value)
    return default


__all__ = [
    "PR_MIRROR_WIRE_SCHEMA_VERSION",
    "PullRequestImportDecision",
    "PullRequestPatchOwner",
    "classify_pull_request",
    "normalize_pull_request_url",
]
