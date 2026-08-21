"""PATH-safe prettier unavailability fakes for tests."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from tests._prettier_fakes import hide_prettier_from_path


def test_hide_prettier_from_path_keeps_sibling_binaries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sibling_dir = tmp_path / "local-bin"
    sibling_dir.mkdir()
    prettier = sibling_dir / "prettier"
    sase = sibling_dir / "sase"
    prettier.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    sase.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    prettier.chmod(0o755)
    sase.chmod(0o755)
    monkeypatch.setenv("PATH", str(sibling_dir))

    stub_dir = tmp_path / "hide-prettier"
    hide_prettier_from_path(monkeypatch, stub_dir=stub_dir)

    path_parts = os.environ["PATH"].split(os.pathsep)
    assert str(sibling_dir) in path_parts
    found_prettier = shutil.which("prettier")
    assert found_prettier is not None
    assert Path(found_prettier).resolve() == (stub_dir / "prettier").resolve()
    assert shutil.which("sase") == str(sase)
