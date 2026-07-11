"""Tests for project-local SASE management authorization."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.project_management import enable_sase_management, project_management_status


@pytest.mark.parametrize(
    "content, expected_managed, expected_error",
    [
        (None, False, None),
        ("", False, None),
        ("is_sase_managed: false\n", False, None),
        ("is_sase_managed: true\n", True, None),
        ("memory:\n  enabled: true\n", False, None),
        ('is_sase_managed: "yes"\n', False, "must be a boolean"),
        ("is_sase_managed: 1\n", False, "must be a boolean"),
        ("- not\n- a mapping\n", False, "expected a YAML mapping"),
        ("is_sase_managed: [\n", False, "failed to parse YAML"),
    ],
)
def test_project_management_status(
    tmp_path: Path,
    content: str | None,
    expected_managed: bool,
    expected_error: str | None,
) -> None:
    config_path = tmp_path / "sase.yml"
    if content is not None:
        config_path.write_text(content, encoding="utf-8")

    status = project_management_status(config_path)

    assert status.is_sase_managed is expected_managed
    assert status.valid is (expected_error is None)
    if expected_error is None:
        assert status.error is None
    else:
        assert status.error is not None
        assert expected_error in status.error


def test_enable_sase_management_preserves_comments(tmp_path: Path) -> None:
    config_path = tmp_path / "sase.yml"
    config_path.write_text(
        "# Keep this comment\nlinked_repos: []\nis_sase_managed: false # local\n",
        encoding="utf-8",
    )

    update = enable_sase_management(config_path)

    assert update.changed is True
    assert update.error is None
    assert config_path.read_text(encoding="utf-8") == (
        "# Keep this comment\nlinked_repos: []\nis_sase_managed: true # local\n"
    )


def test_enable_sase_management_rejects_invalid_yaml_without_writing(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "sase.yml"
    original = "is_sase_managed: [\n"
    config_path.write_text(original, encoding="utf-8")

    update = enable_sase_management(config_path)

    assert update.changed is False
    assert update.error is not None
    assert config_path.read_text(encoding="utf-8") == original
