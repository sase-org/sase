"""Boot-time ``agent_meta.json`` keys that must survive runner rebuilds.

``RUNNER_BOOT_META_KEYS`` is the single list used by the bootstrap writer
and by :func:`sase.axe.run_agent_directive_metadata_preserved.preserved_agent_metadata`.
Directive extraction rebuilds ``agent_meta.json`` from the prompt, so these
keys have to be copied across that rewrite or hijack, provenance, and
user-kill all go blind.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

RUNNER_BOOT_META_KEYS: tuple[str, ...] = (
    "runner_capabilities",
    "code_identity",
    "booted_at",
    "launch_scratch_key",
    "prompt_origin",
    "prompt_source_surface",
)


def copy_runner_boot_meta(
    source: Mapping[str, Any], dest: dict[str, Any]
) -> dict[str, Any]:
    """Copy every present :data:`RUNNER_BOOT_META_KEYS` value into *dest*."""
    for key in RUNNER_BOOT_META_KEYS:
        _copy_boot_meta_key(source, dest, key)
    return dest


def restamp_hijack_capability(agent_meta: dict[str, Any]) -> None:
    """Re-stamp hijack support when this process is writing its own meta.

    Follows the ``launch_scratch_key`` rule in
    :func:`sase.axe.run_agent_markers.write_agent_meta`: only the runner
    whose ``pid`` matches ``os.getpid()`` may add the capability. A TUI or
    CLI rewriting another agent's meta must not claim hijack support for it.
    """
    if agent_meta.get("pid") != os.getpid():
        return
    from sase.agent.hijack import HIJACK_RUNNER_CAPABILITY

    capabilities = agent_meta.get("runner_capabilities")
    if not isinstance(capabilities, list):
        capabilities = []
    else:
        capabilities = list(capabilities)
    if HIJACK_RUNNER_CAPABILITY not in capabilities:
        capabilities.append(HIJACK_RUNNER_CAPABILITY)
    agent_meta["runner_capabilities"] = capabilities


def _copy_boot_meta_key(
    source: Mapping[str, Any], dest: dict[str, Any], key: str
) -> None:
    value = source.get(key)
    if key == "runner_capabilities":
        if isinstance(value, list) and all(
            isinstance(item, str) and item for item in value
        ):
            dest[key] = list(value)
        return
    if key == "code_identity":
        if isinstance(value, dict):
            dest[key] = dict(value)
        return
    if isinstance(value, str) and value:
        dest[key] = value


__all__ = [
    "RUNNER_BOOT_META_KEYS",
    "copy_runner_boot_meta",
    "restamp_hijack_capability",
]
