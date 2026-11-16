"""Tests for the eager-annotation compatibility lint tool."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "check_eager_annotations"


def _run_tool(src_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(TOOL_PATH),
            "--src",
            str(src_root),
            "--package",
            "fakepkg",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _package(tmp_path: Path) -> Path:
    package = tmp_path / "src" / "fakepkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    return package


def test_tool_script_is_executable() -> None:
    assert TOOL_PATH.exists()
    assert TOOL_PATH.stat().st_mode & 0o111


def test_reports_eager_slice_annotation_on_every_python_version(tmp_path: Path) -> None:
    package = _package(tmp_path)
    (package / "bad.py").write_text(
        "from typing import SupportsIndex, overload\n"
        "class Items(list[str]):\n"
        "    @overload\n"
        "    def __getitem__(self, index: SupportsIndex, /) -> str: ...\n"
        "    @overload\n"
        "    def __getitem__(self, index: slice[int | None, int | None, int | None], /) -> list[str]: ...\n"
        "    def __getitem__(self, index: slice[int | None, int | None, int | None], /) -> str | list[str]:\n"
        "        return super().__getitem__(index)\n",
        encoding="utf-8",
    )

    result = _run_tool(tmp_path / "src")

    assert result.returncode == 1
    assert "fakepkg/bad.py:" in result.stdout
    assert "slice" in result.stdout
    assert "Python 3.12 evaluates annotations eagerly" in result.stdout


def test_future_annotations_suppresses_slice_finding(tmp_path: Path) -> None:
    package = _package(tmp_path)
    (package / "safe.py").write_text(
        "from __future__ import annotations\n"
        "class Items(list[str]):\n"
        "    def __getitem__(self, index: slice[int | None, int | None, int | None], /) -> str | list[str]:\n"
        "        return super().__getitem__(index)\n",
        encoding="utf-8",
    )

    result = _run_tool(tmp_path / "src")

    assert result.returncode == 0
    assert result.stdout == ""


def test_reports_type_checking_only_annotation_name(tmp_path: Path) -> None:
    package = _package(tmp_path)
    (package / "types.py").write_text("class Hidden: ...\n", encoding="utf-8")
    (package / "bad.py").write_text(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from fakepkg.types import Hidden\n"
        "def build(value: Hidden) -> None:\n"
        "    pass\n",
        encoding="utf-8",
    )

    result = _run_tool(tmp_path / "src")

    assert result.returncode == 1
    assert "fakepkg/bad.py:" in result.stdout
    assert "NameError" in result.stdout


def test_never_imports_package_main_module(tmp_path: Path) -> None:
    package = _package(tmp_path)
    marker = tmp_path / "imported-main"
    (package / "__main__.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
        encoding="utf-8",
    )

    result = _run_tool(tmp_path / "src")

    assert result.returncode == 0
    assert not marker.exists()
