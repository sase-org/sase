"""Machine-local project frontmatter handling for plan documents."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.sdd.plan_project import (
    plan_project_for_artifacts_dir,
    _read_plan_project,
    read_plan_project_file,
    strip_plan_project,
)


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("---\nproject: ' Display Name '\n---\n# Plan\n", "Display Name"),
        ("---\ntier: tale\n---\n# Plan\n", None),
        ("---\nproject: '   '\n---\n# Plan\n", None),
        ("---\nproject: 42\n---\n# Plan\n", None),
        ("---\nproject: [broken\n---\n# Plan\n", None),
        ("# Plan\n", None),
    ],
)
def test_read_plan_project_is_tolerant(content: str, expected: str | None) -> None:
    assert _read_plan_project(content) == expected


def test_read_plan_project_file_handles_missing_and_invalid_utf8(
    tmp_path: Path,
) -> None:
    assert read_plan_project_file(tmp_path / "missing.md") is None
    invalid = tmp_path / "invalid.md"
    invalid.write_bytes(b"---\nproject: \xff\n---\n")
    assert read_plan_project_file(invalid) is None


def test_strip_plan_project_is_exact_when_absent_and_removes_when_present() -> None:
    absent = "---\ntier: tale\n---\n\n# Plan  \n"
    assert strip_plan_project(absent) == absent
    assert strip_plan_project("# Plan\n") == "# Plan\n"

    present = "---\ntier: tale\nproject: Example\n---\n# Plan\n"
    assert strip_plan_project(present) == "---\ntier: tale\n---\n# Plan\n"


@pytest.mark.parametrize(
    ("project_key", "record", "expected"),
    [
        (
            "registered",
            SimpleNamespace(project_name="registered", display_name="Display"),
            "Display",
        ),
        ("unregistered", None, None),
        (
            "registered",
            SimpleNamespace(project_name="different", display_name="Display"),
            None,
        ),
    ],
)
def test_plan_project_for_artifacts_dir_uses_registered_display_name(
    monkeypatch: pytest.MonkeyPatch,
    project_key: str,
    record: SimpleNamespace | None,
    expected: str | None,
) -> None:
    from sase import project_aliases
    from sase.turns import settlement

    monkeypatch.setattr(
        settlement, "project_name_from_artifacts_dir", lambda _path: project_key
    )
    monkeypatch.setattr(
        project_aliases,
        "registered_project_records",
        lambda: [] if record is None else [record],
    )

    assert plan_project_for_artifacts_dir("/artifacts") == expected


@pytest.mark.parametrize("project_key", ["home", "HOME"])
def test_plan_project_for_artifacts_dir_omits_home(
    monkeypatch: pytest.MonkeyPatch, project_key: str
) -> None:
    from sase.turns import settlement

    monkeypatch.setattr(
        settlement, "project_name_from_artifacts_dir", lambda _path: project_key
    )
    assert plan_project_for_artifacts_dir("/artifacts") is None


def test_write_sdd_files_strips_project_from_store_copy(tmp_path: Path) -> None:
    from sase.sdd.files import write_sdd_files

    source = tmp_path / "proposal.md"
    source.write_text(
        "---\ntier: tale\ntitle: Example\ngoal: Example works\n"
        "size: small\nproject: Display Name\n---\n# Plan\n\nShip it.\n",
        encoding="utf-8",
    )
    plans_root = tmp_path / "plans"

    with (
        patch("sase.file_references.format_with_prettier", side_effect=lambda x: x),
        patch(
            "sase.sdd.plan_header_writes.project_plan_header_sections",
            side_effect=lambda content, **_kwargs: content,
        ),
    ):
        _prompt, plan_path = write_sdd_files(
            tmp_path / "sdd",
            "proposal",
            "# Prompt\n",
            str(source),
            plan_tier="tale",
            plans_root=plans_root,
            yyyymm="202610",
        )

    assert "project:" not in plan_path.read_text(encoding="utf-8")
    assert "project: Display Name" in source.read_text(encoding="utf-8")
