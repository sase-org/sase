"""Managed-checkout origin healing and reconciliation.

Split out of :mod:`sase.workspace_provider.utils`. Import the public
names from that module rather than depending on this one directly.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.workspace_provider._utils_git import (
    command_output as _command_output,
    git_command_error as _git_command_error,
    git_config_get_all_origin_push_urls as _git_config_get_all_origin_push_urls,
    git_remote_get_origin_push_urls as _git_remote_get_origin_push_urls,
    origin_read_error as _origin_read_error,
    output_lines as _output_lines,
    remote_points_at_path as _remote_points_at_path,
    remote_urls_match as _remote_urls_match,
    run_git_remote_get_url as _run_git_remote_get_url,
    same_path as _same_path,
    set_origin_push_url as _set_origin_push_url,
    set_origin_url as _set_origin_url,
)

_logger = logging.getLogger(__name__)


def heal_clone_origin_if_needed(
    *,
    primary_workspace_dir: str,
    target_checkout_dir: str,
) -> None:
    target_result = _run_git_remote_get_url(target_checkout_dir)
    target_url = target_result.stdout.strip() if target_result.returncode == 0 else ""
    points_at_primary = bool(
        target_url
        and _remote_points_at_path(
            target_url,
            primary_workspace_dir.rstrip("/"),
            cwd=target_checkout_dir,
        )
    )

    primary_result = _run_git_remote_get_url(primary_workspace_dir)
    primary_url = (
        primary_result.stdout.strip() if primary_result.returncode == 0 else ""
    )
    if not primary_url:
        message = _origin_read_error(primary_workspace_dir, primary_result)
        if points_at_primary:
            raise RuntimeError(
                "Existing workspace clone has stale origin pointing at the "
                f"primary checkout, but {message}."
            )
        _logger.warning(
            "Could not verify reusable workspace clone origin for %s: %s",
            target_checkout_dir,
            message,
        )
        return

    if target_url and _remote_urls_match(
        target_url, primary_url, cwd=target_checkout_dir
    ):
        return

    set_result = _set_origin_url(target_checkout_dir, primary_url)
    if set_result.returncode == 0:
        _logger.info(
            "Rewrote reusable workspace clone origin for %s from %r to %r",
            target_checkout_dir,
            target_url or "<unreadable>",
            primary_url,
        )
        return

    detail = _command_output(set_result) or "unknown error"
    _logger.warning(
        "Failed to rewrite reusable workspace clone origin for %s from %r to %r: %s",
        target_checkout_dir,
        target_url or "<unreadable>",
        primary_url,
        detail,
    )
    if points_at_primary:
        raise RuntimeError(
            "Existing workspace clone has stale origin pointing at the primary "
            f"checkout and could not be healed: {detail}"
        )


def _verified_managed_marker(
    checkout_dir: str,
    *,
    primary_workspace_dir: str | None,
) -> tuple[str, bool] | None:
    from sase.workspace_provider.marker import find_marker_from_cwd
    from sase.workspace_provider.registry import (
        WorkspaceRegistryError,
        read_registry_file,
    )

    marker_match = find_marker_from_cwd(checkout_dir)
    if marker_match is None:
        return None
    marker_checkout_dir, marker = marker_match
    marker_primary_dir = marker.primary_workspace_dir.rstrip("/")
    if not marker_primary_dir:
        raise RuntimeError(
            "managed checkout identity could not be verified because the "
            "checkout marker is missing primary_workspace_dir"
        )
    if not marker.registry_path:
        raise RuntimeError(
            "managed checkout identity could not be verified because the "
            "checkout marker is missing registry_path"
        )
    expected_primary_dir = (
        primary_workspace_dir.rstrip("/") if primary_workspace_dir else ""
    )
    if expected_primary_dir and not _same_path(
        Path(marker_primary_dir),
        Path(expected_primary_dir),
    ):
        raise RuntimeError(
            "managed checkout marker primary does not match the expected "
            f"primary checkout: marker={marker_primary_dir}, expected={expected_primary_dir}"
        )

    try:
        registry = read_registry_file(marker.registry_path, strict=True)
    except WorkspaceRegistryError as exc:
        raise RuntimeError(
            "managed checkout identity could not be verified because the "
            f"workspace registry is unreadable: {exc}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            "managed checkout identity could not be verified because the "
            f"workspace registry could not be loaded: {exc}"
        ) from exc
    if registry is None:
        raise RuntimeError(
            "managed checkout identity could not be verified because the "
            f"workspace registry is missing: {marker.registry_path}"
        )

    entry = registry.workspaces.get(str(marker.workspace_num))
    identity_verified = (
        bool(marker.project_key)
        and marker.project_key == registry.project_key
        and entry is not None
        and _same_path(Path(entry.checkout_dir), Path(marker_checkout_dir))
        and _same_path(
            Path(registry.primary_workspace_dir),
            Path(marker_primary_dir),
        )
    )
    if not identity_verified:
        raise RuntimeError(
            "managed checkout identity could not be verified from marker "
            f"and registry for {marker_checkout_dir}"
        )
    return marker_primary_dir, True


def _managed_origin_reconciliation_decision(
    request: Mapping[str, Any],
) -> Mapping[str, Any]:
    from sase.core.rust import require_rust_binding

    decision = require_rust_binding("decide_managed_origin_reconciliation")(
        dict(request)
    )
    if not isinstance(decision, Mapping):
        raise RuntimeError(
            "managed origin reconciliation returned a non-object decision"
        )
    return decision


def _build_managed_origin_request(
    checkout_dir: str,
    primary_workspace_dir: str,
    *,
    identity_verified: bool,
) -> dict[str, Any]:
    checkout_dir = os.path.abspath(checkout_dir)
    primary_workspace_dir = os.path.abspath(primary_workspace_dir)

    primary_result = _run_git_remote_get_url(primary_workspace_dir)
    primary_url = (
        primary_result.stdout.strip() if primary_result.returncode == 0 else ""
    )
    primary_error = (
        None
        if primary_url
        else _origin_read_error(primary_workspace_dir, primary_result)
    )

    target_result = _run_git_remote_get_url(checkout_dir)
    target_url = target_result.stdout.strip() if target_result.returncode == 0 else ""
    target_error = (
        None if target_url else _origin_read_error(checkout_dir, target_result)
    )

    push_result = _git_remote_get_origin_push_urls(checkout_dir)
    effective_push_urls = _output_lines(push_result)
    explicit_result = _git_config_get_all_origin_push_urls(checkout_dir)
    explicit_push_urls = _output_lines(explicit_result)

    return {
        "managed": True,
        "identity_verified": identity_verified,
        "checkout_dir": checkout_dir,
        "primary_checkout_dir": primary_workspace_dir,
        "canonical_remote_url": primary_url or None,
        "canonical_remote_error": primary_error,
        "canonical_remote_points_at_primary": bool(
            primary_url
            and _remote_points_at_path(
                primary_url,
                primary_workspace_dir,
                cwd=primary_workspace_dir,
            )
        ),
        "origin_url": target_url or None,
        "origin_read_error": target_error,
        "origin_points_at_primary": bool(
            target_url
            and _remote_points_at_path(
                target_url,
                primary_workspace_dir,
                cwd=checkout_dir,
            )
        ),
        "origin_matches_canonical": bool(
            target_url
            and primary_url
            and _remote_urls_match(target_url, primary_url, cwd=checkout_dir)
        ),
        "effective_push_urls": effective_push_urls,
        "effective_push_urls_pointing_at_primary": [
            value
            for value in effective_push_urls
            if _remote_points_at_path(
                value,
                primary_workspace_dir,
                cwd=checkout_dir,
            )
        ],
        "explicit_push_urls": explicit_push_urls,
        "explicit_push_urls_pointing_at_primary": [
            value
            for value in explicit_push_urls
            if _remote_points_at_path(
                value,
                primary_workspace_dir,
                cwd=checkout_dir,
            )
        ],
    }


def _assert_origin_no_longer_points_at_primary(
    checkout_dir: str,
    primary_workspace_dir: str,
) -> None:
    origin_result = _run_git_remote_get_url(checkout_dir)
    origin_url = origin_result.stdout.strip() if origin_result.returncode == 0 else ""
    if not origin_url:
        raise RuntimeError(_origin_read_error(checkout_dir, origin_result))
    if _remote_points_at_path(origin_url, primary_workspace_dir, cwd=checkout_dir):
        raise RuntimeError(
            "managed checkout origin still resolves to the primary checkout "
            f"after reconciliation: {origin_url}"
        )

    push_result = _git_remote_get_origin_push_urls(checkout_dir)
    if push_result.returncode != 0:
        raise RuntimeError(
            _git_command_error(
                "could not verify origin push URLs", checkout_dir, push_result
            )
        )
    stale_push_urls = [
        value
        for value in _output_lines(push_result)
        if _remote_points_at_path(value, primary_workspace_dir, cwd=checkout_dir)
    ]
    if stale_push_urls:
        raise RuntimeError(
            "managed checkout origin push destination still resolves to the "
            f"primary checkout after reconciliation: {', '.join(stale_push_urls)}"
        )


def reconcile_managed_checkout_origin(
    checkout_dir: str,
    *,
    primary_workspace_dir: str | None = None,
    assume_managed_checkout: bool = False,
) -> bool:
    """Repair a managed checkout's stale origin before provider selection.

    Only origins or explicit push URLs proven to resolve to the primary
    checkout are rewritten. Unmanaged checkouts, unrelated local bare
    remotes, and non-stale origin configuration are left untouched.
    """
    checkout_dir = os.path.abspath(checkout_dir)
    verified_marker = _verified_managed_marker(
        checkout_dir,
        primary_workspace_dir=primary_workspace_dir,
    )
    if verified_marker is None:
        if not assume_managed_checkout:
            return False
        if not primary_workspace_dir:
            raise RuntimeError(
                "managed checkout origin reconciliation requires a primary "
                "checkout directory"
            )
        resolved_primary_dir = primary_workspace_dir.rstrip("/")
        identity_verified = True
    else:
        resolved_primary_dir, identity_verified = verified_marker

    request = _build_managed_origin_request(
        checkout_dir,
        resolved_primary_dir,
        identity_verified=identity_verified,
    )
    decision = _managed_origin_reconciliation_decision(request)
    action = str(decision.get("action", ""))
    reason = str(decision.get("reason", "managed origin reconciliation failed"))
    if action == "none":
        return False
    if action == "fail":
        raise RuntimeError(reason)
    if action != "rewrite":
        raise RuntimeError(
            f"managed origin reconciliation returned unsupported action: {action}"
        )

    changed = False
    rewrite_origin_url = decision.get("rewrite_origin_url")
    if isinstance(rewrite_origin_url, str) and rewrite_origin_url.strip():
        set_result = _set_origin_url(checkout_dir, rewrite_origin_url)
        if set_result.returncode != 0:
            raise RuntimeError(
                _git_command_error(
                    "could not rewrite managed checkout origin",
                    checkout_dir,
                    set_result,
                )
            )
        changed = True

    rewrite_push_urls = decision.get("rewrite_push_urls", [])
    if rewrite_push_urls is None:
        rewrite_push_urls = []
    if not isinstance(rewrite_push_urls, list):
        raise RuntimeError(
            "managed origin reconciliation returned invalid push URL rewrites"
        )
    for item in rewrite_push_urls:
        if not isinstance(item, Mapping):
            raise RuntimeError(
                "managed origin reconciliation returned invalid push URL rewrite"
            )
        old_url = item.get("old_url")
        new_url = item.get("new_url")
        if not isinstance(old_url, str) or not isinstance(new_url, str):
            raise RuntimeError(
                "managed origin reconciliation returned incomplete push URL rewrite"
            )
        set_result = _set_origin_push_url(checkout_dir, new_url, old_url)
        if set_result.returncode != 0:
            raise RuntimeError(
                _git_command_error(
                    "could not rewrite managed checkout origin push URL",
                    checkout_dir,
                    set_result,
                )
            )
        changed = True

    _assert_origin_no_longer_points_at_primary(
        checkout_dir,
        resolved_primary_dir,
    )
    if changed:
        _logger.info(
            "Reconciled managed checkout origin for %s before provider selection",
            checkout_dir,
        )
    return changed
