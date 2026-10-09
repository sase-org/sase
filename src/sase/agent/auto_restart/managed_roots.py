"""Managed code roots for update-skew witness collection.

A managed root is a checkout sase trusts: the ``sase`` host, the
``sase-core-rs`` extension, or an editable ``sase-*`` plugin. The failure
classifier scopes every signature family to these roots, so an
ImportError raised by code under an agent's workspace directory never
matches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from collections.abc import Mapping


@dataclass(frozen=True)
class ManagedRoot:
    """One trusted code root with its current version identity."""

    name: str
    role: str
    source_root: str | None
    commit: str | None
    version: str | None
    install_type: str | None


def collect_managed_roots() -> tuple[ManagedRoot, ...]:
    """Collect managed roots from the runtime version inventory."""
    from sase.version._collector import collect_runtime_version_inventory

    inventory = collect_runtime_version_inventory()
    roots: list[ManagedRoot] = []
    for package in inventory.packages:
        git_commit: str | None = None
        if package.git is not None and package.git.commit:
            git_commit = package.git.commit
        version = package.display_version or None
        roots.append(
            ManagedRoot(
                name=package.name,
                role=str(package.role),
                source_root=package.source_root,
                commit=git_commit,
                version=version,
                install_type=str(package.install_type),
            )
        )
    return tuple(roots)


def current_code_identity() -> dict[str, Any]:
    """Snapshot this process image's code identity via the runner helper.

    This is the same shape the runner persists into
    ``agent_meta.json`` (``code_identity``), so W1 compares like with
    like. The helper memoizes per process; in a scan process the first
    call reflects current disk state, which is exactly "current".
    """
    from sase.axe.runner_lifecycle_phase import boot_code_identity

    identity, _, _ = boot_code_identity()
    if isinstance(identity, dict):
        return dict(identity)
    return {"schema_version": 1, "roots": []}


def code_identity_digest(identity: Mapping[str, Any] | None) -> str | None:
    """Digest a boot-style code identity into an opaque comparison string.

    One ``name@short`` segment per root, sorted by name, joined with
    ``|``. The short form prefers the git commit (editable checkouts)
    and falls back to the version (wheels). Returns ``None`` when the
    identity carries no usable roots, so legacy rows without a boot
    snapshot simply cannot fire W1.
    """
    if not isinstance(identity, Mapping):
        return None
    raw_roots = identity.get("roots")
    if not isinstance(raw_roots, list) or not raw_roots:
        return None
    segments: list[str] = []
    for root in raw_roots:
        if not isinstance(root, Mapping):
            continue
        name = root.get("name")
        if not isinstance(name, str) or not name:
            continue
        commit = root.get("commit")
        if isinstance(commit, str) and len(commit) >= 7:
            short = commit[:7]
        else:
            version = root.get("version")
            short = str(version) if version is not None else "unknown"
        segments.append(f"{name}@{short}")
    if not segments:
        return None
    segments.sort()
    return "|".join(segments)


__all__ = [
    "ManagedRoot",
    "code_identity_digest",
    "collect_managed_roots",
    "current_code_identity",
]
