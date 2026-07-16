"""Tests for best-effort plan inventory path metadata."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.main.plan_inventory_paths import plan_metadata_for_path


def test_plan_metadata_normalizes_title_and_tier_in_one_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = tmp_path / "unicode.md"
    plan.write_text(
        "---\ntitle: >-\n  Ship   café —\n  safely\ntier: ' EPIC '\n---\n# Plan\n",
        encoding="utf-8",
    )
    real_read_text = Path.read_text
    reads: list[Path] = []

    def read_text(
        path: Path,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        reads.append(path)
        return real_read_text(path, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", read_text)

    metadata = plan_metadata_for_path(str(plan))
    assert (metadata.title, metadata.tier) == ("Ship café — safely", "epic")
    assert reads == [plan]


@pytest.mark.parametrize(
    ("content", "tier"),
    [
        ("# No frontmatter\n", "-"),
        ("---\ntitle: '   '\ntier: tale\n---\n# Blank\n", "tale"),
        ("---\ntitle: [not, text]\ntier: epic\n---\n# Wrong type\n", "epic"),
        ("---\ntitle: [unterminated\n---\n# Malformed\n", "-"),
        ("---\n- title\n- tier\n---\n# Wrong shape\n", "-"),
    ],
)
def test_plan_metadata_returns_null_title_for_legacy_and_malformed_content(
    tmp_path: Path,
    content: str,
    tier: str,
) -> None:
    plan = tmp_path / "legacy.md"
    plan.write_text(content, encoding="utf-8")

    metadata = plan_metadata_for_path(str(plan))
    assert (metadata.title, metadata.tier) == (None, tier)


def test_plan_metadata_tolerates_invalid_utf8_missing_and_unreadable_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_utf8 = tmp_path / "invalid.md"
    invalid_utf8.write_bytes(b"\xff\xfe")
    missing = tmp_path / "missing.md"

    invalid_metadata = plan_metadata_for_path(str(invalid_utf8))
    missing_metadata = plan_metadata_for_path(str(missing))
    assert (invalid_metadata.title, invalid_metadata.tier) == (None, "-")
    assert (missing_metadata.title, missing_metadata.tier) == (None, "-")

    def deny_read(*args: object, **kwargs: object) -> str:
        raise PermissionError("unreadable")

    monkeypatch.setattr(Path, "read_text", deny_read)
    unreadable_metadata = plan_metadata_for_path(str(invalid_utf8))
    assert (unreadable_metadata.title, unreadable_metadata.tier) == (None, "-")
