"""Thin adapter from release-watch facts to Rust ``release_steward_decide``.

Python owns transport, CLI, and output. Shared eligibility, precedence,
idempotency-key, and escalation policy live in ``sase_core`` and are called
through the ``sase_core_rs`` extension. This module never calculates a
substitute verdict: a missing or stale extension is ``WATCHER_BROKEN``.

The scheduled observe-only host installs only the core wheel, so this
adapter imports ``sase_core_rs`` directly rather than the sase package.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

RELEASE_STEWARD_WIRE_SCHEMA_VERSION = 1
BINDING_NAME = "release_steward_decide"
EXTENSION_MODULE = "sase_core_rs"


def watcher_broken_result(
    *,
    source: str,
    message: str,
    remedy: str,
) -> dict[str, Any]:
    """Return the fail-closed result used when the binding is unavailable."""
    return {
        "schema_version": RELEASE_STEWARD_WIRE_SCHEMA_VERSION,
        "primary": {
            "kind": "watcher_broken",
            "source": source,
            "remedy": remedy,
        },
        "details": message,
        "evidence": [],
        "blocker_started_at": None,
        "blocker_duration_uncertain": False,
        "train_action": None,
        "escalation": None,
        "secondary": [],
        "process_exit": 1,
    }


def _missing_binding_result(exc: BaseException) -> dict[str, Any]:
    return watcher_broken_result(
        source=EXTENSION_MODULE,
        message=str(exc),
        remedy=(
            "build or install sase-core-rs from the pinned sase-core "
            "revision so release_steward_decide is available"
        ),
    )


def decide(request: Mapping[str, Any]) -> dict[str, Any]:
    """Call the Rust binding with *request* and return its result dict.

    A missing extension or missing ``release_steward_decide`` attribute
    becomes ``WATCHER_BROKEN``. Structurally invalid requests propagate
    the binding's ``ValueError``.
    """
    try:
        import sase_core_rs
    except ImportError as exc:
        return _missing_binding_result(exc)
    fn = getattr(sase_core_rs, BINDING_NAME, None)
    if fn is None:
        return _missing_binding_result(
            AttributeError(
                f"{EXTENSION_MODULE} does not expose {BINDING_NAME!r}"
            )
        )
    result = fn(dict(request))
    return dict(result)
