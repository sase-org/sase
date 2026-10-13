"""The Python adapter uses the same manifest contract as sase-core."""

from __future__ import annotations

import json
from pathlib import Path

from sase.core.instruction_manifest import normalize_instruction_manifest

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"
_CORE_FIXTURE_DIR = Path("crates") / "sase_core" / "tests" / "fixtures"
_FIXTURE_VERSIONS = (1, 2)


def _core_fixture_candidates(version: int) -> list[Path]:
    repo_root = Path(__file__).resolve().parents[2]
    relative = _CORE_FIXTURE_DIR / f"instruction_manifest_v{version}.json"
    return [
        repo_root / "sase" / "repos" / "linked" / "sase-core" / relative,
        repo_root.parent / "sase-core" / relative,
    ]


def test_manifest_fixture_matches_opened_core_checkout() -> None:
    import pytest

    for version in _FIXTURE_VERSIONS:
        matches = [path for path in _core_fixture_candidates(version) if path.is_file()]
        if not matches:
            pytest.skip(
                "opened sase-core checkout with manifest fixtures is unavailable"
            )

        expected = (_FIXTURE_DIR / f"instruction_manifest_v{version}.json").read_bytes()
        for path in matches:
            assert path.read_bytes() == expected, path


def test_golden_manifest_normalizes_through_adapter() -> None:
    for version in _FIXTURE_VERSIONS:
        path = _FIXTURE_DIR / f"instruction_manifest_v{version}.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        assert normalize_instruction_manifest(manifest) == manifest
