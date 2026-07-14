"""Tests for ACE prompt catalog snapshot helpers."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui import prompt_catalog
from sase.ace.tui.actions._startup_prompt_catalog import StartupPromptCatalogMixin
from sase.ace.tui.widgets.xprompt_arg_assist import XPromptAssistEntry
from sase.xprompt.models import XPrompt


def _entry(name: str) -> XPromptAssistEntry:
    return XPromptAssistEntry(
        name=name,
        insertion=f"#{name}",
        reference_prefix="#",
        kind="xprompt",
        input_signature=None,
        inputs=(),
        content_preview=None,
    )


def test_prompt_source_token_changes_for_xprompt_file_create(
    tmp_path: Path,
    monkeypatch,
) -> None:
    xprompt_dir = tmp_path / ".xprompts"
    xprompt_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(prompt_catalog, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(
        prompt_catalog, "get_xprompt_search_paths", lambda: [xprompt_dir]
    )
    monkeypatch.setattr(prompt_catalog, "current_config_token", lambda: ("config",))

    before = prompt_catalog._prompt_source_token([None])
    (xprompt_dir / "new.md").write_text("hello", encoding="utf-8")
    after = prompt_catalog._prompt_source_token([None])

    assert before != after


def test_prompt_source_token_changes_for_project_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_dir = tmp_path / "config"
    project_dir = config_dir / "xprompts" / "sase"
    project_dir.mkdir(parents=True)
    monkeypatch.setattr(prompt_catalog, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(prompt_catalog, "get_xprompt_search_paths", lambda: [])
    monkeypatch.setattr(prompt_catalog, "current_config_token", lambda: ("config",))

    before = prompt_catalog._prompt_source_token(["sase"])
    (project_dir / "review.yml").write_text("steps: []", encoding="utf-8")
    after = prompt_catalog._prompt_source_token(["sase"])

    assert before != after


def test_prompt_source_change_filter_matches_only_catalog_sources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_dir = tmp_path / "config"
    xprompt_dir = tmp_path / ".xprompts"
    project_dir = config_dir / "xprompts" / "sase"
    config_dir.mkdir()
    xprompt_dir.mkdir()
    project_dir.mkdir(parents=True)
    monkeypatch.setattr(prompt_catalog, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(
        prompt_catalog, "get_xprompt_search_paths", lambda: [xprompt_dir]
    )

    assert prompt_catalog.prompt_source_change_is_relevant(
        [xprompt_dir / "review.md"],
        ["sase"],
    )
    assert prompt_catalog.prompt_source_change_is_relevant(
        [project_dir / "ship.yaml"],
        ["sase"],
    )
    assert prompt_catalog.prompt_source_change_is_relevant(
        [config_dir / "sase.yml"],
        ["sase"],
    )
    assert not prompt_catalog.prompt_source_change_is_relevant(
        [tmp_path / "README.md"],
        ["sase"],
    )
    assert not prompt_catalog.prompt_source_change_is_relevant(
        [config_dir / "notes.txt"],
        ["sase"],
    )


def test_build_prompt_catalog_snapshot_short_circuits_unchanged_token(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        prompt_catalog,
        "_prompt_source_token",
        lambda _projects: ("same",),
    )

    assert (
        prompt_catalog.build_prompt_catalog_snapshot(
            generation=1,
            projects=[None],
            previous_source_token=("same",),
        )
        is None
    )


def test_build_prompt_catalog_snapshot_merges_xprompt_and_user_snippets(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        prompt_catalog,
        "_prompt_source_token",
        lambda _projects: ("changed",),
    )
    monkeypatch.setattr(
        prompt_catalog,
        "get_all_xprompts",
        lambda project=None: {
            "review": XPrompt(
                name="review",
                content="Review this",
                snippet=True,
            )
        },
    )
    monkeypatch.setattr(
        prompt_catalog,
        "build_xprompt_assist_entries",
        lambda project=None: [_entry("review")],
    )

    import sase.config

    monkeypatch.setattr(
        sase.config,
        "load_merged_config",
        lambda: {"ace": {"snippets": {"user": "User body$0"}}},
    )

    snapshot = prompt_catalog.build_prompt_catalog_snapshot(
        generation=2,
        projects=[None],
        previous_source_token=None,
    )

    assert snapshot is not None
    assert snapshot.generation == 2
    assert snapshot.snippets == {
        "review": "Review this$0",
        "user": "User body$0",
    }
    assert snapshot.assist_entries_by_project[None][0].name == "review"


def test_app_prompt_catalog_returns_stable_assist_list_until_snapshot_changes() -> None:
    class CatalogApp(StartupPromptCatalogMixin):
        def _ensure_prompt_catalog_project(self, project: str | None) -> None:
            del project

        def _schedule_prompt_catalog_token_fallback_check(self) -> None:
            pass

    app = CatalogApp()
    app._prompt_catalog = prompt_catalog.PromptCatalogSnapshot(
        generation=1,
        source_token=("first",),
        snippets={},
        assist_entries_by_project={None: (_entry("review"),)},
    )
    app._prompt_catalog_assist_entries_cache = {}

    first = app.get_prompt_catalog_assist_entries(None)
    second = app.get_prompt_catalog_assist_entries(None)

    assert first is second

    app._prompt_catalog = prompt_catalog.PromptCatalogSnapshot(
        generation=2,
        source_token=("second",),
        snippets={},
        assist_entries_by_project={None: (_entry("ship"),)},
    )
    app._prompt_catalog_assist_entries_cache = {}
    refreshed = app.get_prompt_catalog_assist_entries(None)

    assert refreshed is not first
    assert refreshed is not None
    assert refreshed[0].name == "ship"
