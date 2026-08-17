"""Install stamps for generated shell-completion scripts."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.completion.install_targets import SUPPORTED_SHELLS
from sase.core.paths import sase_subdir


STAMP_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class InstallStamp:
    """Record of a completion script sase wrote for one shell."""

    shell: str
    version: str
    digest: str
    target: str
    timestamp: str
    schema_version: int = STAMP_SCHEMA_VERSION

    def to_json(self) -> dict[str, Any]:
        return {
            "digest": self.digest,
            "schema_version": self.schema_version,
            "shell": self.shell,
            "target": self.target,
            "timestamp": self.timestamp,
            "version": self.version,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> InstallStamp:
        return cls(
            shell=str(data["shell"]),
            version=str(data["version"]),
            digest=str(data["digest"]),
            target=str(data["target"]),
            timestamp=str(data["timestamp"]),
            schema_version=int(data.get("schema_version", STAMP_SCHEMA_VERSION)),
        )


def _stamp_dir() -> Path:
    """Return ``~/.sase/completion/stamp``."""
    return sase_subdir("completion") / "stamp"


def _stamp_path(shell: str) -> Path:
    """Return the stamp JSON path for *shell*."""
    return _stamp_dir() / f"{shell}.json"


def read_stamp(shell: str) -> InstallStamp | None:
    """Return the stamp for *shell*, or ``None`` when missing or malformed."""
    path = _stamp_path(shell)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        stamp = InstallStamp.from_json(payload)
    except (KeyError, TypeError, ValueError):
        return None
    return stamp if stamp.shell == shell else None


def write_stamp(stamp: InstallStamp) -> Path:
    """Atomically write *stamp* and return the path."""
    path = _stamp_path(stamp.shell)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(stamp.to_json(), indent=2, sort_keys=True) + "\n"
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    return path


def list_stamps() -> tuple[InstallStamp, ...]:
    """Return every readable stamp, in supported-shell order."""
    return tuple(
        stamp for shell in SUPPORTED_SHELLS if (stamp := read_stamp(shell)) is not None
    )


def stamp_owns_path(shell: str, path: Path) -> bool:
    """Return whether the *shell* stamp claims *path* as sase-written."""
    stamp = read_stamp(shell)
    if stamp is None:
        return False
    try:
        return Path(stamp.target).expanduser().resolve() == path.expanduser().resolve()
    except OSError:
        return Path(stamp.target) == path


__all__ = [
    "InstallStamp",
    "STAMP_SCHEMA_VERSION",
    "list_stamps",
    "read_stamp",
    "stamp_owns_path",
    "write_stamp",
]
