"""Distribution, import, and source metadata helpers."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from sase.version._models import (
    DirectUrlInfo,
    ImportResolution,
    InstallType,
    SourceKind,
)
from sase.version._utils import metadata_value


def find_distribution(
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


def distribution_name(dist: importlib.metadata.Distribution | None) -> str | None:
    if dist is None:
        return None
    return metadata_value(dist.metadata, "Name")


def distribution_version(dist: importlib.metadata.Distribution | None) -> str | None:
    if dist is None:
        return None
    version = getattr(dist, "version", None)
    if isinstance(version, str) and version:
        return version
    return metadata_value(dist.metadata, "Version")


def distribution_location(
    dist: importlib.metadata.Distribution | None,
) -> Path | None:
    if dist is None:
        return None
    try:
        return Path(str(dist.locate_file("")))
    except Exception:
        return None


def install_type(dist: importlib.metadata.Distribution | None) -> InstallType:
    return "wheel" if dist is not None else "unknown"


def direct_url_info(
    dist: importlib.metadata.Distribution | None,
    warnings: list[str],
) -> DirectUrlInfo | None:
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
    source_root = path_from_url(payload.get("url")) if editable else None
    if editable and source_root is None:
        warnings.append("editable direct_url.json did not contain a file URL")
    return DirectUrlInfo(
        install_type="editable" if editable else "wheel",
        source_root=source_root,
    )


def path_from_url(value: object) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme != "file":
        return None
    if parsed.netloc and parsed.netloc not in {"", "localhost"}:
        return None
    return Path(unquote(parsed.path))


def resolve_import(import_module: str | None) -> ImportResolution:
    if not import_module:
        return ImportResolution(None, None)
    try:
        spec = importlib.util.find_spec(import_module)
    except Exception as exc:
        return ImportResolution(
            None,
            None,
            f"could not resolve import module {import_module}: {exc}",
        )
    if spec is None:
        return ImportResolution(
            None,
            None,
            f"could not resolve import module {import_module}",
        )

    search_locations = spec.submodule_search_locations
    if search_locations:
        code_directory = Path(next(iter(search_locations)))
        return ImportResolution(code_directory, code_directory)

    origin = spec.origin
    if not origin or origin in {"built-in", "frozen"}:
        return ImportResolution(
            None,
            None,
            f"import module {import_module} has no filesystem path",
        )

    import_path = Path(origin)
    return ImportResolution(import_path, import_path.parent)


def source_root(
    *,
    source_kind: SourceKind,
    direct_url: DirectUrlInfo | None,
    install_type: InstallType,
    import_resolution: ImportResolution,
    distribution_location: Path | None,
) -> Path | None:
    if source_kind == "python":
        if direct_url and direct_url.source_root:
            return direct_url.source_root
        if install_type == "editable" and import_resolution.code_directory:
            return find_ancestor_with_file(
                import_resolution.code_directory,
                "pyproject.toml",
            )
        return None

    candidates = [direct_url.source_root if direct_url else None]
    if install_type == "editable":
        # Only editable installs may climb from the import/distribution
        # location; for wheels those live under site-packages and the walk
        # could adopt an unrelated ancestor Cargo.toml as the source root.
        candidates.extend([import_resolution.code_directory, distribution_location])
    for candidate in candidates:
        if candidate is None:
            continue
        cargo_root = find_cargo_version_root(candidate)
        if cargo_root:
            return cargo_root
    return direct_url.source_root if direct_url else None


def source_version(
    source_kind: SourceKind,
    source_root: Path | None,
    install_type: InstallType,
    warnings: list[str],
) -> str | None:
    if source_root is None:
        return None

    version = (
        python_source_version(source_root)
        if source_kind == "python"
        else rust_source_version(source_root)
    )
    if version is None and install_type == "editable":
        warnings.append(f"source version metadata not found under {source_root}")
    return version


def python_source_version(source_root: Path) -> str | None:
    data = read_toml(source_root / "pyproject.toml")
    project = data.get("project")
    if not isinstance(project, dict):
        return None
    version = project.get("version")
    return version if isinstance(version, str) and version else None


def rust_source_version(source_root: Path) -> str | None:
    cargo_root = find_cargo_version_root(source_root) or source_root
    data = read_toml(cargo_root / "Cargo.toml")
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


def find_cargo_version_root(start: Path) -> Path | None:
    for candidate in ancestors(start):
        data = read_toml(candidate / "Cargo.toml")
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


def find_ancestor_with_file(start: Path, filename: str) -> Path | None:
    for candidate in ancestors(start):
        if (candidate / filename).is_file():
            return candidate
    return None


def ancestors(start: Path) -> tuple[Path, ...]:
    current = start if start.is_dir() else start.parent
    return (current, *current.parents)


def read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as f:
            value = tomllib.load(f)
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def code_directory(
    *,
    source_kind: SourceKind,
    install_type: InstallType,
    source_root: Path | None,
    import_resolution: ImportResolution,
    distribution_location: Path | None,
) -> Path | None:
    if source_kind == "rust" and install_type == "editable" and source_root:
        return source_root
    return import_resolution.code_directory or source_root or distribution_location
