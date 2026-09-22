#!/usr/bin/env python3
"""Source identity of the linked sase-core checkout.

A dev extension is fresh only when it was built from the checkout's current
source. The identity is ``git rev-parse HEAD`` plus a digest of uncommitted
and untracked changes under :data:`INPUT_PATHS` — the same crate input paths
``tools/sase_core_wheel_cache`` hashes for its clean-tree cache key. Both the
``rust-install`` stamp writer (Justfile) and the ``core-source`` freshness
check in ``tools/validate_test_environment`` share this module so the path
list and the identity computation cannot drift apart.

Only git plumbing is used and ``target/`` is never hashed: untracked files
come from ``git status``, which never reports gitignored build output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path


#: Crate input paths whose content identifies a sase-core source tree.
#: Shared with ``tools/sase_core_wheel_cache`` (clean-tree cache key) and
#: the dev-extension freshness stamp (this module's identity).
INPUT_PATHS = ("Cargo.toml", "Cargo.lock", "crates/sase_core_py")

#: Venv-relative stamp recording the source identity an extension was built
#: from. Written by the ``rust-install`` Justfile recipe only after a
#: successful install, so an edit made during the build still reads as stale.
STAMP_FILENAME = ".sase-core-rs-source.json"

STAMP_SCHEMA_VERSION = 1

_GIT_TIMEOUT = 30.0


def _git(core_dir: Path, *args: str) -> bytes | None:
    """Run a git plumbing command, returning stdout bytes or None on failure."""
    try:
        completed = subprocess.run(
            ("git", "-C", str(core_dir), *args),
            check=False,
            capture_output=True,
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.stdout if completed.returncode == 0 else None


def _untracked_paths(status: bytes) -> list[str]:
    """Parse ``git status --porcelain=v1 -z`` output into untracked relpaths."""
    paths = []
    for record in status.split(b"\0"):
        if record.startswith(b"?? "):
            paths.append(record[3:].decode("utf-8", errors="replace"))
    return sorted(paths)


def _untracked_content(core_dir: Path, relpath: str) -> bytes | None:
    """Read an untracked file, refusing paths that escape the checkout."""
    try:
        resolved_core = core_dir.resolve()
        candidate = (core_dir / relpath).resolve()
        candidate.relative_to(resolved_core)
    except (OSError, ValueError):
        return None
    try:
        if not candidate.is_file():
            return None
        return candidate.read_bytes()
    except OSError:
        return None


def compute_identity(core_dir: Path) -> dict[str, str] | None:
    """Return ``{"head": ..., "dirty": ...}`` for a checkout, or None.

    None means the identity is uncomputable here (not a git checkout, no
    ``HEAD`` yet, git missing) — not that the tree is clean. Callers treat
    that as "skip the freshness check", never as "matches any stamp".
    """
    raw_head = _git(core_dir, "rev-parse", "HEAD")
    if raw_head is None:
        return None
    head = raw_head.decode("utf-8", errors="replace").strip()
    if not head:
        return None
    diff = _git(core_dir, "diff", "HEAD", "--", *INPUT_PATHS)
    if diff is None:
        return None
    status = _git(
        core_dir,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "-z",
        "--",
        *INPUT_PATHS,
    )
    if status is None:
        return None
    digest = hashlib.sha256()
    digest.update(b"diff\x00")
    digest.update(diff)
    digest.update(b"\x00")
    for relpath in _untracked_paths(status):
        digest.update(b"untracked\x00")
        digest.update(relpath.encode("utf-8", errors="replace"))
        digest.update(b"\x00")
        content = _untracked_content(core_dir, relpath)
        if content is None:
            # Raced with a concurrent edit (or an escaping symlink): hash the
            # name so the identity still moves instead of matching a stamp.
            digest.update(b"<unreadable>\x00")
        else:
            digest.update(content)
            digest.update(b"\x00")
    return {"head": head, "dirty": digest.hexdigest()}


def identity_fingerprint(identity: Mapping[str, str]) -> str:
    """Stable digest of an identity mapping for fingerprint buckets."""
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def stamp_path(venv_dir: Path) -> Path:
    """Location of the built-from stamp inside a venv."""
    return venv_dir / STAMP_FILENAME


def format_stamp(identity: Mapping[str, str]) -> str:
    """Single-line stamp payload capturing an identity."""
    return json.dumps(
        {"schema_version": STAMP_SCHEMA_VERSION, **identity}, sort_keys=True
    )


def read_stamp(venv_dir: Path) -> dict[str, str] | None:
    """Read a venv's built-from stamp, or None when missing or malformed."""
    try:
        payload = json.loads(stamp_path(venv_dir).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != STAMP_SCHEMA_VERSION
        or not isinstance(payload.get("head"), str)
        or not isinstance(payload.get("dirty"), str)
    ):
        return None
    return {"head": payload["head"], "dirty": payload["dirty"]}


def main(argv: list[str] | None = None) -> int:
    """Print the checkout's stamp payload, or nothing when uncomputable.

    Always exits 0: the ``rust-install`` recipe captures stdout into a shell
    variable, and empty output simply means "skip stamping" (a non-git
    checkout has no identity to record). The reason goes to stderr.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sase-core-dir", type=Path, required=True)
    namespace = parser.parse_args(argv)
    identity = compute_identity(namespace.sase_core_dir)
    if identity is None:
        print(
            "[sase-core-source-identity] uncomputable source identity for "
            f"{namespace.sase_core_dir}; skipping the built-from stamp",
            file=sys.stderr,
        )
        return 0
    print(format_stamp(identity))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
