"""Provenance recording for one backup: host, versions, and revisions.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

from pathlib import Path
import socket
import subprocess
from typing import Any

from sase.config.identity import read_machine_name_selector
from sase.core.paths import machine_name_path
from sase.migration_kit.hashing import sha256_bytes
from sase.version.inventory import collect_runtime_version_inventory
from sase.version.render import runtime_version_inventory_to_json_payload

PROVENANCE_SCHEMA_VERSION = 1


def host_identity() -> str:
    """Return the tailnet machine name if configured, else the OS hostname."""
    selected = read_machine_name_selector(machine_name_path())
    return selected or socket.gethostname()


def _git_revision(git_root: Path) -> str | None:
    """Return the HEAD commit of *git_root*, or ``None`` if it is not a repo."""
    if not (git_root / ".git").exists():
        return None
    result = subprocess.run(
        ["git", "-C", str(git_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _kit_source_checksum() -> str:
    """Return a stable sha256 over every ``migration_kit`` module's source.

    Lets a later restore or rehearsal prove which exact revision of this
    temporary kit produced a given backup, independent of the host repo's
    git revision (a dirty working tree still hashes deterministically).
    """
    package_dir = Path(__file__).resolve().parent
    parts: list[bytes] = []
    for path in sorted(package_dir.rglob("*.py")):
        relative = path.relative_to(package_dir).as_posix()
        parts.append(relative.encode("utf-8"))
        parts.append(path.read_bytes())
    return sha256_bytes(b"\x00".join(parts))


def build_provenance(
    *,
    run_id: str,
    source_root: Path,
    resolved_source_root: Path,
) -> dict[str, Any]:
    """Return the ``provenance.json`` payload for one backup invocation."""
    inventory = collect_runtime_version_inventory()
    host_repo_revision = _git_revision(Path(__file__).resolve().parents[3])
    source_root_revision = _git_revision(resolved_source_root)
    return {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "run_id": run_id,
        "host": host_identity(),
        "sase_version": runtime_version_inventory_to_json_payload(inventory),
        "host_repo_revision": host_repo_revision,
        "source_root": str(source_root),
        "resolved_source_root": str(resolved_source_root),
        "source_root_revision": source_root_revision,
        "kit_revision": host_repo_revision,
        "kit_checksum": _kit_source_checksum(),
    }
