"""Shared fixtures and fixture builders for ratchet_core_window tool tests."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "ratchet_core_window"
PLATFORMS = (
    "macosx_10_12_x86_64.macosx_11_0_arm64.macosx_10_12_universal2",
    "manylinux_2_28_aarch64",
    "manylinux_2_28_x86_64",
    "win_amd64",
)


def load_tool() -> ModuleType:
    loader = SourceFileLoader("ratchet_core_window_tool", str(SCRIPT))
    spec = importlib.util.spec_from_file_location(
        "ratchet_core_window_tool",
        SCRIPT,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return load_tool()


def sdist(version: str, *, yanked: bool = False) -> dict[str, object]:
    return {
        "filename": f"sase_core_rs-{version}.tar.gz",
        "packagetype": "sdist",
        "yanked": yanked,
    }


def wheel(version: str, platform: str, *, yanked: bool = False) -> dict[str, object]:
    return {
        "filename": f"sase_core_rs-{version}-cp312-abi3-{platform}.whl",
        "packagetype": "bdist_wheel",
        "yanked": yanked,
    }


def complete_files(version: str, *, yanked: bool = False) -> list[dict[str, object]]:
    return [sdist(version, yanked=yanked)] + [
        wheel(version, platform, yanked=yanked) for platform in PLATFORMS
    ]


def metadata(*versions: str) -> dict[str, object]:
    return {"releases": {version: complete_files(version) for version in versions}}


def pyproject_text(
    specifier: str = ">=0.21.3,<0.22.0",
    *,
    version: str | None = None,
) -> str:
    version_line = f'version = "{version}"\n' if version is not None else ""
    return f"""
[project]
{version_line}dependencies = [
    "jinja2",
    "sase-core-rs{specifier}",
    "schedule",
]
""".lstrip()


def lock_text(version: str = "0.21.3", specifier: str = ">=0.21.3,<0.22.0") -> str:
    return lock_text_for_platforms(version, specifier, platforms=PLATFORMS)


def lock_text_for_platforms(
    version: str,
    specifier: str,
    *,
    platforms: tuple[str, ...],
) -> str:
    wheel_lines = "\n".join(
        f'    {{ url = "https://files.example/sase_core_rs-{version}-cp312-abi3-{platform}.whl", hash = "sha256:{index}", size = {index} }},'
        for index, platform in enumerate(platforms, start=1)
    )
    return f"""
version = 1

[[package]]
name = "sase"
version = "0.16.0"
dependencies = [
    {{ name = "sase-core-rs" }},
]

[package.metadata]
requires-dist = [
    {{ name = "sase-core-rs", specifier = "{specifier}" }},
]

[[package]]
name = "sase-core-rs"
version = "{version}"
source = {{ registry = "https://pypi.org/simple/" }}
sdist = {{ url = "https://files.example/sase_core_rs-{version}.tar.gz", hash = "sha256:sdist", size = 100 }}
wheels = [
{wheel_lines}
]
""".lstrip()


# Live Publish failure (run 32532695440) refused asttokens because uv rewrote a
# top-level lock-format key outside version/sdist/wheels. asttokens 3.0.1 on
# master omits `dependencies`; uv may emit an empty list (or other lock-format
# keys in the same family) while bumping sase-core-rs.
ASTTOKENS_DEPENDENCIES_FIELD = """\
dependencies = []
"""


def asttokens_package(
    version: str,
    digest: str,
    *,
    extra_lines: str = "",
    source: str = 'source = { registry = "https://pypi.org/simple/" }',
) -> str:
    extra = extra_lines
    if extra and not extra.endswith("\n"):
        extra += "\n"
    return f"""
