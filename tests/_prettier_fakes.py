"""Test-only prettier unavailability fakes.

Production no longer has ``SASE_DISABLE_PRETTIER``. Tests that need
deterministic unformatted markdown must hide prettier from PATH or from
``shutil.which`` instead of toggling a feature flag.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest


def hide_prettier_from_path(monkeypatch: pytest.MonkeyPatch, *, stub_dir: Path) -> None:
    """Prepend a failing prettier stub so host PATH directories stay intact.

    Dropping PATH entries that contain prettier also hides sibling binaries
    in the same directory (this host keeps prettier next to ``sase`` in
    ``~/.local/bin``). Child processes inherit the stub first and fall back
    through prettier's error path to the original text.
    """
    stub_dir.mkdir(parents=True, exist_ok=True)
    stub = stub_dir / "prettier"
    stub.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    stub.chmod(0o755)
    current = os.environ.get("PATH", "")
    monkeypatch.setenv(
        "PATH",
        os.pathsep.join((str(stub_dir), current)) if current else str(stub_dir),
    )


def fake_prettier_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``format_with_prettier`` treat prettier as missing in-process."""
    real_which = shutil.which

    def _which(cmd: str, mode: int = os.F_OK, path: str | None = None) -> str | None:
        if cmd == "prettier":
            return None
        return real_which(cmd, mode=mode, path=path)

    monkeypatch.setattr("sase.file_references.shutil.which", _which)
