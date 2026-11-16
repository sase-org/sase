"""Evaluation entry point and descriptor validation for local trust.

Implements ``evaluate_local_trust_for_path``, ``effective_local_layer``,
and ``validate_trust_descriptor`` on top of the shared state in
``_local_trust_enforcement_shared`` and the flag-on decision in
``local_trust_enforcement_flag_on``. Private helpers here are used only in
this file.
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
from pathlib import Path
from typing import Any

from sase.config._local_trust_enforcement_shared import (
    LocalTrustEvaluation,
    checkout_root_for_local_path,
    evaluation_active,
    is_local_command_trust_enabled,
    trust_evaluation_guard,
)
from sase.config.local_trust_enforcement_flag_on import evaluate_with_flag_on

log = logging.getLogger(__name__)


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


def _canonical_path(path: Path) -> str:
    """Canonicalize both selected-path comparisons, including macOS aliases."""
    return str(path.expanduser().resolve(strict=False))


def _current_selected_config_path(path: Path) -> Path | None:
    """Resolve the currently selected canonical/fallback config for a descriptor."""
    root = checkout_root_for_local_path(path)
    if root is None:
        return path if path.is_file() else None
    try:
        from sase.content_layout import resolve_project_layout

        return resolve_project_layout(root).config.resolve_read("project config")
    except Exception:
        return None


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
    if evaluation_active():
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
    with trust_evaluation_guard():
        return evaluate_with_flag_on(local_path, layer)


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


__all__ = [
    "effective_local_layer",
    "evaluate_local_trust_for_path",
    "validate_trust_descriptor",
]
