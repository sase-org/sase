"""The Python adapter uses the same manifest contract as sase-core."""

from __future__ import annotations

import json
from pathlib import Path

from sase.core.instruction_manifest import normalize_instruction_manifest

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "instruction_manifest_v1.json"
)
_CORE_FIXTURE_RELATIVE = (
    Path("crates") / "sase_core" / "tests" / "fixtures" / "instruction_manifest_v1.json"
)


def _core_fixture_candidates() -> list[Path]:
    repo_root = Path(__file__).resolve().parents[2]
    return [
        repo_root / "sase" / "repos" / "linked" / "sase-core" / _CORE_FIXTURE_RELATIVE,
        repo_root.parent / "sase-core" / _CORE_FIXTURE_RELATIVE,
    ]


def test_manifest_fixture_matches_opened_core_checkout() -> None:
    import pytest

    matches = [path for path in _core_fixture_candidates() if path.is_file()]
    if not matches:
        pytest.skip("opened sase-core checkout with manifest fixture is unavailable")

    expected = _FIXTURE_PATH.read_bytes()
    for path in matches:
        assert path.read_bytes() == expected, path


def test_golden_manifest_normalizes_through_adapter() -> None:
    manifest = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert normalize_instruction_manifest(manifest) == manifest
