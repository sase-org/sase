"""Tests for ACE prompt catalog snapshot helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sase.ace.tui import prompt_catalog
from sase.macro.models import Macro
from sase.snippet.models import SnippetSourceContribution
from tests.ace.tui._prompt_catalog_test_helpers import entry


def _config_contributions(
    snippets: dict[str, str],
) -> tuple[tuple[SnippetSourceContribution, ...], tuple[object, ...]]:
    return (
        tuple(
            SnippetSourceContribution(
                trigger=trigger,
                template=template,
                kind="user",
                path="ace.snippets",
                display_path="ace.snippets",
                writable=True,
            )
            for trigger, template in snippets.items()
        ),
        (),
    )


def test_prompt_source_token_changes_for_xprompt_file_create(
    tmp_path: Path,
    monkeypatch,
) -> None:
    macro_dir = tmp_path / ".xprompts"
    macro_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(prompt_catalog, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(prompt_catalog, "get_macro_search_paths", lambda: [macro_dir])
    monkeypatch.setattr(prompt_catalog, "current_config_token", lambda: ("config",))

    before = prompt_catalog._prompt_source_token([None])
    (macro_dir / "new.md").write_text("hello", encoding="utf-8")
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
    monkeypatch.setattr(prompt_catalog, "get_macro_search_paths", lambda: [])
    monkeypatch.setattr(prompt_catalog, "current_config_token", lambda: ("config",))

    before = prompt_catalog._prompt_source_token(["sase"])
    (project_dir / "review.yml").write_text("steps: []", encoding="utf-8")
    after = prompt_catalog._prompt_source_token(["sase"])

    assert before != after


def test_prompt_source_token_changes_for_memory_file_create(
    tmp_path: Path,
    monkeypatch,
) -> None:
    memory_dir = tmp_path / "sase" / "memory"
    memory_dir.mkdir(parents=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(prompt_catalog, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(prompt_catalog, "get_macro_search_paths", lambda: [])
    monkeypatch.setattr(prompt_catalog, "current_config_token", lambda: ("config",))
    monkeypatch.setattr(
        prompt_catalog,
        "resolve_memory_file_sources",
        lambda **_kwargs: (
            SimpleNamespace(
                paths=SimpleNamespace(candidates=(memory_dir,)),
            ),
        ),
    )

    before = prompt_catalog._prompt_source_token([None])
    (memory_dir / "glossary.md").write_text("---\ntype: core\n---\nbody\n")
    after = prompt_catalog._prompt_source_token([None])

    assert before != after


def test_prompt_source_watch_paths_include_memory_roots(
    tmp_path: Path,
    monkeypatch,
) -> None:
    memory_dir = tmp_path / "sase" / "memory"
    memory_dir.mkdir(parents=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(prompt_catalog, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(prompt_catalog, "get_macro_search_paths", lambda: [])
    monkeypatch.setattr(
        prompt_catalog,
        "resolve_memory_file_sources",
        lambda **_kwargs: (
            SimpleNamespace(
                paths=SimpleNamespace(candidates=(memory_dir,)),
            ),
        ),
    )

    paths = prompt_catalog.prompt_source_watch_paths([None])

    assert memory_dir in paths


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
        "sase.macro.loader.get_all_macros",
        lambda project=None: {
            "review": Macro(
                name="review",
                content="Review this",
                snippet=True,
            )
        },
    )
    monkeypatch.setattr(
        prompt_catalog,
        "build_macro_assist_entries",
        lambda project=None: [entry("review")],
    )
    monkeypatch.setattr(
        "sase.snippet.catalog._config_layer_contributions",
        lambda *_a, **_k: _config_contributions({"user": "User body$0"}),
    )

    snapshot = prompt_catalog.build_prompt_catalog_snapshot(
        generation=2,
        projects=[None],
        previous_source_token=None,
        pending_snippet_saves={
            "combo": "#[review] + #[user]",
            "capital_ref": "#[Review]!",
        },
    )

    assert snapshot is not None
    assert snapshot.generation == 2
    assert snapshot.snippets == {
        "Combo": "Review this + User body$0",
        "Capital_ref": "Review this!$0",
        "Review": "Review this$0",
        "User": "User body$0",
        "capital_ref": "Review this!$0",
        "review": "Review this$0",
        "user": "User body$0",
        "combo": "Review this + User body$0",
    }
    assert snapshot.explicit_snippets == {
        "review": "Review this$0",
        "user": "User body$0",
        "combo": "#[review] + #[user]",
        "capital_ref": "#[Review]!",
    }
    assert snapshot.user_snippets == {"user": "User body$0"}
    assert snapshot.assist_entries_by_project[None][0].name == "review"


def test_prompt_catalog_preserves_explicit_capitalized_collisions(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        prompt_catalog,
        "_prompt_source_token",
        lambda _projects: ("changed",),
    )
    monkeypatch.setattr(
        "sase.macro.loader.get_all_macros",
        lambda project=None: {
            "foo": Macro(name="foo", content="xprompt lower", snippet=True),
            "Foo": Macro(name="Foo", content="xprompt capital", snippet=True),
            "bar": Macro(name="bar", content="xprompt bar", snippet=True),
        },
    )
    monkeypatch.setattr(
        prompt_catalog,
        "build_macro_assist_entries",
        lambda project=None: [],
    )
    monkeypatch.setattr(
        "sase.snippet.catalog._config_layer_contributions",
        lambda *_a, **_k: _config_contributions(
            {
                "foo": "user lower",
                "Bar": "user capital",
                "User_only": "authored capital",
                "user_only": "user lowercase",
            }
        ),
    )

    snapshot = prompt_catalog.build_prompt_catalog_snapshot(
        generation=1,
        projects=[None],
    )

    assert snapshot is not None
    assert snapshot.explicit_snippets == {
        "foo": "user lower",
        "Foo": "xprompt capital$0",
        "bar": "xprompt bar$0",
        "Bar": "user capital",
        "User_only": "authored capital",
        "user_only": "user lowercase",
    }
    assert snapshot.snippets["foo"] == "user lower"
    assert snapshot.snippets["Foo"] == "xprompt capital$0"
    assert snapshot.snippets["bar"] == "xprompt bar$0"
    assert snapshot.snippets["Bar"] == "user capital"
    assert snapshot.snippets["user_only"] == "user lowercase"
    assert snapshot.snippets["User_only"] == "authored capital"
    assert snapshot.user_snippets == {
        "foo": "user lower",
        "Bar": "user capital",
        "User_only": "authored capital",
        "user_only": "user lowercase",
    }


def test_config_dirty_build_invalidates_warm_merged_config(monkeypatch) -> None:
    state = {"fresh": False}
    monkeypatch.setattr(
        prompt_catalog,
        "_prompt_source_token",
        lambda _projects: ("fresh",) if state["fresh"] else ("stale",),
    )
    monkeypatch.setattr("sase.macro.loader.get_all_macros", lambda project=None: {})
    monkeypatch.setattr(
        prompt_catalog,
        "build_macro_assist_entries",
        lambda project=None: [],
    )

    from sase.config import core as config_core

    monkeypatch.setattr(
        config_core,
        "clear_config_cache",
        lambda: state.__setitem__("fresh", True),
    )
    monkeypatch.setattr(
        "sase.snippet.catalog._config_layer_contributions",
        lambda *_a, **_k: _config_contributions(
            {"saved": "new" if state["fresh"] else "old"}
        ),
    )

    snapshot = prompt_catalog.build_prompt_catalog_snapshot(
        generation=3,
        projects=[None],
        previous_source_token=("stale",),
        config_dirty=True,
    )

    assert snapshot is not None
    assert snapshot.user_snippets == {"saved": "new"}
    assert snapshot.explicit_snippets == {"saved": "new"}
    assert snapshot.snippets == {"Saved": "New", "saved": "new"}


def test_compose_pending_snippet_saves_preserves_existing_and_resolves_refs() -> None:
    composed = prompt_catalog.compose_pending_snippet_saves(
        {"xprompt": "Existing $1$0", "user": "User"},
        {"saved": "#[xprompt] then $1"},
    )

    assert composed["xprompt"] == "Existing $1$0"
    assert composed["Xprompt"] == "Existing $1$0"
    assert composed["user"] == "User"
    assert composed["User"] == "User"
    assert composed["saved"] == "Existing $1 then $2$0"
    assert composed["Saved"] == "Existing $1 then $2$0"
