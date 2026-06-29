"""Tests for reusable project alias service helpers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
    effective_project_name,
)
from sase.project_aliases import (
    allocate_project_name,
    canonicalize_project_aliases_in_prompt,
    ensure_project_name_locked,
    humanize_project_refs_in_prompt,
    load_project_alias_map,
    set_project_name_locked,
)
from tests.main.project_handler_helpers import (
    _write_project,
    lifecycle_stubs,
    projects_root,
)

__all__ = ["lifecycle_stubs", "projects_root"]


def _record(
    project_name: str,
    *,
    aliases: list[str] | None = None,
    state: str = "active",
    system_managed: bool = False,
    launchable: bool | None = None,
    project_file: str | Path | None = None,
    archive_file: str | Path | None = None,
    display_name: str | None = None,
) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=project_name,
        project_dir=f"/tmp/projects/{project_name}",
        project_file=str(
            project_file or f"/tmp/projects/{project_name}/{project_name}.sase"
        ),
        archive_file=str(archive_file) if archive_file is not None else None,
        workspace_dir=f"/tmp/workspaces/{project_name}",
        state=state,
        state_explicit=False,
        system_managed=system_managed,
        active_claim_count=0,
        launchable=(state == "active" if launchable is None else launchable),
        aliases=list(aliases or []),
        warnings=[],
        parse_warnings=[],
        display_name=display_name,
    )


def test_allocate_project_name_uses_available_base() -> None:
    assert allocate_project_name("foo", [_record("alpha")]) == "foo"


def test_allocate_project_name_walks_underscore_suffixes() -> None:
    records = [
        _record("foo"),
        _record("alpha", aliases=["foo_1"]),
        _record("beta", display_name="foo_2"),
    ]

    assert allocate_project_name("foo", records) == "foo_3"


def test_allocate_project_name_counts_alias_and_display_collisions() -> None:
    records = [
        _record("alpha", aliases=["widgets"]),
        _record("beta", display_name="widgets_1"),
    ]

    assert allocate_project_name("widgets", records) == "widgets_2"


def test_allocate_project_name_reuses_current_project_display_name() -> None:
    records = [
        _record("alpha", display_name="widgets"),
        _record("beta", aliases=["widgets_1"]),
    ]

    assert allocate_project_name("widgets", records, project_name="alpha") == "widgets"


def test_allocate_project_name_rejects_invalid_base() -> None:
    with pytest.raises(ValueError, match="invalid project name"):
        allocate_project_name(".hidden", [])


def test_load_project_alias_map_ignores_spec_less_project_name_collision(
    projects_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bob_cli_file = _write_project(
        projects_root,
        "bob-cli",
        "PROJECT_ALIASES: bob\nWORKSPACE_DIR: /tmp/bob-cli\nNAME: b\n",
    )
    stray_project_file = projects_root / "bob" / "bob.sase"
    stray_project_file.parent.mkdir()

    monkeypatch.setattr(
        "sase.project_aliases.list_project_records",
        lambda *_args, **_kwargs: [
            _record(
                "bob",
                launchable=False,
                project_file=stray_project_file,
                aliases=[],
            ),
            _record("bob-cli", aliases=["bob"], project_file=bob_cli_file),
        ],
    )
    monkeypatch.setattr("sase.project_aliases._vcs_workflow_names", lambda: {"gh"})

    assert load_project_alias_map(projects_root) == {"bob": "bob-cli"}
    assert canonicalize_project_aliases_in_prompt("#gh:bob fix") == "#gh:bob-cli fix"


def test_load_project_alias_map_preserves_real_project_name_collision(
    projects_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bob_file = _write_project(
        projects_root,
        "bob",
        "WORKSPACE_DIR: /tmp/bob\nNAME: b\n",
    )
    bob_cli_file = _write_project(
        projects_root,
        "bob-cli",
        "PROJECT_ALIASES: bob\nWORKSPACE_DIR: /tmp/bob-cli\nNAME: c\n",
    )

    monkeypatch.setattr(
        "sase.project_aliases.list_project_records",
        lambda *_args, **_kwargs: [
            _record("bob", project_file=bob_file),
            _record("bob-cli", aliases=["bob"], project_file=bob_cli_file),
        ],
    )

    with pytest.raises(ValueError, match="real project name"):
        load_project_alias_map(projects_root)


def test_load_project_alias_map_rejects_duplicate_alias(
    projects_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bob_file = _write_project(
        projects_root,
        "bob-cli",
        "PROJECT_ALIASES: bob\nWORKSPACE_DIR: /tmp/bob-cli\nNAME: b\n",
    )
    docs_file = _write_project(
        projects_root,
        "docs-cli",
        "PROJECT_ALIASES: bob\nWORKSPACE_DIR: /tmp/docs-cli\nNAME: d\n",
    )

    monkeypatch.setattr(
        "sase.project_aliases.list_project_records",
        lambda *_args, **_kwargs: [
            _record("bob-cli", aliases=["bob"], project_file=bob_file),
            _record("docs-cli", aliases=["bob"], project_file=docs_file),
        ],
    )

    with pytest.raises(ValueError, match="assigned to both"):
        load_project_alias_map(projects_root)


def test_load_project_alias_map_includes_display_name(
    projects_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widgets_file = _write_project(
        projects_root,
        "gh_acme__widgets",
        "PROJECT_NAME: widgets\nWORKSPACE_DIR: /tmp/widgets\nNAME: c\n",
    )

    monkeypatch.setattr(
        "sase.project_aliases.list_project_records",
        lambda *_args, **_kwargs: [
            _record(
                "gh_acme__widgets",
                project_file=widgets_file,
                display_name="widgets",
            ),
        ],
    )
    monkeypatch.setattr("sase.project_aliases._vcs_workflow_names", lambda: {"gh"})

    assert (
        effective_project_name(_record("gh_acme__widgets", display_name="widgets"))
        == "widgets"
    )
    assert load_project_alias_map(projects_root) == {"widgets": "gh_acme__widgets"}
    assert canonicalize_project_aliases_in_prompt("#gh:widgets fix") == (
        "#gh:gh_acme__widgets fix"
    )


def test_humanize_project_refs_in_prompt_rewrites_only_vcs_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.project_aliases._vcs_workflow_names", lambda: {"gh"})

    prompt = (
        "#gh:gh_acme__widgets fix\n"
        "#gh(gh_acme__widgets) inspect\n"
        "path: /tmp/gh_acme__widgets/file\n"
        "```text\n#gh:gh_acme__widgets fenced\n```\n"
    )

    result = humanize_project_refs_in_prompt(
        prompt,
        {"gh_acme__widgets": "widgets"},
    )

    assert "#gh:widgets fix" in result
    assert "#gh(widgets) inspect" in result
    assert "path: /tmp/gh_acme__widgets/file" in result
    assert "#gh:gh_acme__widgets fenced" in result


def test_load_project_alias_map_rejects_display_name_collision(
    projects_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_file = _write_project(
        projects_root,
        "gh_acme__widgets",
        "PROJECT_NAME: widgets\nWORKSPACE_DIR: /tmp/a\nNAME: a\n",
    )
    second_file = _write_project(
        projects_root,
        "gh_globex__widgets",
        "PROJECT_NAME: widgets\nWORKSPACE_DIR: /tmp/b\nNAME: b\n",
    )

    monkeypatch.setattr(
        "sase.project_aliases.list_project_records",
        lambda *_args, **_kwargs: [
            _record(
                "gh_acme__widgets",
                project_file=first_file,
                display_name="widgets",
            ),
            _record(
                "gh_globex__widgets",
                project_file=second_file,
                display_name="widgets",
            ),
        ],
    )

    with pytest.raises(ValueError, match="assigned to both"):
        load_project_alias_map(projects_root)


def test_set_project_name_locked_writes_replaces_and_removes_name(
    projects_root: Path,
    lifecycle_stubs: Callable[[], None],
) -> None:
    lifecycle_stubs()
    project_file = _write_project(
        projects_root,
        "alpha",
        "WORKSPACE_DIR: /tmp/alpha\nNAME: a\n",
    )

    record = set_project_name_locked("alpha", "widgets", projects_root=projects_root)
    assert record.display_name == "widgets"
    assert "PROJECT_NAME: widgets\n" in project_file.read_text(encoding="utf-8")

    record = set_project_name_locked("alpha", "tools", projects_root=projects_root)
    content = project_file.read_text(encoding="utf-8")
    assert record.display_name == "tools"
    assert "PROJECT_NAME: tools\n" in content
    assert "widgets" not in content

    record = set_project_name_locked("alpha", None, projects_root=projects_root)
    assert record.display_name is None
    assert "PROJECT_NAME:" not in project_file.read_text(encoding="utf-8")


def test_ensure_project_name_locked_is_idempotent(
    projects_root: Path,
    lifecycle_stubs: Callable[[], None],
) -> None:
    lifecycle_stubs()
    project_file = _write_project(
        projects_root,
        "alpha",
        "PROJECT_NAME: widgets\nWORKSPACE_DIR: /tmp/alpha\nNAME: a\n",
    )

    record = ensure_project_name_locked("alpha", "widgets", projects_root=projects_root)

    assert record.display_name == "widgets"
    assert project_file.read_text(encoding="utf-8").count("PROJECT_NAME:") == 1


def test_set_project_name_locked_rejects_alias_collision(
    projects_root: Path,
    lifecycle_stubs: Callable[[], None],
) -> None:
    lifecycle_stubs()
    project_file = _write_project(
        projects_root,
        "alpha",
        "WORKSPACE_DIR: /tmp/alpha\nNAME: a\n",
    )
    _write_project(
        projects_root,
        "beta",
        "PROJECT_ALIASES: widgets\nWORKSPACE_DIR: /tmp/beta\nNAME: b\n",
    )

    with pytest.raises(ValueError, match="assigned to both"):
        set_project_name_locked("alpha", "widgets", projects_root=projects_root)

    assert "PROJECT_NAME:" not in project_file.read_text(encoding="utf-8")
