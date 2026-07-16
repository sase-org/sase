"""Owned path resolution for neutral and legacy interaction bundles."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sase.core.paths import sase_subdir
from sase.notification_gates.models import (
    GateError,
    validate_identifier,
    validate_relative_path,
)

if TYPE_CHECKING:
    from sase.notification_gates.registry import GateAdapter
    from sase.notifications.models import Notification

INTERACTION_REQUESTS_DIR: Path | None = None

REQUEST_FILENAME = "request.json"
RESPONSE_FILENAME = "response.json"
CANCELLATION_FILENAME = "cancellation.json"
CREATION_JOURNAL_FILENAME = ".creation.json"
CREATION_RESULT_FILENAME = ".creation_result.json"


@dataclass(frozen=True)
class GateBundlePaths:
    """Canonical paths owned by one neutral gate bundle."""

    root: Path
    request: Path
    response: Path
    cancellation: Path
    journal: Path
    creation_result: Path


@dataclass(frozen=True)
class ResolvedGateBundle:
    """Neutral-first bundle resolution with legacy filename projection."""

    kind: str
    root: Path
    request: Path
    response: Path
    cancellation: Path
    legacy: bool


def interaction_requests_dir() -> Path:
    """Return the SASE-owned root for neutral gate bundles."""
    return INTERACTION_REQUESTS_DIR or sase_subdir("interaction_requests")


def bundle_paths(kind: str, request_id: str) -> GateBundlePaths:
    """Return canonical paths after validating kind and request identifiers."""
    safe_kind = validate_identifier(kind, "kind")
    safe_request_id = validate_identifier(request_id, "request_id")
    root = interaction_requests_dir() / safe_kind / safe_request_id
    return GateBundlePaths(
        root=root,
        request=root / REQUEST_FILENAME,
        response=root / RESPONSE_FILENAME,
        cancellation=root / CANCELLATION_FILENAME,
        journal=root / CREATION_JOURNAL_FILENAME,
        creation_result=root / CREATION_RESULT_FILENAME,
    )


def owned_resource_path(bundle_root: Path, relative_path: str) -> Path:
    """Resolve a bundle-relative resource and enforce lexical containment."""
    normalized = validate_relative_path(relative_path, "resource path")
    candidate = bundle_root.joinpath(*normalized.split("/"))
    try:
        candidate.relative_to(bundle_root)
    except ValueError as exc:  # pragma: no cover - lexical validation is primary
        raise GateError(
            "path_escape", "resource path", "resource escapes the request bundle"
        ) from exc
    return candidate


def assert_owned_bundle(bundle_root: Path) -> Path:
    """Return the normalized bundle path if it is under the configured root."""
    owned_root = interaction_requests_dir().expanduser().resolve(strict=False)
    candidate = bundle_root.expanduser().resolve(strict=False)
    try:
        candidate.relative_to(owned_root)
    except ValueError as exc:
        raise GateError(
            "unowned_bundle",
            str(bundle_root),
            "gate bundle is outside the SASE interaction_requests directory",
        ) from exc
    _reject_symlink_components(bundle_root, stop=interaction_requests_dir())
    return candidate


def resolve_notification_bundle(
    notification: Notification,
) -> ResolvedGateBundle | None:
    """Resolve a typed notification to a neutral bundle or its legacy directory."""
    from sase.notification_gates.registry import adapter_for_action

    adapter = adapter_for_action(notification.action)
    if adapter is None:
        return None
    request_id = notification.action_data.get("request_id")
    request_kind = notification.action_data.get("request_kind", adapter.kind)
    if request_id:
        try:
            neutral = bundle_paths(request_kind, request_id)
        except GateError:
            neutral = None
        if neutral is not None and neutral.request.is_file():
            return ResolvedGateBundle(
                kind=adapter.kind,
                root=neutral.root,
                request=neutral.request,
                response=neutral.response,
                cancellation=neutral.cancellation,
                legacy=False,
            )
    return _resolve_legacy_bundle(adapter, notification.action_data)


def _resolve_legacy_bundle(
    adapter: GateAdapter, action_data: dict[str, str]
) -> ResolvedGateBundle | None:
    """Resolve the adapter's in-flight legacy bundle from typed action data."""
    value = action_data.get(adapter.legacy_directory_key)
    if not value or not value.strip():
        return None
    root = Path(value).expanduser()
    return ResolvedGateBundle(
        kind=adapter.kind,
        root=root,
        request=root / adapter.request_filename,
        response=root / adapter.response_filename,
        cancellation=root / CANCELLATION_FILENAME,
        legacy=True,
    )


def _reject_symlink_components(path: Path, *, stop: Path) -> None:
    """Reject existing symlink components below *stop*."""
    absolute = path.expanduser().absolute()
    stop_absolute = stop.expanduser().absolute()
    try:
        relative = absolute.relative_to(stop_absolute)
    except ValueError:
        return
    current = stop_absolute
    for part in relative.parts:
        current /= part
        try:
            if current.is_symlink():
                raise GateError(
                    "symlink_not_allowed",
                    str(current),
                    "symlinks are not allowed inside gate bundles",
                )
        except OSError as exc:
            raise GateError("path_validation_failed", str(current), str(exc)) from exc


def open_regular_nofollow(path: Path) -> int:
    """Open a regular file without following a final symlink."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise GateError(
            "unsafe_file", str(path), f"cannot safely open {path}: {exc}"
        ) from exc
    try:
        if not os.path.isfile(f"/proc/self/fd/{fd}"):
            raise GateError(
                "unsafe_file", str(path), "owned resource is not a regular file"
            )
    except BaseException:
        os.close(fd)
        raise
    return fd


__all__ = [
    "CANCELLATION_FILENAME",
    "CREATION_JOURNAL_FILENAME",
    "CREATION_RESULT_FILENAME",
    "INTERACTION_REQUESTS_DIR",
    "REQUEST_FILENAME",
    "RESPONSE_FILENAME",
    "GateBundlePaths",
    "ResolvedGateBundle",
    "assert_owned_bundle",
    "bundle_paths",
    "interaction_requests_dir",
    "open_regular_nofollow",
    "owned_resource_path",
    "resolve_notification_bundle",
]
