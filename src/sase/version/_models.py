"""Data models and shared constants for runtime version inventory."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

HOST_DISTRIBUTION_NAME = "sase"
CORE_DISTRIBUTION_NAME = "sase-core-rs"
CONSOLE_SCRIPT_ENTRY_POINT_GROUP = "console_scripts"
SASE_CHOP_SCRIPT_PREFIX = "sase_chop_"

PackageRole = Literal["host", "core", "plugin"]
InstallType = Literal["editable", "wheel", "unknown"]
SourceKind = Literal["python", "rust"]


@dataclass(frozen=True)
class GitVersionMetadata:
    """Best-effort git metadata for one source checkout."""

    root: str
    commit: str
    short_commit: str
    tag: str | None
    distance: int | None
    dirty: bool

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible primitives."""
        return asdict(self)


@dataclass(frozen=True)
class GitProbeResult:
    """Result of a best-effort git probe."""

    metadata: GitVersionMetadata | None
    warning: str | None = None


GitProbe = Callable[[Path], GitProbeResult]


@dataclass(frozen=True)
class VersionPackageRecord:
    """Version and source-location record for one runtime package."""

    name: str
    role: PackageRole
    display_version: str
    distribution_version: str | None
    source_version: str | None
    import_module: str | None
    import_path: str | None
    code_directory: str | None
    source_root: str | None
    distribution_location: str | None
    install_type: InstallType
    git: GitVersionMetadata | None
    plugin_signals: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible primitives."""
        payload = asdict(self)
        payload["plugin_signals"] = list(self.plugin_signals)
        payload["warnings"] = list(self.warnings)
        return payload


@dataclass(frozen=True)
class RuntimeVersionInventory:
    """Runtime inventory for the current ``sase`` process."""

    executable: str
    python_executable: str
    python_version: str
    packages: tuple[VersionPackageRecord, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible primitives."""
        return {
            "executable": self.executable,
            "python_executable": self.python_executable,
            "python_version": self.python_version,
            "packages": [record.to_dict() for record in self.packages],
        }


@dataclass(frozen=True)
class DirectUrlInfo:
    install_type: InstallType
    source_root: Path | None


@dataclass(frozen=True)
class ImportResolution:
    import_path: Path | None
    code_directory: Path | None
    warning: str | None = None
