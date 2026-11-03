"""Shared loader and fixture builders for the release_candidate tool tests."""

from __future__ import annotations

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "release_candidate"

CORE_WHEEL_PLATFORMS = (
    "manylinux_2_28_x86_64",
    "manylinux_2_28_aarch64",
)
CORE_SUFFIXES = (".tar.gz", *(f"{platform}.whl" for platform in CORE_WHEEL_PLATFORMS))
SOURCE_PIN = "a" * 40
TAG_SHA = "b" * 40


def _looks_like_sha(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 40:
        return False
    return all(char in "0123456789abcdefABCDEF" for char in value)


def containment_record(**overrides: object) -> dict[str, object]:
    core_version = str(overrides.get("core_version", "0.42.0"))
    pin = str(overrides.get("pin", SOURCE_PIN))
    record: dict[str, object] = {
        "pin": pin,
        "core_version": core_version,
        "tag": f"v{core_version}",
        "compare_status": "identical",
        "tag_sha": TAG_SHA,
    }
    record.update(overrides)
    return record


def load_tool() -> ModuleType:
    loader = SourceFileLoader("release_candidate_tool", str(SCRIPT))
    spec = importlib.util.spec_from_file_location(
        "release_candidate_tool",
        SCRIPT,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def core_files(
    version: str = "0.42.0", *, yanked: bool = False
) -> list[dict[str, object]]:
    files: list[dict[str, object]] = [
        {
            "filename": f"sase_core_rs-{version}.tar.gz",
            "packagetype": "sdist",
            "yanked": yanked,
            "sha256": "4b9ff64d4bd495216ecf1a29861cbc31f47f9af4e5d39e258ec18c9936cabea7",
            "url": f"https://files.pythonhosted.org/packages/sase_core_rs-{version}.tar.gz",
        }
    ]
    for platform in CORE_WHEEL_PLATFORMS:
        filename = f"sase_core_rs-{version}-cp312-abi3-{platform}.whl"
        files.append(
            {
                "filename": filename,
                "packagetype": "bdist_wheel",
                "yanked": yanked,
                "sha256": "c26d3d23780e261ef0d8b40bf954bb3a61b10197b8d9978184b33b0a966f8a0f",
                "url": f"https://files.pythonhosted.org/packages/{filename}",
            }
        )
    return files


def dists(version: str = "0.18.0") -> list[dict[str, object]]:
    return [
        {
            "filename": f"sase-{version}-py3-none-any.whl",
            "packagetype": "bdist_wheel",
            "size": 1024,
            "sha256": "a" * 64,
            "asset": f"gh-release:v{version}/sase-{version}-py3-none-any.whl",
        },
        {
            "filename": f"sase-{version}.tar.gz",
            "packagetype": "sdist",
            "size": 2048,
            "sha256": "b" * 64,
            "asset": f"gh-release:v{version}/sase-{version}.tar.gz",
        },
    ]


def seal_kwargs(**overrides: object) -> dict[str, object]:
    core_version = str(overrides.get("core_version", "0.42.0"))
    pin_override = overrides.get("core_source_pin", SOURCE_PIN)
    pin = str(pin_override) if _looks_like_sha(pin_override) else SOURCE_PIN
    kwargs: dict[str, object] = {
        "repository": "sase-org/sase",
        "version": "0.18.0",
        "tag": "refs/tags/v0.18.0",
        "sha": "4e5b7d2eb6c4a5b6c4a5b6c4a5b6c4a5b6c4a5b6",
        "tree": "9" * 40,
        "generation": 1,
        "builder_revision": "sase-org/sase/.github/workflows/release.yml@refs/tags/v0.18.0",
        "builder_run_id": 123,
        "builder_attempt": 1,
        "core_source_pin": pin,
        "core_containment": containment_record(pin=pin, core_version=core_version),
        "core_version": core_version,
        "core_files": core_files(core_version),
        "expected_core_suffixes": list(CORE_SUFFIXES),
        "dists": dists(),
    }
    kwargs.update(overrides)
    return kwargs
