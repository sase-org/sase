from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ruff_selects_tc004() -> None:
    """Keep Python 3.12 runtime annotations safe from TYPE_CHECKING-only names."""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "TC004" in config["tool"]["ruff"]["lint"]["select"]
