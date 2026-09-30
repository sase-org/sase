"""Shared git plumbing for the attachment store (private).

Public helpers live here because more than one :mod:`git_store` submodule
needs them: bounded :func:`run_git`, :func:`git_env`, the timeout and
chunk-size constants, and the canonical object/tombstone path helpers
shared by the read and write mixins. Import only public names from this
module.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from sase.bead.attachments.blob_store import BlobStoreError
from sase.bead.attachments.store import validate_sha256
from sase.core.rust import require_rust_binding

LOCAL_GIT_TIMEOUT_SECONDS = 30.0
CHUNK_SIZE = 1 << 20


def git_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Return a noninteractive git environment plus *extra* overrides."""

    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    ssh_command = env.get("GIT_SSH_COMMAND", "ssh")
    if "BatchMode=" not in ssh_command:
        ssh_command = f"{ssh_command} -o BatchMode=yes"
    env["GIT_SSH_COMMAND"] = ssh_command
    if extra:
        env.update(extra)
    return env


def run_git(
    args: list[str],
    *,
    cwd: Path,
    timeout: float,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one bounded git command, capturing output as text."""

    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        timeout=timeout,
        check=False,
        capture_output=True,
        text=True,
        env=git_env(env),
    )


def object_relpath(sha256: str) -> str:
    """Return the canonical remote object path for *sha256*.

    The layout comes from ``sase_core_rs.artifact_object_relpath`` and the
    shape is pinned by the prompt-archive quarantine rule
    (:func:`canonical_archive_object_digest`): a bare repo has no worktree
    to quarantine into, so a non-canonical path is an error here.
    """

    relpath = str(require_rust_binding("artifact_object_relpath")(sha256))
    from sase.agents_sync.prompt_archive.archive_objects import (
        canonical_archive_object_digest,
    )

    if canonical_archive_object_digest(relpath) != sha256:
        raise BlobStoreError(
            f"git store path for {sha256[:16]}… is not canonical: {relpath!r}"
        )
    return relpath


def tombstone_relpath(sha256: str) -> str:
    """Return the canonical remote tombstone path for *sha256*.

    Tombstones live at ``files/tombstones/sha256/<xx>/<sha>.json`` next to
    the content-addressed object layout from
    ``sase_core_rs.artifact_object_relpath``.
    """

    validate_sha256(sha256)
    object_path = object_relpath(sha256)
    prefix = "files/objects/sha256/"
    if not object_path.startswith(prefix) or not object_path.endswith(sha256):
        raise BlobStoreError(
            f"git store tombstone for {sha256[:16]}… has no canonical path: "
            f"{object_path!r}"
        )
    return f"files/tombstones/sha256/{sha256[:2]}/{sha256}.json"
