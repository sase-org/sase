"""Read and compare the sase-core revision required by a host checkout."""

from __future__ import annotations

from dataclasses import dataclass
import re
import subprocess
from pathlib import Path

from sase.finalizers.commit_revision_pin import revision_pins_for_project

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_GIT_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class CorePin:
    """The core commit pinned by one host revision."""

    pin_file: str
    sha: str

    @property
    def short_sha(self) -> str:
        """Return the standard 12-character revision abbreviation."""
        return self.sha[:12]


def read_core_pin(host_root: Path, ref: str) -> CorePin | None:
    """Read the configured sase-core pin from *host_root* at *ref*."""
    pins = revision_pins_for_project(str(host_root))
    pin_file = pins.get("sase-core")
    if not pin_file:
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(host_root), "show", f"{ref}:{pin_file}"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    if not _SHA_RE.fullmatch(sha):
        return None
    return CorePin(pin_file=pin_file, sha=sha)


def core_contains_revision(core_root: Path, sha: str, ref: str) -> bool | None:
    """Report whether *sha* is in *ref*, or ``None`` when git cannot decide."""
    if not _SHA_RE.fullmatch(sha):
        return None
    try:
        object_result = subprocess.run(
            ["git", "-C", str(core_root), "cat-file", "-e", f"{sha}^{{commit}}"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if object_result.returncode != 0:
        error = object_result.stderr.lower()
        if object_result.returncode == 1 or any(
            marker in error
            for marker in (
                "not a valid object name",
                "could not get object info",
                "bad object",
            )
        ):
            return False
        return None

    try:
        ancestor_result = subprocess.run(
            ["git", "-C", str(core_root), "merge-base", "--is-ancestor", sha, ref],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if ancestor_result.returncode == 0:
        return True
    if ancestor_result.returncode == 1:
        return False
    return None


__all__ = ["CorePin", "core_contains_revision", "read_core_pin"]