[[package]]
name = "asttokens"
version = "{version}"
{source}
{extra}sdist = {{ url = "https://files.example/asttokens-{version}.tar.gz", hash = "sha256:{digest}-sdist", size = 10 }}
wheels = [
    {{ url = "https://files.example/asttokens-{version}-py3-none-any.whl", hash = "sha256:{digest}-wheel", size = 10 }},
]
""".lstrip()


def lock_text_with_asttokens(
    version: str,
    specifier: str,
    *,
    asttokens_version: str = "3.0.0",
    asttokens_digest: str = "old",
    asttokens_direct: bool = False,
    asttokens_extra_lines: str = "",
    asttokens_source: str = 'source = { registry = "https://pypi.org/simple/" }',
    project_version: str = "0.16.0",
) -> str:
    header, rest = lock_text(version, specifier).split("\n\n", 1)
    if project_version != "0.16.0":
        rest = rest.replace(
            'version = "0.16.0"',
            f'version = "{project_version}"',
            1,
        )
    if asttokens_direct:
        rest = rest.replace(
            '    { name = "sase-core-rs" },',
            '    { name = "asttokens" },\n    { name = "sase-core-rs" },',
            1,
        )
    return (
        f"{header}\n\n"
        f"{asttokens_package(asttokens_version, asttokens_digest, extra_lines=asttokens_extra_lines, source=asttokens_source)}\n"
        f"{rest}"
    )


def write_project(
    root: Path,
    *,
    specifier: str = ">=0.21.3,<0.22.0",
    lock_version: str = "0.21.3",
    project_version: str | None = None,
) -> tuple[Path, Path]:
    pyproject = root / "pyproject.toml"
    uv_lock = root / "uv.lock"
    pyproject.write_text(
        pyproject_text(specifier, version=project_version),
        encoding="utf-8",
    )
    uv_lock.write_text(lock_text(lock_version, specifier), encoding="utf-8")
    (root / "README.md").write_text("# fixture\n", encoding="utf-8")
    return pyproject, uv_lock


def write_project_with_asttokens(
    root: Path,
    *,
    asttokens_direct: bool = False,
    asttokens_version: str = "3.0.0",
    asttokens_extra_lines: str = "",
    asttokens_source: str = 'source = { registry = "https://pypi.org/simple/" }',
) -> tuple[Path, Path]:
    pyproject = root / "pyproject.toml"
    uv_lock = root / "uv.lock"
    specifier = ">=0.21.3,<0.22.0"
    pyproject.write_text(pyproject_text(specifier), encoding="utf-8")
    uv_lock.write_text(
        lock_text_with_asttokens(
            "0.21.3",
            specifier,
            asttokens_direct=asttokens_direct,
            asttokens_version=asttokens_version,
            asttokens_extra_lines=asttokens_extra_lines,
            asttokens_source=asttokens_source,
        ),
        encoding="utf-8",
    )
    (root / "README.md").write_text("# fixture\n", encoding="utf-8")
    return pyproject, uv_lock


def successful_lock_runner(
    tool: ModuleType,
    *,
    platforms: tuple[str, ...] = PLATFORMS,
):
    def _runner(project_dir: Path, target: object) -> subprocess.CompletedProcess[str]:
        specifier = tool.dependency_specifier_for_floor(target)
        (project_dir / "uv.lock").write_text(
            lock_text_for_platforms(target.raw, specifier, platforms=platforms),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(["uv", "lock"], 0, "", "")

    return _runner


def asttokens_refresh_lock_runner(
    tool: ModuleType,
    *,
    asttokens_version: str = "3.0.1",
    asttokens_digest: str = "new",
    asttokens_direct: bool = False,
    asttokens_extra_lines: str = "",
    asttokens_source: str = 'source = { registry = "https://pypi.org/simple/" }',
    project_version: str = "0.16.0",
):
    def _runner(project_dir: Path, target: object) -> subprocess.CompletedProcess[str]:
        specifier = tool.dependency_specifier_for_floor(target)
        (project_dir / "uv.lock").write_text(
            lock_text_with_asttokens(
                target.raw,
                specifier,
                asttokens_direct=asttokens_direct,
                asttokens_digest=asttokens_digest,
                asttokens_version=asttokens_version,
                asttokens_extra_lines=asttokens_extra_lines,
                asttokens_source=asttokens_source,
                project_version=project_version,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(["uv", "lock"], 0, "", "")

    return _runner
