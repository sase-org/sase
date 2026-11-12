"""Synchronous trust enforcement for project-local executable config.

Phase ``hook-enforcement`` activates the ``local_config_command_trust``
sunset flag. When the flag is enabled, local command-bearing contributions
require a current human acknowledgment; otherwise they are filtered before
merging and before the independent file-hook and config-macro loaders
consume raw layers.

``load_config_layers()`` stays raw for provenance inspection and
feature-flag bootstrap. This module provides the effective-local adapter
that executable consumers use instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import threading
from typing import Any
from collections.abc import Iterator

log = logging.getLogger(__name__)

_flag_state_cache_token: tuple[Any, ...] | None = None
_flag_state_cache_value: bool | None = None

_warned_signatures: set[tuple[str, str, str]] = set()
_warned_lock = threading.RLock()

_evaluation_state = threading.local()


def _evaluation_active() -> bool:
    """Return whether this thread is already inside a trust evaluation."""
    return bool(getattr(_evaluation_state, "active", False))


@contextmanager
def _trust_evaluation_guard() -> Iterator[None]:
    """Mark nested config loads as internal so they skip filtering."""
    previous = _evaluation_active()
    _evaluation_state.active = True
    try:
        yield
    finally:
        _evaluation_state.active = previous


def is_local_command_trust_enabled() -> bool:
    """Return whether local-command trust enforcement applies.

    The sunset flag defaults on. A resolver failure fails closed (treated
    as enabled) so local execution never sneaks through when flag state
    cannot be determined. Raw layer inspection never calls this helper.
    """
    try:
        from sase.feature_flags import FeatureFlag, current_flags

        return bool(current_flags().enabled(FeatureFlag.local_config_command_trust))
    except Exception:
        log.debug("Local-command trust flag lookup failed; enforcing", exc_info=True)
        return True


def _read_candidate_file(path: Path) -> dict[str, Any]:
    """Read one decoded local layer file, returning empty on missing file."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        return {}
    try:
        from sase._yaml_safe import yaml_safe_load

        value = yaml_safe_load(text)
    except Exception:
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _checkout_root_for_local_path(local_path: Path) -> Path | None:
    """Return the checkout root owning *local_path*, if discoverable."""
    try:
        from sase.content_layout import discover_project_root
    except Exception:
        return None
    probe = local_path if local_path.is_dir() else local_path.parent
    try:
        found = discover_project_root(probe)
    except Exception:
        return None
    if found is not None:
        return found
    # Fall back to the config's grandparent for canonical layouts when the
    # checkout is not a registered project root (unregistered roots still
    # get checkout-scoped trust rather than inheriting another project).
    try:
        if local_path.name in {"sase.yml", "sase.yaml"}:
            if local_path.parent.name == "sase":
                return local_path.parent.parent
            return local_path.parent
    except Exception:
        return None
    return None


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


def _lower_macros_and_workflows() -> tuple[dict[str, Any], dict[str, Any]]:
    """Return lower-layer macros/workflows without triggering filtering."""
    try:
        from sase.config.core import load_merged_config_for_local_path

        with _trust_evaluation_guard():
            lower = load_merged_config_for_local_path(None)
    except Exception:
        return {}, {}
    macros = lower.get("macros")
    workflows = lower.get("workflows")
    return (
        dict(macros) if isinstance(macros, dict) else {},
        dict(workflows) if isinstance(workflows, dict) else {},
    )


@dataclass(frozen=True)
class LocalTrustEvaluation:
    """One synchronous trust verdict for a local layer candidate."""

    enabled: bool
    trusted: bool
    effective_layer: dict[str, Any]
    removed_paths: tuple[str, ...]
    status: str
    reason: str
    digest: str
    acknowledged_digest: str | None
    identity: str | None
    config_path: str | None
    logical_path: str | None
    warning: str | None
    policy_version: int = 1

    def descriptor(self) -> dict[str, Any]:
        """Return the immutable trust facts retained with executable data."""
        return {
            "identity": self.identity,
            "config_path": self.config_path,
            "logical_path": self.logical_path,
            "digest": self.digest,
            "status": self.status,
            "enabled": self.enabled,
            "policy_version": self.policy_version,
        }


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


