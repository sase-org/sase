"""Renderer-environment fingerprint checks for ACE PNG snapshots."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_MANIFEST_PATH = Path(__file__).with_name("renderer_env.json")
_FONTS_DIR = Path(__file__).with_name("fonts")
_REMEDIATION = (
    "Run `just install-visual`; if this is an intentional renderer upgrade, "
    "update the visual pins and renderer_env.json, then follow the snapshot "
    "regeneration workflow."
)


class RendererEnvironmentError(RuntimeError):
    """Raised when visual snapshots would use an unapproved renderer stack."""


@dataclass(frozen=True)
class RendererEnvironmentManifest:
    """Committed inputs that define the ACE PNG golden corpus."""

    packages: dict[str, str]
    fonts: dict[str, str]
    python_version: str
    platform: str


def load_renderer_environment_manifest(
    path: Path = _MANIFEST_PATH,
) -> RendererEnvironmentManifest:
    """Load the committed renderer-environment manifest."""
    data = json.loads(path.read_text(encoding="utf-8"))
    diagnostics = data["diagnostics"]
    return RendererEnvironmentManifest(
        packages=dict(data["packages"]),
        fonts=dict(data["fonts"]),
        python_version=diagnostics["python_version"],
        platform=diagnostics["platform"],
    )


def renderer_environment_mismatches(
    manifest: RendererEnvironmentManifest,
    *,
    package_version: Callable[[str], str] = importlib.metadata.version,
    fonts_dir: Path = _FONTS_DIR,
) -> list[str]:
    """Return package and font differences from the committed fingerprint."""
    mismatches: list[str] = []
    for package, expected in sorted(manifest.packages.items()):
        try:
            actual = package_version(package)
        except importlib.metadata.PackageNotFoundError:
            mismatches.append(
                f"package {package}: expected {expected}, but it is not installed"
            )
            continue
        if actual != expected:
            mismatches.append(f"package {package}: expected {expected}, found {actual}")

    actual_fonts = {
        path.name: path
        for path in fonts_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".otf", ".ttf"}
    }
    for font, expected in sorted(manifest.fonts.items()):
        path = actual_fonts.get(font)
        if path is None:
            mismatches.append(
                f"font {font}: expected sha256:{expected}, but is missing"
            )
            continue
        actual = _sha256(path)
        if actual != expected:
            mismatches.append(
                f"font {font}: expected sha256:{expected}, found sha256:{actual}"
            )

    for font in sorted(actual_fonts.keys() - manifest.fonts.keys()):
        mismatches.append(
            f"font {font}: bundled font is missing from renderer_env.json"
        )
    return mismatches


def assert_renderer_environment(
    *,
    update: bool,
    manifest: RendererEnvironmentManifest | None = None,
    package_version: Callable[[str], str] = importlib.metadata.version,
    fonts_dir: Path = _FONTS_DIR,
    platform_system: Callable[[], str] = platform.system,
    platform_machine: Callable[[], str] = platform.machine,
    python_version: Callable[[], str] = platform.python_version,
) -> None:
    """Fail fast for a skewed stack or unsafe golden regeneration host."""
    expected = manifest or load_renderer_environment_manifest()
    system = platform_system()
    machine = platform_machine()
    runtime = f"{system}-{machine}"
    mismatches = renderer_environment_mismatches(
        expected,
        package_version=package_version,
        fonts_dir=fonts_dir,
    )
    if mismatches:
        heading = (
            "ACE PNG golden regeneration refused because the renderer "
            "environment fingerprint does not match:"
            if update
            else "ACE PNG renderer environment mismatch; snapshots were not run:"
        )
        details = "\n".join(f"  - {mismatch}" for mismatch in mismatches)
        raise RendererEnvironmentError(
            f"{heading}\n{details}\n"
            f"Current runtime (diagnostic only): Python {python_version()} on "
            f"{runtime}.\n"
            "Manifest runtime (diagnostic only): Python "
            f"{expected.python_version} on {expected.platform}.\n"
            f"{_REMEDIATION}"
        )

    if update and system != "Linux":
        raise RendererEnvironmentError(
            "ACE PNG golden regeneration refused: goldens must be generated on "
            f"Linux, but the current platform is {runtime}.\n{_REMEDIATION}"
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
