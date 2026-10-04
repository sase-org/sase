"""Target writes selected by the unified macro/snippet save panel."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml  # type: ignore[import-untyped]

from sase.ace.tui.actions.agent_workflow._prompt_bar_save_macro_targets import (
    write_binding_sync,
)
from sase.ace.tui.modals import UnifiedMacroSaveResult
from sase.ace.tui.widgets.prompt_stack import MacroBinding as MacroBinding
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.macro.prompt_frontmatter import PromptFrontmatter
from sase.macro.save import SaveTargetFormat

from ._prompt_save_macro_helpers import _SaveFlowApp, _SaveHarness


async def test_unified_markdown_result_writes_typed_name_authoritatively(
    tmp_path: Path,
) -> None:
    harness = _SaveHarness()
    target = UnifiedMacroSaveResult(
        mode="macro",
        name="ns/foo",
        path=str(tmp_path / "ns_foo.md"),
        location_path=str(tmp_path),
        target_format=SaveTargetFormat.MARKDOWN,
        entry_name=None,
        display_path="./ns_foo.md",
        exists=False,
        frontmatter=PromptFrontmatter(name="ns/foo", description="Saved"),
    )
    with patch("sase.macro.save_state.save_last_used_location", return_value=True):
        await harness._write_macro_target(target, "new body")

    written = Path(target.path).read_text(encoding="utf-8")
    assert "name: ns/foo" in written
    assert "description: Saved" in written
    assert written.endswith("new body\n")
    assert harness.notifications == [("Created macro 'ns/foo'", None)]
    assert harness.git_offers == [(target.path, True, "ns/foo", "macro")]


async def test_unified_config_result_inserts_macro(tmp_path: Path) -> None:
    config = tmp_path / "sase" / "sase.yml"
    config.parent.mkdir()
    config.write_text("theme: dark\n", encoding="utf-8")
    harness = _SaveHarness()
    target = UnifiedMacroSaveResult(
        mode="macro",
        name="review",
        path=str(config),
        location_path=str(config),
        target_format=SaveTargetFormat.CONFIG,
        entry_name="review",
        display_path="./sase/sase.yml",
        exists=False,
        frontmatter=PromptFrontmatter(description="Review code"),
    )
    with patch("sase.macro.save_state.save_last_used_location", return_value=True):
        await harness._write_macro_target(target, "check this")

    payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert payload["macros"]["review"] == {
        "description": "Review code",
        "content": "check this",
    }


def test_bound_markdown_write_uses_resolved_write_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    source_root = home / ".local" / "share" / "chezmoi" / "home"
    read_path = home / "sase" / "macros" / "review.md"
    write_path = source_root / "sase" / "macros" / "review.md"
    read_path.parent.mkdir(parents=True)
    write_path.parent.mkdir(parents=True)
    read_path.write_text("applied\n", encoding="utf-8")
    write_path.write_text("old source\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr("sase.macro.write_targets.CHEZMOI_HOME", source_root)
    monkeypatch.setattr("sase.macro.write_targets.get_use_chezmoi", lambda: True)
    binding = MacroBinding.for_file(read_path, reference="#review")

    write_binding_sync(binding, PromptFrontmatter(description="Saved"), "new body")

    assert read_path.read_text(encoding="utf-8") == "applied\n"
    written = write_path.read_text(encoding="utf-8")
    assert "description: Saved" in written
    assert written.endswith("new body\n")


async def test_unified_snippet_result_writes_only_active_pane_and_refreshes(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sase" / "sase.yml"
    config.parent.mkdir()
    config.write_text("ace:\n  snippets: {}\n", encoding="utf-8")
    harness = _SaveHarness()
    target = UnifiedMacroSaveResult(
        mode="snippet",
        name="review",
        path=str(config),
        location_path=str(config),
        target_format=None,
        entry_name="review",
        display_path="./sase/sase.yml",
        exists=False,
        frontmatter=PromptFrontmatter(),
    )

    with patch("sase.macro.save_state.save_last_used_location", return_value=True):
        await harness._write_snippet_target(target, "beta")

    payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert payload["ace"]["snippets"] == {"review": "beta"}
    assert harness._user_snippets == {}
    assert harness._pending_snippet_saves == {"review": "beta"}
    assert harness._snippets_cache == {"Review": "Beta", "review": "beta"}
    assert harness.git_offers == [(str(config), True, "review", "snippet")]


async def test_chezmoi_source_save_expands_in_same_mounted_prompt_before_apply(
    tmp_path: Path,
) -> None:
    source_config = tmp_path / "chezmoi" / "dot_config" / "sase" / "sase.yml"
    source_config.parent.mkdir(parents=True)
    source_config.write_text("ace:\n  snippets: {}\n", encoding="utf-8")
    target = UnifiedMacroSaveResult(
        mode="snippet",
        name="welcome",
        path=str(source_config),
        location_path=str(source_config),
        target_format=None,
        entry_name="welcome",
        display_path="chezmoi source",
        exists=False,
        frontmatter=PromptFrontmatter(),
    )
    app = _SaveFlowApp("draft")
    app._user_snippets = {"applied": "Applied"}
    app._snippets_cache = {
        "applied": "Applied",
        "macro": "Hello $1$0",
    }
    app._prompt_catalog = SimpleNamespace(
        explicit_snippets={
            "applied": "Applied",
            "macro": "Hello $1$0",
        }
    )

    with patch("sase.macro.save_state.save_last_used_location", return_value=True):
        async with app.run_test() as pilot:
            text_area = app.query_one(PromptTextArea)
            assert text_area.is_mounted

            await app._write_snippet_target(target, "#[macro] from $1")

            assert app._pending_snippet_saves == {"welcome": "#[macro] from $1"}
            assert app._snippets_cache["applied"] == "Applied"
            assert app._snippets_cache["macro"] == "Hello $1$0"
            assert app._snippets_cache["welcome"] == "Hello $1 from $2$0"
            assert app._snippets_cache["Welcome"] == "Hello $1 from $2$0"

            text_area.load_text("Welcome")
            text_area.cursor_location = (0, len("Welcome"))
            with patch.object(
                type(text_area),
                "_ace_app",
                new_callable=lambda: property(lambda _self: app),
            ):
                assert text_area._try_expand_snippet() is True
            assert app.query_one(PromptTextArea) is text_area
            assert text_area.text == "Hello  from "
            await pilot.pause()


async def test_second_save_replaces_pending_trigger_deterministically(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sase.yml"
    config.write_text("ace:\n  snippets: {}\n", encoding="utf-8")
    target = UnifiedMacroSaveResult(
        mode="snippet",
        name="review",
        path=str(config),
        location_path=str(config),
        target_format=None,
        entry_name="review",
        display_path=str(config),
        exists=False,
        frontmatter=PromptFrontmatter(),
    )
    harness = _SaveHarness()

    with patch("sase.macro.save_state.save_last_used_location", return_value=True):
        await harness._write_snippet_target(target, "first")
        await harness._write_snippet_target(target, "second")

    assert harness._pending_snippet_saves == {"review": "second"}
    assert harness._snippets_cache == {"Review": "Second", "review": "second"}


async def test_live_save_preserves_authored_capital_collision_off_event_loop() -> None:
    from sase.ace.tui import prompt_catalog

    harness = _SaveHarness()
    harness._user_snippets = {"Foo": "authored capital"}
    event_loop_thread = threading.get_ident()
    composition_threads: list[int] = []
    real_compose = prompt_catalog.compose_pending_snippet_saves

    def record_compose(
        explicit_snippets: dict[str, str],
        pending_snippet_saves: dict[str, str],
    ) -> dict[str, str]:
        composition_threads.append(threading.get_ident())
        return real_compose(explicit_snippets, pending_snippet_saves)

    with patch.object(
        prompt_catalog,
        "compose_pending_snippet_saves",
        side_effect=record_compose,
    ):
        await harness._publish_saved_snippet("foo", "lower save")

    assert composition_threads
    assert all(thread_id != event_loop_thread for thread_id in composition_threads)
    assert harness._pending_snippet_saves == {"foo": "lower save"}
    assert harness._snippets_cache == {
        "Foo": "authored capital",
        "foo": "lower save",
    }


async def test_save_snippet_uses_resolved_chezmoi_target_for_post_write(
    tmp_path: Path,
) -> None:
    source = tmp_path / "chezmoi" / "dot_config" / "sase" / "sase.yml"
    home_target = tmp_path / "home" / ".config" / "sase" / "sase.yml"
    source.parent.mkdir(parents=True)
    source.write_text(yaml.safe_dump({"ace": {"snippets": {}}}), encoding="utf-8")
    harness = _SaveHarness()

    with patch("sase.macro.save_state.save_last_used_location", return_value=True):
        ok = await harness.save_snippet(
            write_path=str(source),
            read_path=str(home_target),
            location_path=str(source),
            display_path="~/.config/sase/sase.yml",
            trigger="todo",
            body="body",
            exists=False,
            apply_target=str(home_target),
            via_chezmoi=True,
        )

    assert ok is True
    assert harness.post_write_targets
    target = harness.post_write_targets[-1]
    assert target.write_path == source
    assert target.read_path == home_target
    assert target.apply_target == home_target
    assert target.via_chezmoi is True
