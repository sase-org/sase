"""Provenance facts for the attachment audience decision.

Python only gathers facts; the ordered rule table lives in sase-core
(``attachment_audience_decision``) so every frontend agrees. All helpers
are lazy and fail private on uncertainty. Nothing here runs unless the
invocation actually attaches files.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path


def is_owner_only(path: Path) -> bool:
    """Return whether *path* has no group/other read bits (``st_mode``)."""
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    return mode & 0o044 == 0


def git_toplevel(start: Path) -> Path | None:
    """Return the checkout root containing *start*, or None."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(start if start.is_dir() else start.parent),
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    return Path(root) if root else None


def workspace_root(cwd: Path | None = None) -> str | None:
    """Return the checkout root of the invocation cwd, or None."""
    base = cwd or Path.cwd()
    root = git_toplevel(base)
    return str(root) if root is not None else None


def scratch_roots() -> list[str]:
    """Return SASE managed-tmp roots plus the run's managed TMPDIR."""
    roots: list[str] = []
    try:
        from sase.core.paths import managed_tmpdir_root

        roots.append(str(managed_tmpdir_root()))
    except Exception:
        pass
    for key in ("SASE_TMPDIR", "TMPDIR"):
        value = os.environ.get(key)
        if value and value.strip():
            candidate = value.strip()
            if candidate not in roots:
                roots.append(candidate)
    return roots


def current_actor() -> str:
    """Return ``human`` or ``agent``, failing closed to ``agent``."""
    if os.environ.get("SASE_AGENT") or os.environ.get("SASE_AGENT_NAME"):
        return "agent"
    try:
        from sase.agent.identity import discover_agent_identity

        return "agent" if discover_agent_identity() is not None else "human"
    except Exception:
        return "agent"


def produced_during_run(path: Path) -> bool | None:
    """Return whether *path* was produced during this agent run.

    ``None`` without a run window (human invocations have no run window,
    and malformed agent metadata also yields ``None``).
    """
    if current_actor() != "agent":
        return None
    try:
        from sase.agent.identity import discover_agent_identity

        identity = discover_agent_identity()
        if identity is None or not identity.artifacts_dir:
            return None
        meta_path = Path(identity.artifacts_dir) / "agent_meta.json"
        import json

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        started_raw = meta.get("run_started_at")
        if not isinstance(started_raw, str) or not started_raw.strip():
            return None
        started = datetime.fromisoformat(started_raw.strip().replace("Z", "+00:00"))
        if started.tzinfo is None:
            return None
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=started.tzinfo)
        return mtime >= started
    except Exception:
        return None


def bead_store_visibility() -> str:
    """Return the configured beads sidecar visibility.

    Merged sidecar entries default to ``public``. Non-sidecar (legacy)
    bead storage counts as private.
    """
    try:
        from sase._linked_repo_config import (
            merged_sidecar_entries_from_config,
            resolution_config,
        )

        workspace = str(Path.cwd())
        config = resolution_config(workspace, None)
        for entry in merged_sidecar_entries_from_config(
            config,
            primary_workspace_dir=workspace,
        ):
            if entry.get("role") == "beads" or entry.get("_sidecar_role") == "beads":
                visibility = str(entry.get("visibility") or "public").strip().lower()
                return visibility if visibility in ("public", "private") else "public"
            # Entries use plain ``role`` in most call sites; be lenient.
            role = str(entry.get("role") or entry.get("name") or "")
            if role == "beads":
                visibility = str(entry.get("visibility") or "public").strip().lower()
                return visibility if visibility in ("public", "private") else "public"
        # No beads sidecar entry: check for any beads role key variant.
        for entry in merged_sidecar_entries_from_config(
            config,
            primary_workspace_dir=workspace,
        ):
            for key in ("role", "sidecar_role", "_role"):
                if str(entry.get(key) or "") == "beads":
                    visibility = (
                        str(entry.get("visibility") or "public").strip().lower()
                    )
                    return (
                        visibility if visibility in ("public", "private") else "public"
                    )
        return "public"
    except Exception:
        return "private"


def checkout_facts(path: Path) -> dict[str, object] | None:
    """Return git facts for *path*, or None when outside a checkout."""
    try:
        resolved = path.resolve()
    except OSError:
        return None
    root = git_toplevel(resolved)
    if root is None:
        return None
    ignored = _is_ignored(root, resolved)
    origin_url = _origin_url(root)
    tracked_identical = _tracked_identical_to_remote(root, resolved)
    return {
        "root": str(root),
        "ignored": ignored,
        "tracked_identical_to_remote": tracked_identical,
        "origin_url": origin_url,
    }


def _is_ignored(root: Path, path: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=str(root),
            capture_output=True,
            check=False,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _origin_url(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    return url or None


def _remote_tracking_default_branch(root: Path) -> str | None:
    """Return e.g. ``origin/main`` or None when it cannot be determined."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "origin/HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        branch = result.stdout.strip()
        if result.returncode == 0 and branch and branch != "origin/HEAD":
            return branch
    except Exception:
        pass
    for candidate in ("origin/main", "origin/master"):
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--verify", candidate],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if result.returncode == 0:
                return candidate
        except Exception:
            continue
    return None


def _tracked_identical_to_remote(root: Path, path: Path) -> bool:
    """Return True only when bytes equal the remote-tracking default blob."""
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return False
    branch = _remote_tracking_default_branch(root)
    if branch is None:
        return False
    try:
        hashed = subprocess.run(
            ["git", "hash-object", str(path)],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if hashed.returncode != 0:
            return False
        local_hash = hashed.stdout.strip()
        remote = subprocess.run(
            ["git", "rev-parse", f"{branch}:{rel}"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if remote.returncode != 0:
            return False
        return bool(local_hash) and local_hash == remote.stdout.strip()
    except Exception:
        return False


__all__ = [
    "bead_store_visibility",
    "checkout_facts",
    "current_actor",
    "git_toplevel",
    "is_owner_only",
    "produced_during_run",
    "scratch_roots",
    "workspace_root",
]
