"""Shared fixtures for dev-update plan tests."""

from __future__ import annotations

from pathlib import Path

from sase.version._git import GitProbeResult, GitUpstreamStatus
from sase.version._models import GitVersionMetadata, VersionPackageRecord


def record(
    name: str,
    *,
    role: str,
    source_root: str | None,
    display_version: str = "0.5.0+1.gaaaaaaaaa",
    install_type: str = "editable",
) -> VersionPackageRecord:
    return VersionPackageRecord(
        name=name,
        role=role,  # type: ignore[arg-type]
        display_version=display_version,
        distribution_version="0.5.0",
        source_version="0.5.0",
        import_module=None,
        import_path=None,
        code_directory=None,
        source_root=source_root,
        distribution_location=None,
        install_type=install_type,  # type: ignore[arg-type]
        git=None,
    )


def status(
    root: str,
    *,
    dirty: bool = False,
    detached: bool = False,
    upstream: str | None = "origin/main",
    ahead: int | None = 0,
    behind: int | None = 2,
) -> GitUpstreamStatus:
    return GitUpstreamStatus(
        root=root,
        upstream=upstream,
        remote="origin" if upstream else None,
        remote_branch="main" if upstream else None,
        detached=detached,
        dirty=dirty,
        ahead=ahead,
        behind=behind,
    )


def probe(_root: Path, _ref: str = "HEAD") -> GitProbeResult:
    return GitProbeResult(
        GitVersionMetadata(
            root="/repo",
            commit="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            short_commit="bbbbbbbbb",
            tag="v0.5.0",
            distance=4,
            dirty=False,
        )
    )
