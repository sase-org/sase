"""Packaged Stitch glossary names the canonical tracked VCS command."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_stitch_glossary_identifies_stitch_create() -> None:
    data = yaml.safe_load((ROOT / "sase" / "sase.yml").read_text(encoding="utf-8"))
    definition = data["memory"]["glossary"]["Stitch"]["definition"]
    assert "sase stitch create" in definition
    assert "sase commit" not in definition
