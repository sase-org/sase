"""Probe machine-writability of artifact-link sidecar roots.

Background link-maintenance jobs call this before any worktree write so an
unauthorized root is skipped with a diagnostic instead of half-mutated.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MachineSidecarWritability:
    """Result of probing one sidecar root for machine mutation rights."""

    writable: bool
    diagnostic: str | None = None


def probe_machine_writable_sidecar_root(root: Path) -> MachineSidecarWritability:
    """Return whether *root* may receive a machine-origin store mutation.

    Calls :func:`authorize_store_mutation` with ``mutation_origin="machine"``
    and does not mutate the worktree.
    """

    from sase.workspace_provider.ownership import (
        WorkspaceOwnershipError,
        authorize_store_mutation,
    )

    resolved = root.expanduser().resolve(strict=False)
    try:
        authorize_store_mutation(resolved, mutation_origin="machine")
    except WorkspaceOwnershipError as exc:
        return MachineSidecarWritability(writable=False, diagnostic=str(exc))
    return MachineSidecarWritability(writable=True)


def sidecar_root_not_machine_writable_message(
    kind: str, _root: Path, *, diagnostic: str
) -> str:
    """Format a skip diagnostic for one unauthorized sidecar root."""

    return f"{kind} root not machine-writable: {_short_machine_refusal(diagnostic)}"


def classify_machine_writable_sidecar_roots(
    sidecar_roots: Mapping[str, Path],
) -> tuple[dict[str, Path], tuple[str, ...]]:
    """Split *sidecar_roots* into writable roots and skip diagnostics."""

    writable: dict[str, Path] = {}
    skipped: list[str] = []
    seen: dict[Path, MachineSidecarWritability] = {}
    for kind, root in sidecar_roots.items():
        resolved = root.expanduser().resolve(strict=False)
        probe = seen.get(resolved)
        if probe is None:
            probe = probe_machine_writable_sidecar_root(resolved)
            seen[resolved] = probe
        if probe.writable:
            writable[kind] = resolved
            continue
        skipped.append(
            sidecar_root_not_machine_writable_message(
                kind,
                resolved,
                diagnostic=probe.diagnostic or "not machine-writable",
            )
        )
    return writable, tuple(skipped)


def _short_machine_refusal(diagnostic: str) -> str:
    if "path resolves to primary workspace #0" in diagnostic:
        return "resolves to primary #0"
    if "read-only canonical location" in diagnostic:
        return "path is a read-only canonical location"
    if "missing checkout marker or registry evidence" in diagnostic:
        return "missing checkout marker or registry evidence"
    if "checkout has no matching live workspace claim" in diagnostic:
        return "checkout has no matching live workspace claim"
    if "user-directed access is not a machine-writable context" in diagnostic:
        return "user-directed access is not a machine-writable context"
    return diagnostic


__all__ = [
    "MachineSidecarWritability",
    "classify_machine_writable_sidecar_roots",
    "probe_machine_writable_sidecar_root",
    "sidecar_root_not_machine_writable_message",
]
