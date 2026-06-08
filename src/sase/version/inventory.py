"""Runtime package version inventory collection.

This module is intentionally CLI-free. It collects immutable records for the
packages that make up the running SASE runtime so later command/rendering layers
can format the same data for humans or JSON.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlparse

from sase.core.rust import RUST_EXTENSION_MODULE_NAME

HOST_DISTRIBUTION_NAME = "sase"
CORE_DISTRIBUTION_NAME = "sase-core-rs"

PackageRole = Literal["host", "core", "plugin"]
InstallType = Literal["editable", "wheel", "unknown"]
SourceKind = Literal["python", "rust"]
GitProbe = Callable[[Path], "GitProbeResult"]

_GIT_TIMEOUT_SECONDS = 1.0
_VERSION_TAG_RE = re.compile(r"^v(?P<version>\d+\.\d+\.\d+(?:[-.a-zA-Z0-9]*)?)$")


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
class _DirectUrlInfo:
    install_type: InstallType
    source_root: Path | None


@dataclass(frozen=True)
class _ImportResolution:
    import_path: Path | None
    code_directory: Path | None
    warning: str | None = None


def derive_display_version(
    base_version: str | None,
    git: GitVersionMetadata | None,
) -> str:
    """Return the effective display version for source and git metadata."""
    if git is None:
        return base_version or "<unknown>"

    tag_version = _version_from_tag(git.tag)
    if tag_version:
        distance = git.distance or 0
        if distance == 0 and not git.dirty:
            return tag_version
        suffix = f"{distance}.g{git.short_commit}"
        if git.dirty:
            suffix = f"{suffix}.dirty"
        return f"{tag_version}+{suffix}"

    if base_version is None:
        return "<unknown>"

    suffix = f"untagged.g{git.short_commit}"
    if git.dirty:
        suffix = f"{suffix}.dirty"
    return f"{base_version}+{suffix}"


def probe_git_metadata(source_root: Path) -> GitProbeResult:
    """Probe git state for ``source_root`` with short timeouts.

    Git failures are represented as warnings so inventory collection remains
    useful in non-git, wheel, or broken-git environments.
    """
    try:
        git_root_text = _run_git(source_root, "rev-parse", "--show-toplevel")
        git_root = Path(git_root_text)
        commit = _run_git(git_root, "rev-parse", "HEAD")
        short_commit = _run_git(git_root, "rev-parse", "--short=9", "HEAD")
        dirty = bool(_run_git(git_root, "status", "--porcelain"))
    except FileNotFoundError:
        return GitProbeResult(None, "git is not available on PATH")
    except subprocess.TimeoutExpired:
        return GitProbeResult(None, f"git probe timed out for {source_root}")
    except subprocess.CalledProcessError as exc:
        return GitProbeResult(
            None,
            f"git metadata unavailable for {source_root}: {exc.stderr.strip() or exc}",
        )

    tag: str | None = None
    distance: int | None = None
    try:
        tag = _run_git(
            git_root,
            "describe",
            "--tags",
            "--match",
            "v[0-9]*",
            "--abbrev=0",
            "HEAD",
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        tag = None

    if tag:
        try:
            distance = int(_run_git(git_root, "rev-list", "--count", f"{tag}..HEAD"))
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
            distance = None

    return GitProbeResult(
        GitVersionMetadata(
            root=str(git_root),
            commit=commit,
            short_commit=short_commit,
            tag=tag,
            distance=distance,
            dirty=dirty,
        )
    )


def collect_runtime_version_inventory(
    *, git_probe: GitProbe | None = probe_git_metadata
) -> RuntimeVersionInventory:
    """Collect the Phase 1 runtime inventory for ``sase`` and ``sase-core-rs``."""
    packages = (
        collect_package_record(
            HOST_DISTRIBUTION_NAME,
            role="host",
            import_module="sase",
            source_kind="python",
            git_probe=git_probe,
        ),
        collect_package_record(
            CORE_DISTRIBUTION_NAME,
            role="core",
            import_module=RUST_EXTENSION_MODULE_NAME,
            source_kind="rust",
            git_probe=git_probe,
        ),
    )
    return RuntimeVersionInventory(
        executable=sys.argv[0],
        python_executable=sys.executable,
        python_version=sys.version.split()[0],
        packages=packages,
    )


def collect_package_record(
    distribution_name: str,
    *,
    role: PackageRole,
    import_module: str | None,
    source_kind: SourceKind,
    git_probe: GitProbe | None = probe_git_metadata,
) -> VersionPackageRecord:
    """Collect one package record without importing provider/plugin code."""
    warnings: list[str] = []
    dist = _find_distribution(distribution_name, warnings)
    metadata_name = _distribution_name(dist) or distribution_name
    distribution_version = _distribution_version(dist)
    distribution_location = _distribution_location(dist)
    direct_url = _direct_url_info(dist, warnings)
    install_type = direct_url.install_type if direct_url else _install_type(dist)

    import_resolution = _resolve_import(import_module)
    if import_resolution.warning:
        warnings.append(import_resolution.warning)

    source_root = _source_root(
        source_kind=source_kind,
        direct_url=direct_url,
        import_resolution=import_resolution,
        distribution_location=distribution_location,
    )
    source_version = _source_version(source_kind, source_root, install_type, warnings)
    git_result = _probe_git(source_root, git_probe)
    if git_result.warning:
        warnings.append(git_result.warning)

    display_version = derive_display_version(
        source_version or distribution_version,
        git_result.metadata,
    )
    code_directory = _code_directory(
        source_kind=source_kind,
        install_type=install_type,
        source_root=source_root,
        import_resolution=import_resolution,
    )

    return VersionPackageRecord(
        name=metadata_name,
        role=role,
        display_version=display_version,
        distribution_version=distribution_version,
        source_version=source_version,
        import_module=import_module,
        import_path=_path_str(import_resolution.import_path),
        code_directory=_path_str(code_directory),
        source_root=_path_str(source_root),
        distribution_location=_path_str(distribution_location),
        install_type=install_type,
        git=git_result.metadata,
        warnings=tuple(warnings),
    )


def _find_distribution(
    distribution_name: str,
    warnings: list[str],
) -> importlib.metadata.Distribution | None:
    try:
        return importlib.metadata.distribution(distribution_name)
    except importlib.metadata.PackageNotFoundError:
        warnings.append(
            f"installed distribution metadata not found for {distribution_name}"
        )
        return None


def _distribution_name(dist: importlib.metadata.Distribution | None) -> str | None:
    if dist is None:
        return None
    return _metadata_value(dist.metadata, "Name")


def _distribution_version(dist: importlib.metadata.Distribution | None) -> str | None:
    if dist is None:
        return None
    version = getattr(dist, "version", None)
    if isinstance(version, str) and version:
        return version
    return _metadata_value(dist.metadata, "Version")


def _distribution_location(
    dist: importlib.metadata.Distribution | None,
) -> Path | None:
    if dist is None:
        return None
    try:
        return Path(str(dist.locate_file("")))
    except Exception:
        return None


def _install_type(dist: importlib.metadata.Distribution | None) -> InstallType:
    return "wheel" if dist is not None else "unknown"


def _direct_url_info(
    dist: importlib.metadata.Distribution | None,
    warnings: list[str],
) -> _DirectUrlInfo | None:
    if dist is None:
        return None
    try:
        text = dist.read_text("direct_url.json")
    except Exception as exc:
        warnings.append(f"could not read direct_url.json for distribution: {exc}")
        return None
    if not text:
        return None

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        warnings.append(f"could not parse direct_url.json: {exc}")
        return None

    dir_info = payload.get("dir_info")
    editable = isinstance(dir_info, dict) and dir_info.get("editable") is True
    source_root = _path_from_url(payload.get("url")) if editable else None
    if editable and source_root is None:
        warnings.append("editable direct_url.json did not contain a file URL")
    return _DirectUrlInfo(
        install_type="editable" if editable else "wheel",
        source_root=source_root,
    )


def _path_from_url(value: object) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme != "file":
        return None
    if parsed.netloc and parsed.netloc not in {"", "localhost"}:
        return None
    return Path(unquote(parsed.path))


def _resolve_import(import_module: str | None) -> _ImportResolution:
    if not import_module:
        return _ImportResolution(None, None)
    try:
        spec = importlib.util.find_spec(import_module)
    except Exception as exc:
        return _ImportResolution(
            None,
            None,
            f"could not resolve import module {import_module}: {exc}",
        )
    if spec is None:
        return _ImportResolution(
            None,
            None,
            f"could not resolve import module {import_module}",
        )

    search_locations = spec.submodule_search_locations
    if search_locations:
        code_directory = Path(next(iter(search_locations)))
        return _ImportResolution(code_directory, code_directory)

    origin = spec.origin
    if not origin or origin in {"built-in", "frozen"}:
        return _ImportResolution(
            None,
            None,
            f"import module {import_module} has no filesystem path",
        )

    import_path = Path(origin)
    return _ImportResolution(import_path, import_path.parent)


def _source_root(
    *,
    source_kind: SourceKind,
    direct_url: _DirectUrlInfo | None,
    import_resolution: _ImportResolution,
    distribution_location: Path | None,
) -> Path | None:
    if source_kind == "python":
        if direct_url and direct_url.source_root:
            return direct_url.source_root
        if import_resolution.code_directory:
            return _find_ancestor_with_file(
                import_resolution.code_directory,
                "pyproject.toml",
            )
        return None

    candidates = [
        direct_url.source_root if direct_url else None,
        import_resolution.code_directory,
        distribution_location,
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        cargo_root = _find_cargo_version_root(candidate)
        if cargo_root:
            return cargo_root
    return direct_url.source_root if direct_url else None


def _source_version(
    source_kind: SourceKind,
    source_root: Path | None,
    install_type: InstallType,
    warnings: list[str],
) -> str | None:
    if source_root is None:
        return None

    version = (
        _python_source_version(source_root)
        if source_kind == "python"
        else _rust_source_version(source_root)
    )
    if version is None and install_type == "editable":
        warnings.append(f"source version metadata not found under {source_root}")
    return version


def _python_source_version(source_root: Path) -> str | None:
    data = _read_toml(source_root / "pyproject.toml")
    project = data.get("project")
    if not isinstance(project, dict):
        return None
    version = project.get("version")
    return version if isinstance(version, str) and version else None


def _rust_source_version(source_root: Path) -> str | None:
    cargo_root = _find_cargo_version_root(source_root) or source_root
    data = _read_toml(cargo_root / "Cargo.toml")
    workspace = data.get("workspace")
    if isinstance(workspace, dict):
        package = workspace.get("package")
        if isinstance(package, dict):
            version = package.get("version")
            if isinstance(version, str) and version:
                return version

    package = data.get("package")
    if isinstance(package, dict):
        version = package.get("version")
        if isinstance(version, str) and version:
            return version
    return None


def _find_cargo_version_root(start: Path) -> Path | None:
    for candidate in _ancestors(start):
        data = _read_toml(candidate / "Cargo.toml")
        if not data:
            continue
        workspace = data.get("workspace")
        if isinstance(workspace, dict):
            package = workspace.get("package")
            if isinstance(package, dict) and isinstance(package.get("version"), str):
                return candidate
        package = data.get("package")
        if isinstance(package, dict) and isinstance(package.get("version"), str):
            return candidate
    return None


def _find_ancestor_with_file(start: Path, filename: str) -> Path | None:
    for candidate in _ancestors(start):
        if (candidate / filename).is_file():
            return candidate
    return None


def _ancestors(start: Path) -> tuple[Path, ...]:
    current = start if start.is_dir() else start.parent
    return (current, *current.parents)


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as f:
            value = tomllib.load(f)
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _probe_git(
    source_root: Path | None,
    git_probe: GitProbe | None,
) -> GitProbeResult:
    if source_root is None or git_probe is None:
        return GitProbeResult(None)
    return git_probe(source_root)


def _code_directory(
    *,
    source_kind: SourceKind,
    install_type: InstallType,
    source_root: Path | None,
    import_resolution: _ImportResolution,
) -> Path | None:
    if source_kind == "rust" and install_type == "editable" and source_root:
        return source_root
    return import_resolution.code_directory or source_root


def _version_from_tag(tag: str | None) -> str | None:
    if tag is None:
        return None
    match = _VERSION_TAG_RE.fullmatch(tag)
    if match is None:
        return None
    return match.group("version")


def _run_git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
    )
    return completed.stdout.strip()


def _metadata_value(metadata: object, key: str) -> str | None:
    getter = getattr(metadata, "get", None)
    if not callable(getter):
        return None
    value = getter(key)
    return value if isinstance(value, str) and value else None


def _path_str(path: Path | None) -> str | None:
    if path is None:
        return None
    return str(path)
