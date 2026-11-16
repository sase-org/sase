"""Flag-on trust decision for project-local executable config.

Implements the sunset-flag-on path of ``evaluate_local_trust_for_path``.
Helpers in this file are used only by ``evaluate_with_flag_on`` and stay
private here. State shared with the evaluation entry point lives as public
names in ``_local_trust_enforcement_shared``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import threading
from typing import Any

from sase.config._local_trust_enforcement_shared import (
    LocalTrustEvaluation,
    checkout_root_for_local_path,
    trust_evaluation_guard,
)

log = logging.getLogger(__name__)

_warned_signatures: set[tuple[str, str, str]] = set()
_warned_lock = threading.RLock()

_lower_macros_cache_key: tuple[Any, ...] | None = None
_lower_macros_cache_value: tuple[dict[str, Any], dict[str, Any]] | None = None
_lower_macros_cache_generation: int | None = None
_lower_macros_cache_lock = threading.RLock()


def _allow_command(requested_path: str, identity: str, allow_root: Path | None) -> str:
    """Return the ``sase config trust allow`` command that records *identity*."""
    target = requested_path
    if allow_root is not None:
        try:
            from sase.config.local_trust_management import acknowledgment_target_path

            target = str(acknowledgment_target_path(allow_root, identity))
        except Exception:
            target = str(allow_root)
    return f"sase config trust allow {target}"


def _logical_location(root: Path, selected: Path) -> str:
    """Return the stable project-relative config choice included in digests."""
    try:
        from sase.config.local_trust_management import logical_config_location_for_trust

        return logical_config_location_for_trust(root, selected)
    except Exception:
        try:
            relative = os.path.abspath(selected).removeprefix(
                os.path.abspath(root) + os.sep
            )
            return relative.replace(os.sep, "/")
        except Exception:
            return selected.name


def _project_identity_for(root: Path, config_path: Path) -> str:
    """Resolve the versioned identity management uses for acknowledgments."""
    from sase.config.local_trust_management import project_identity_for_config

    return project_identity_for_config(root, config_path)


def _lower_macros_cache_token() -> tuple[Any, ...] | None:
    """Return the cache key for the lower-layer macro/workflow memo."""
    try:
        from sase.config import _cache as config_cache
        from sase.config.core import current_config_token

        token = current_config_token()
        generation = config_cache.config_cache_generation
        default_id = (
            0
            if config_cache.default_config_cache is None
            else id(config_cache.default_config_cache)
        )
        plugin_id = (
            0
            if config_cache.plugin_configs_cache is None
            else id(config_cache.plugin_configs_cache)
        )
        return (token, generation, default_id, plugin_id)
    except Exception:
        return None


def _lower_macros_and_workflows() -> tuple[dict[str, Any], dict[str, Any]]:
    """Return lower-layer macros/workflows without triggering filtering."""
    global _lower_macros_cache_key, _lower_macros_cache_value
    global _lower_macros_cache_generation
    try:
        from sase.config import _cache as config_cache

        key = _lower_macros_cache_token()
        generation = config_cache.config_cache_generation
        if key is not None:
            with _lower_macros_cache_lock:
                if (
                    _lower_macros_cache_key == key
                    and _lower_macros_cache_generation == generation
                    and _lower_macros_cache_value is not None
                ):
                    cached_macros, cached_workflows = _lower_macros_cache_value
                    return dict(cached_macros), dict(cached_workflows)
    except Exception:
        key = None
        generation = None
    try:
        from sase.config.core import load_merged_config_for_local_path

        with trust_evaluation_guard():
            lower = load_merged_config_for_local_path(None)
    except Exception:
        return {}, {}
    macros = lower.get("macros")
    workflows = lower.get("workflows")
    result = (
        dict(macros) if isinstance(macros, dict) else {},
        dict(workflows) if isinstance(workflows, dict) else {},
    )
    if key is not None:
        try:
            from sase.config import _cache as config_cache

            with _lower_macros_cache_lock:
                if config_cache.config_cache_generation == generation:
                    _lower_macros_cache_key = key
                    _lower_macros_cache_value = (
                        dict(result[0]),
                        dict(result[1]),
                    )
                    _lower_macros_cache_generation = generation
        except Exception:
            pass
    return result


def _deduplicated_warning(
    identity: str | None, digest: str, reason: str, message: str
) -> str | None:
    """Return *message* once per (identity, digest, reason); else None."""
    key = (identity or "-", digest, reason)
    with _warned_lock:
        if key in _warned_signatures:
            return None
        _warned_signatures.add(key)
    log.warning("%s", message)
    return message


def evaluate_with_flag_on(
    local_path: Path, layer: dict[str, Any]
) -> LocalTrustEvaluation:
    """Evaluate one non-empty local layer while the sunset flag is on."""
    from sase.config.local_trust import (
        decide_local_command_trust,
        filter_trusted_local_layer,
        project_local_commands,
    )

    requested_path = str(local_path)
    found_root = checkout_root_for_local_path(local_path)
    allow_root: Path | None = None
    if found_root is None:
        try:
            canonical = str(local_path.expanduser().resolve(strict=False))
        except Exception:
            canonical = requested_path
        identity = f"checkout:v1:{canonical}"
        logical: str | None = local_path.name
    else:
        try:
            canonical_root = found_root.expanduser().resolve(strict=False)
            selected = local_path.expanduser().resolve(strict=False)
        except Exception:
            canonical_root = found_root
            selected = local_path
        allow_root = canonical_root
        try:
            identity = _project_identity_for(canonical_root, selected)
        except Exception as exc:
            log.debug("Local trust identity failed closed: %s", exc, exc_info=True)
            identity = f"checkout:v1:{canonical_root}"
        try:
            logical = _logical_location(canonical_root, selected)
        except Exception:
            logical = local_path.name
    lower_macros, lower_workflows = _lower_macros_and_workflows()
    try:
        projection = project_local_commands(
            layer,
            lower_macros=lower_macros,
            lower_workflows=lower_workflows,
            source="local_config",
            config_path=logical,
        )
    except Exception as exc:
        message = (
            f"Local commands in {requested_path} were skipped: cannot project "
            f"command-bearing content ({exc}); run "
            f"`{_allow_command(requested_path, identity, allow_root)}` "
            "after review."
        )
        warning = _deduplicated_warning(identity, "projection-error", str(exc), message)
        return LocalTrustEvaluation(
            enabled=True,
            trusted=False,
            effective_layer={},
            removed_paths=("commit_hooks", "file_hooks", "macros", "workflows"),
            status="untrusted",
            reason=f"cannot project local commands: {exc}",
            digest="",
            acknowledged_digest=None,
            identity=identity,
            config_path=requested_path,
            logical_path=logical,
            warning=warning,
        )
    if not projection.projection:
        return LocalTrustEvaluation(
            enabled=True,
            trusted=True,
            effective_layer=dict(layer),
            removed_paths=(),
            status="trusted",
            reason="no command-bearing local content",
            digest=projection.digest,
            acknowledged_digest=None,
            identity=identity,
            config_path=requested_path,
            logical_path=logical,
            warning=None,
            policy_version=projection.policy_version,
        )
    try:
        from sase.config.local_trust_management import local_trust_store_snapshot

        snapshot = local_trust_store_snapshot(identity)
    except Exception as exc:
        message = (
            f"Local commands in {requested_path} were skipped: trust store is "
            f"unavailable ({exc}); run "
            f"`{_allow_command(requested_path, identity, allow_root)}` "
            "after review."
        )
        warning = _deduplicated_warning(
            identity, projection.digest, "store-unavailable", message
        )
        try:
            filtered = filter_trusted_local_layer(
                layer,
                trusted=False,
                lower_macros=lower_macros,
                lower_workflows=lower_workflows,
                source="local_config",
                config_path=logical,
            )
            effective = dict(filtered.effective_layer)
            removed = tuple(filtered.removed_paths)
        except Exception:
            effective = {}
            removed = tuple(projection.blocked_paths)
        return LocalTrustEvaluation(
            enabled=True,
            trusted=False,
            effective_layer=effective,
            removed_paths=removed,
            status="untrusted",
            reason=f"trust store unavailable: {exc}",
            digest=projection.digest,
            acknowledged_digest=None,
            identity=identity,
            config_path=requested_path,
            logical_path=logical,
            warning=warning,
            policy_version=projection.policy_version,
        )
    record = snapshot.get("record") if isinstance(snapshot, dict) else None
    acknowledged = record.get("digest") if isinstance(record, dict) else None
    acknowledged_policy = (
        record.get("policy_version") if isinstance(record, dict) else None
    )
    store_status = snapshot.get("status") if isinstance(snapshot, dict) else None
    store_reason = snapshot.get("reason") if isinstance(snapshot, dict) else None
    if store_status != "available":
        try:
            filtered = filter_trusted_local_layer(
                layer,
                trusted=False,
                lower_macros=lower_macros,
                lower_workflows=lower_workflows,
                source="local_config",
                config_path=logical,
            )
            effective = dict(filtered.effective_layer)
            removed = tuple(filtered.removed_paths)
        except Exception:
            effective = {}
            removed = tuple(projection.blocked_paths)
        detail = str(store_reason or "trust store is unavailable or unsafe")
        message = (
            f"Local commands in {requested_path} were skipped: {detail}; run "
            f"`{_allow_command(requested_path, identity, allow_root)}` "
            "after review."
        )
        warning = _deduplicated_warning(identity, projection.digest, detail, message)
        return LocalTrustEvaluation(
            enabled=True,
            trusted=False,
            effective_layer=effective,
            removed_paths=removed,
            status="untrusted",
            reason=detail,
            digest=projection.digest,
            acknowledged_digest=(
                acknowledged if isinstance(acknowledged, str) else None
            ),
            identity=identity,
            config_path=requested_path,
            logical_path=logical,
            warning=warning,
            policy_version=projection.policy_version,
        )
    try:
        decision = decide_local_command_trust(
            projection.digest,
            acknowledged if isinstance(acknowledged, str) else None,
            acknowledged_policy_version=(
                acknowledged_policy if isinstance(acknowledged_policy, int) else None
            ),
        )
    except Exception as exc:
        try:
            filtered = filter_trusted_local_layer(
                layer,
                trusted=False,
                lower_macros=lower_macros,
                lower_workflows=lower_workflows,
                source="local_config",
                config_path=logical,
            )
            effective = dict(filtered.effective_layer)
            removed = tuple(filtered.removed_paths)
        except Exception:
            effective = {}
            removed = tuple(projection.blocked_paths)
        message = (
            f"Local commands in {requested_path} were skipped: cannot decide "
            f"trust ({exc}); run "
            f"`{_allow_command(requested_path, identity, allow_root)}` "
            "after review."
        )
        warning = _deduplicated_warning(identity, projection.digest, str(exc), message)
        return LocalTrustEvaluation(
            enabled=True,
            trusted=False,
            effective_layer=effective,
            removed_paths=removed,
            status="untrusted",
            reason=f"cannot decide trust: {exc}",
            digest=projection.digest,
            acknowledged_digest=(
                acknowledged if isinstance(acknowledged, str) else None
            ),
            identity=identity,
            config_path=requested_path,
            logical_path=logical,
            warning=warning,
            policy_version=projection.policy_version,
        )
    if decision.trusted:
        try:
            filtered = filter_trusted_local_layer(
                layer,
                trusted=True,
                lower_macros=lower_macros,
                lower_workflows=lower_workflows,
                source="local_config",
                config_path=logical,
            )
            effective = dict(filtered.effective_layer)
        except Exception:
            effective = dict(layer)
        return LocalTrustEvaluation(
            enabled=True,
            trusted=True,
            effective_layer=effective,
            removed_paths=(),
            status="trusted",
            reason=decision.reason,
            digest=projection.digest,
            acknowledged_digest=(
                acknowledged if isinstance(acknowledged, str) else None
            ),
            identity=identity,
            config_path=requested_path,
            logical_path=logical,
            warning=None,
            policy_version=projection.policy_version,
        )
    try:
        filtered = filter_trusted_local_layer(
            layer,
            trusted=False,
            lower_macros=lower_macros,
            lower_workflows=lower_workflows,
            source="local_config",
            config_path=logical,
        )
        effective = dict(filtered.effective_layer)
        removed = tuple(filtered.removed_paths)
    except Exception:
        effective = {}
        removed = tuple(projection.blocked_paths)
    message = (
        f"Local commands in {requested_path} were skipped ({decision.reason}); "
        f"run `{_allow_command(requested_path, identity, allow_root)}` "
        "after review."
    )
    warning = _deduplicated_warning(
        identity, projection.digest, decision.reason, message
    )
    return LocalTrustEvaluation(
        enabled=True,
        trusted=False,
        effective_layer=effective,
        removed_paths=removed,
        status="untrusted",
        reason=decision.reason,
        digest=projection.digest,
        acknowledged_digest=(acknowledged if isinstance(acknowledged, str) else None),
        identity=identity,
        config_path=requested_path,
        logical_path=logical,
        warning=warning,
        policy_version=projection.policy_version,
    )


__all__ = [
    "evaluate_with_flag_on",
]
