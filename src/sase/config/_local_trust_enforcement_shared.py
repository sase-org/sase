"""Shared trust-enforcement state and identity helpers.

Public names in this private module are shared by the sibling
``local_trust_enforcement_*`` modules. Each public name here has more than
one consumer among the new modules, so it lives here instead of being
duplicated. Helpers used by only one sibling stay in that sibling.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import logging
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_evaluation_state = threading.local()


def evaluation_active() -> bool:
    """Return whether this thread is already inside a trust evaluation."""
    return bool(getattr(_evaluation_state, "active", False))


@contextmanager
def trust_evaluation_guard() -> Iterator[None]:
    """Mark nested config loads as internal so they skip filtering."""
    previous = evaluation_active()
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


def checkout_root_for_local_path(local_path: Path) -> Path | None:
    """Return the checkout root owning *local_path*, if discoverable."""
    try:
        from sase.content_layout import owning_checkout_root_for_config

        return owning_checkout_root_for_config(local_path)
    except Exception:
        return None


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


__all__ = [
    "LocalTrustEvaluation",
    "checkout_root_for_local_path",
    "evaluation_active",
    "is_local_command_trust_enabled",
    "trust_evaluation_guard",
]