def evaluate_local_trust_for_path(
    local_path: Path | None,
    candidate: Mapping[str, Any] | None,
) -> LocalTrustEvaluation:
    """Evaluate trust for one decoded local layer candidate synchronously.

    The same decoded snapshot is digested and filtered; callers must
    execute the returned ``effective_layer``, never a second unchecked
    read. Missing files and non-command layers are trusted with no
    warning. Store or identity failures fail closed when command-bearing
    content is present.
    """
    enabled = is_local_command_trust_enabled()
    requested_path = str(local_path) if local_path is not None else None
    if local_path is None:
        return LocalTrustEvaluation(
            enabled=enabled,
            trusted=True,
            effective_layer=dict(candidate) if candidate is not None else {},
            removed_paths=(),
            status="no-local-layer" if enabled else "flag-disabled",
            reason="no local layer selected",
            digest="",
            acknowledged_digest=None,
            identity=None,
            config_path=requested_path,
            logical_path=None,
            warning=None,
        )
    try:
        is_dir = local_path.is_dir()
    except OSError:
        is_dir = False
    if is_dir:
        return LocalTrustEvaluation(
            enabled=enabled,
            trusted=True,
            effective_layer={},
            removed_paths=(),
            status="no-local-layer" if enabled else "flag-disabled",
            reason="no local config file",
            digest="",
            acknowledged_digest=None,
            identity=None,
            config_path=requested_path,
            logical_path=None,
            warning=None,
        )
    if candidate is None:
        layer = _read_candidate_file(local_path)
    else:
        layer = dict(candidate)
    if not layer:
        return LocalTrustEvaluation(
            enabled=enabled,
            trusted=True,
            effective_layer={},
            removed_paths=(),
            status="no-local-content" if enabled else "flag-disabled",
            reason="local layer is empty",
            digest="",
            acknowledged_digest=None,
            identity=None,
            config_path=requested_path,
            logical_path=None,
            warning=None,
        )
    if not enabled:
        return LocalTrustEvaluation(
            enabled=False,
            trusted=True,
            effective_layer=dict(layer),
            removed_paths=(),
            status="flag-disabled",
            reason="local_config_command_trust is off; compatibility mode",
            digest="",
            acknowledged_digest=None,
            identity=None,
            config_path=requested_path,
            logical_path=None,
            warning=None,
        )
    if _evaluation_active():
        return LocalTrustEvaluation(
            enabled=True,
            trusted=True,
            effective_layer=dict(layer),
            removed_paths=(),
            status="internal-load",
            reason="nested trust evaluation; outer verdict applies",
            digest="",
            acknowledged_digest=None,
            identity=None,
            config_path=requested_path,
            logical_path=None,
            warning=None,
        )
    with _trust_evaluation_guard():
        return _evaluate_with_flag_on(local_path, layer)


def _evaluate_with_flag_on(
    local_path: Path, layer: dict[str, Any]
) -> LocalTrustEvaluation:
    """Evaluate one non-empty local layer while the sunset flag is on."""
    from sase.config.local_trust import (
        decide_local_command_trust,
        filter_trusted_local_layer,
        project_local_commands,
    )

    requested_path = str(local_path)
    root = _checkout_root_for_local_path(local_path)
    if root is None:
        try:
            canonical = str(local_path.expanduser().resolve(strict=False))
        except Exception:
            canonical = requested_path
        root = local_path.parent
        identity = f"checkout:v1:{canonical}"
        logical: str | None = local_path.name
    else:
        try:
            selected = Path(os.path.abspath(local_path))
            canonical_root = root.expanduser().resolve(strict=False)
        except Exception:
            canonical_root = root
            selected = local_path
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
            f"command-bearing content ({exc}); run `sase config trust allow "
            f"{requested_path}` after review."
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
            f"unavailable ({exc}); run `sase config trust allow {requested_path}` "
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
            f"`sase config trust allow {requested_path}` after review."
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
            f"trust ({exc}); run `sase config trust allow {requested_path}` "
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
        f"run `sase config trust allow {requested_path}` after review."
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


def effective_local_layer(
    local_path: Path | None,
    candidate: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], LocalTrustEvaluation]:
    """Return the filtered local contribution and its synchronous verdict."""
    evaluation = evaluate_local_trust_for_path(local_path, candidate)
    return evaluation.effective_layer, evaluation


def validate_trust_descriptor(descriptor: Mapping[str, Any]) -> bool:
    """Return whether a retained local descriptor still matches acknowledgment.

    Changed config or revocation blocks further local execution. This check
    is synchronous and reads the current snapshot; it never trusts a
    caller-supplied boolean or a prefetched mapping.
    """
    try:
        if not is_local_command_trust_enabled():
            return True
        identity = descriptor.get("identity")
        expected_digest = descriptor.get("digest")
        config_path = descriptor.get("config_path")
        logical_path = descriptor.get("logical_path")
        policy_version = descriptor.get("policy_version")
        if not isinstance(identity, str) or not identity:
            return False
        if not isinstance(expected_digest, str) or not expected_digest:
            return False
        if not isinstance(config_path, str) or not config_path:
            return False
        if not isinstance(policy_version, int):
            return False
        selected = _current_selected_config_path(Path(config_path))
        if selected is None or _canonical_path(selected) != _canonical_path(
            Path(config_path)
        ):
            return False
        current = evaluate_local_trust_for_path(Path(config_path), candidate=None)
        return bool(
            current.enabled
            and current.trusted
            and current.identity == identity
            and current.logical_path == logical_path
            and current.digest == expected_digest
            and current.policy_version == policy_version
        )
    except Exception:
        log.debug("Trust descriptor revalidation failed closed", exc_info=True)
        return False


def _canonical_path(path: Path) -> str:
    """Canonicalize both selected-path comparisons, including macOS aliases."""
    return str(path.expanduser().resolve(strict=False))


def _current_selected_config_path(path: Path) -> Path | None:
    """Resolve the currently selected canonical/fallback config for a descriptor."""
    root = _checkout_root_for_local_path(path)
    if root is None:
        return path if path.is_file() else None
    try:
        from sase.content_layout import resolve_project_layout

        return resolve_project_layout(root).config.resolve_read("project config")
    except Exception:
        return None


__all__ = [
    "LocalTrustEvaluation",
    "effective_local_layer",
    "evaluate_local_trust_for_path",
    "is_local_command_trust_enabled",
    "validate_trust_descriptor",
]
