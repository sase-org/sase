"""Tests for local Rust-extension install cleanup helpers."""

from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[1]
_TOOL_PATH = _REPO_ROOT / "tools" / "purge_sase_core_rs_extensions"


def _load_tool() -> dict[str, Any]:
    return runpy.run_path(str(_TOOL_PATH), run_name="purge_sase_core_rs_extensions")


def test_purge_sase_core_rs_extensions_removes_shadowing_native_artifacts(
    tmp_path: Path,
) -> None:
    site_packages = tmp_path / "site-packages"
    package_dir = site_packages / "sase_core_rs"
    package_dir.mkdir(parents=True)

    stale_tagged = package_dir / "sase_core_rs.cpython-314-x86_64-linux-gnu.so"
    abi3 = package_dir / "sase_core_rs.abi3.so"
    flat = site_packages / "sase_core_rs.cpython-313-x86_64-linux-gnu.so"
    keep_init = package_dir / "__init__.py"
    keep_python = package_dir / "sase_core_rs.py"
    keep_unrelated = package_dir / "other_extension.so"

    for path in (
        stale_tagged,
        abi3,
        flat,
        keep_init,
        keep_python,
        keep_unrelated,
    ):
        path.write_bytes(b"placeholder")

    tool = _load_tool()
    removed = tool["purge_sase_core_rs_extensions"]([site_packages])

    assert removed == sorted([flat, abi3, stale_tagged])
    assert not stale_tagged.exists()
    assert not abi3.exists()
    assert not flat.exists()
    assert keep_init.exists()
    assert keep_python.exists()
    assert keep_unrelated.exists()
