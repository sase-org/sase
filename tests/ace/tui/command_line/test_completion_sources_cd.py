"""``cd`` resolution and candidate tests for the ``:`` Command Line."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.command_line.builtins import resolve_cd
from sase.ace.tui.command_line.cd_completion import (
    cd_completion_context,
    complete_cd,
)
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)

from tests.ace.tui.command_line._completion_sources_shared import (
    await_provider_task,
    panel,
    pin_cwd,
    shown,
    stub_provider,
    type_line,
)

pytest_plugins = ["tests.ace.tui.command_line._completion_sources_shared"]

__all__ = [
    "test_cd_completes_directories_projects_and_unpin_on_the_screen",
    "test_cd_offers_unpin_in_the_empty_menu_after_the_directories",
    "test_cd_plus_prefers_the_canonical_key_over_an_equal_label",
    "test_cd_plus_resolves_the_labels_completion_offers_and_home",
]


def _record(
    name: str,
    *,
    display_name: str | None = None,
    state: str = "enabled",
    workspace_dir: str | None = None,
) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=name,
        project_dir=f"/projects/{name}",
        project_file=f"/projects/{name}/{name}.sase",
        archive_file=None,
        workspace_dir=workspace_dir,
        state=state,
        state_explicit=True,
        system_managed=name == "home",
        active_claim_count=0,
        launchable=True,
        display_name=display_name,
    )


def _stub_project_records(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, records: list[ProjectRecordWire]
) -> list[bool]:
    """Serve *records* as the project store; return each ``include_home`` seen."""
    import sase.core.paths as core_paths
    import sase.core.project_lifecycle_facade as facade

    include_home_seen: list[bool] = []

    def _list_records(
        root: object, states: object, *, include_home: bool = False, **kwargs: object
    ) -> list[ProjectRecordWire]:
        include_home_seen.append(include_home)
        return list(records)

    monkeypatch.setattr(core_paths, "sase_projects_dir", lambda: tmp_path)
    monkeypatch.setattr(facade, "list_project_records", _list_records)
    return include_home_seen


def test_cd_plus_resolves_the_labels_completion_offers_and_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``cd +sase`` and ``cd +home`` reach the checkouts completion promised."""
    include_home_seen = _stub_project_records(
        monkeypatch,
        tmp_path,
        [
            _record(
                "gh_sase-org__sase",
                display_name="sase",
                workspace_dir="/ws/github/sase",
            ),
            _record("home", workspace_dir="/ws/git/home"),
            _record("gh_org__old", display_name="old", state="disabled"),
        ],
    )

    by_label = resolve_cd("+sase", cwd="/")
    assert (by_label.pinned, by_label.outcome.exit_code) == ("/ws/github/sase", 0)
    assert by_label.changes_pin is True
    assert resolve_cd("+gh_sase-org__sase", cwd="/").pinned == "/ws/github/sase"
    assert resolve_cd("+home", cwd="/").pinned == "/ws/git/home"
    assert include_home_seen and all(include_home_seen)

    disabled = resolve_cd("+old", cwd="/")
    assert (disabled.pinned, disabled.outcome.exit_code) == (None, 2)
    missing = resolve_cd("+nope", cwd="/")
    assert missing.outcome.text == "error: no such project: nope"
    assert missing.changes_pin is False


def test_cd_plus_prefers_the_canonical_key_over_an_equal_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A label that collides with another project's key never steals the key."""
    _stub_project_records(
        monkeypatch,
        tmp_path,
        [
            _record("alias-holder", display_name="core", workspace_dir="/ws/holder"),
            _record("core", workspace_dir="/ws/core"),
        ],
    )

    assert resolve_cd("+core", cwd="/").pinned == "/ws/core"


def _dir_row(value: str) -> dict[str, Any]:
    return {"value": value, "badge": "dir", "source": "path"}


def test_cd_offers_unpin_in_the_empty_menu_after_the_directories() -> None:
    """``cd `` lists directories, then ``-``; ``-`` alone is only the unpin row."""
    context = cd_completion_context("cd ", len("cd "))
    assert context is not None
    empty = complete_cd(
        "cd ", len("cd "), context, [_dir_row("src/"), _dir_row("docs/")]
    )
    assert [item["insert_text"] for item in empty["items"]] == ["src/", "docs/", "-"]
    assert empty["kind"] == "dir"

    typed = complete_cd("cd s", len("cd s"), context, [_dir_row("src/")])
    assert [item["insert_text"] for item in typed["items"]] == ["src/"]

    dash_context = cd_completion_context("cd -", len("cd -"))
    assert dash_context is not None
    dash = complete_cd("cd -", len("cd -"), dash_context, [_dir_row("-notes/")])
    assert [item["insert_text"] for item in dash["items"]] == ["-notes/", "-"]

    project_context = cd_completion_context("cd +", len("cd +"))
    assert project_context is not None
    projects = complete_cd(
        "cd +",
        len("cd +"),
        project_context,
        [{"value": "home", "badge": "project", "source": "provider"}],
    )
    assert [item["insert_text"] for item in projects["items"]] == ["+home"]


async def test_cd_completes_directories_projects_and_unpin_on_the_screen(
    grammar_handle: Any,
    history_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``cd`` slots list pinned-cwd directories, ``+project`` rows and ``-``."""
    from sase.completion.candidates.protocol import Candidate

    (tmp_path / "alpha").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "notes.txt").write_text("not a directory")
    stub_provider(
        monkeypatch,
        lambda kind: [Candidate("zeta", "enabled"), Candidate("home", "enabled")],
    )
    async with panel(grammar_handle) as (page, screen):
        pin_cwd(page, screen, tmp_path)
        await type_line(page, screen, "cd ")
        await await_provider_task(screen)
        assert shown(screen) == ["alpha/", "-"]

        await type_line(page, screen, "cd .")
        await await_provider_task(screen)
        assert shown(screen) == [".hidden/"]

        await type_line(page, screen, "cd +")
        await await_provider_task(screen)
        assert {"+zeta", "+home"} <= set(shown(screen))
