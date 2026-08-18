"""Tests for prompt repo-mention preview and jump actions."""

from __future__ import annotations

import dataclasses
import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from rich.console import Console

from sase.ace.testing import PromptPage
from sase.ace.tui.modals.jump_action_modal import JumpActionModal
from sase.ace.tui.modals.repo_preview_modal import RepoPreviewModal
from sase.ace.tui.repo_mention_catalog import PromptRepoMentionContext
from sase.ace.tui.widgets._prompt_jump import _open_jump_target_in_tmux_pane
from sase.ace.tui.widgets._prompt_jump_target import JumpTarget
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._prompt_repo_mention_helpers import catalog_for_text, install_warm_repo_mentions


def _top_is_preview(page: PromptPage) -> bool:
    return isinstance(page.ta.app.screen_stack[-1], RepoPreviewModal)


def _top_is_jump_modal(page: PromptPage) -> bool:
    return isinstance(page.ta.app.screen_stack[-1], JumpActionModal)


def _render_text(renderable: object) -> str:
    console = Console(file=io.StringIO(), width=100, record=True)
    console.print(renderable)
    return console.export_text()


async def test_k_on_repo_mention_pushes_repo_preview_card(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    text = "Ask sase-core to inspect the workspace"
    catalog = catalog_for_text(text, tmp_path, "sase-core")

    async with PromptPage(text, cursor=(0, 6), size=(80, 24)) as page:
        install_warm_repo_mentions(monkeypatch, page.ta.app, catalog)
        monkeypatch.setattr(
            page.ta,
            "_lookup_word_under_cursor",
            lambda: (_ for _ in ()).throw(
                AssertionError("word lookup must not run for repo mentions")
            ),
        )

        await page.press("K")
        await page.wait_for(lambda: _top_is_preview(page))

        modal = page.ta.app.screen_stack[-1]
        assert isinstance(modal, RepoPreviewModal)
        assert modal._mention.identifier == "sase-core"
        assert modal._matched_text == "sase-core"
        title_text = _render_text(modal._build_title())
        assert "REPO" in title_text
        assert "sase-core" in title_text
        assert "matched" not in title_text
        assert page.ta._prompt_preview_request_id == 0


async def test_k_on_cold_repo_catalog_defers_without_word_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warmed: list[PromptRepoMentionContext] = []
    notifications: list[tuple[str, str | None]] = []

    async with PromptPage("sase-core", cursor=(0, 2), size=(80, 24)) as page:
        monkeypatch.setattr(
            page.ta.app,
            "get_prompt_repo_mention_catalog",
            lambda _context, *, schedule=True: None,
            raising=False,
        )
        monkeypatch.setattr(
            page.ta.app,
            "is_prompt_repo_mention_catalog_warm",
            lambda _context: False,
            raising=False,
        )
        monkeypatch.setattr(
            page.ta.app,
            "warm_prompt_repo_mention_catalog",
            warmed.append,
            raising=False,
        )
        monkeypatch.setattr(
            page.ta,
            "_lookup_word_under_cursor",
            lambda: (_ for _ in ()).throw(
                AssertionError("cold repo lookup must not fall through")
            ),
        )
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append((message, severity)),
        )

        await page.press("K")
        await page.pause()

        assert len(warmed) == 1
        assert notifications == [
            ("Repo catalog is still loading; try again", "warning")
        ]
        assert page.ta._prompt_preview_request_id == 0
        assert not _top_is_preview(page)


async def test_k_miss_on_repo_mention_falls_through_to_word_lookup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    text = "Ask sase-core to inspect the workspace"
    catalog = catalog_for_text(text, tmp_path, "sase-core")
    calls: list[bool] = []

    async with PromptPage(
        text,
        cursor=(0, text.index("inspect")),
        size=(80, 24),
    ) as page:
        install_warm_repo_mentions(monkeypatch, page.ta.app, catalog)
        monkeypatch.setattr(
            page.ta,
            "_lookup_word_under_cursor",
            lambda: calls.append(True) or False,
        )

        await page.press("K")
        await page.pause()

        assert calls == [True]
        assert not _top_is_preview(page)


async def test_ctrl_bracket_on_cloned_repo_mention_builds_checkout_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    text = "Ask sase-core to inspect the workspace"
    catalog = catalog_for_text(text, tmp_path, "sase-core")
    payloads: list[JumpTarget] = []

    monkeypatch.setattr(
        PromptTextArea,
        "_present_jump_actions",
        lambda self, payload: payloads.append(payload),
    )

    async with PromptPage(text, cursor=(0, 6), size=(80, 24)) as page:
        install_warm_repo_mentions(monkeypatch, page.ta.app, catalog)

        await page.press("ctrl+right_square_bracket")
        await page.wait_for(lambda: bool(payloads))

        payload = payloads[0]
        assert payload.kind_label == "repo"
        assert payload.icon == "R"
        assert payload.title == "sase-core"
        assert payload.source_path == str(tmp_path / "sase-core")
        assert payload.is_editable is False
        assert payload.config_path == str(tmp_path / "sase.yml")
        assert payload.config_line == 16
        assert payload.config_col == 7


async def test_ctrl_bracket_on_not_cloned_repo_mention_opens_declaration_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    text = "Ask sase-core to inspect the workspace"
    catalog = catalog_for_text(text, tmp_path, "sase-core", exists=False)
    notifications: list[tuple[str, str | None]] = []
    opened: list[JumpTarget] = []

    monkeypatch.setattr(
        PromptTextArea,
        "_open_jump_target_in_this_pane",
        lambda self, payload: opened.append(payload),
    )

    async with PromptPage(text, cursor=(0, 6), size=(80, 24)) as page:
        install_warm_repo_mentions(monkeypatch, page.ta.app, catalog)
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append((message, severity)),
        )

        await page.press("ctrl+right_square_bracket")
        await page.wait_for(lambda: bool(opened))

        assert notifications == [
            (
                "sase-core is not cloned in this workspace; "
                "run `sase repo open sase-core`",
                "warning",
            )
        ]
        assert not _top_is_jump_modal(page)
        declaration = opened[0]
        assert declaration.source_path == str(tmp_path / "sase.yml")
        assert declaration.line == 16
        assert declaration.col == 7


async def test_ctrl_bracket_on_not_cloned_external_repo_notifies_with_no_chooser(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    identifier = "gh:owner/repo"
    text = f"Ask {identifier} to inspect the workspace"
    catalog = catalog_for_text(
        text, tmp_path, identifier, kind="external", exists=False
    )
    notifications: list[tuple[str, str | None]] = []

    monkeypatch.setattr(
        PromptTextArea,
        "_open_jump_target_in_this_pane",
        lambda self, payload: (_ for _ in ()).throw(
            AssertionError("a declaration-less external repo must not open anything")
        ),
    )
    monkeypatch.setattr(
        PromptTextArea,
        "_present_jump_actions",
        lambda self, payload: (_ for _ in ()).throw(
            AssertionError("a not-cloned external repo must not open a chooser")
        ),
    )

    async with PromptPage(
        text,
        cursor=(0, text.index(identifier) + 2),
        size=(80, 24),
    ) as page:
        install_warm_repo_mentions(monkeypatch, page.ta.app, catalog)
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append((message, severity)),
        )

        await page.press("ctrl+right_square_bracket")
        await page.pause()

        assert notifications == [
            (
                f"{identifier} is not cloned in this workspace; "
                f"run `sase repo open {identifier}`",
                "warning",
            )
        ]
        assert not _top_is_jump_modal(page)


async def test_jump_action_choices_include_config_only_with_declaration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump.is_tmux_session", lambda: False
    )
    with_declaration = JumpTarget(
        kind_label="repo",
        icon="R",
        title="sase-core",
        source_path="/workspace/repos/sase-core",
        line=None,
        col=None,
        loadable_markdown=None,
        config_path="/workspace/sase/sase.yml",
        config_line=16,
        config_col=7,
    )
    without_declaration = dataclasses.replace(with_declaration, config_path=None)

    async with PromptPage("sase-core", cursor=(0, 0), size=(80, 24)) as page:
        assert page.ta._jump_action_choices(with_declaration) == ["editor", "config"]
        assert page.ta._jump_action_choices(without_declaration) == ["editor"]


async def test_perform_jump_action_config_opens_declaration_path_and_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[JumpTarget] = []
    monkeypatch.setattr(
        PromptTextArea,
        "_open_jump_target_in_this_pane",
        lambda self, payload: opened.append(payload),
    )
    payload = JumpTarget(
        kind_label="repo",
        icon="R",
        title="sase-core",
        source_path="/workspace/repos/sase-core",
        line=None,
        col=None,
        loadable_markdown=None,
        config_path="/workspace/sase/sase.yml",
        config_line=16,
        config_col=7,
    )

    async with PromptPage("sase-core", cursor=(0, 0), size=(80, 24)) as page:
        page.ta._perform_jump_action("config", payload)

        assert len(opened) == 1
        derived = opened[0]
        assert derived.source_path == "/workspace/sase/sase.yml"
        assert derived.line == 16
        assert derived.col == 7
        assert derived.title == "sase-core"


def test_open_jump_target_in_tmux_pane_uses_directory_itself_for_dir_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "sase-core"
    directory.mkdir()
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        commands.append(command)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("sase.ace.tui.widgets._prompt_jump.subprocess.run", fake_run)
    monkeypatch.setattr("sase.ace.tui.widgets._prompt_jump.get_editor", lambda: "vim")

    payload = JumpTarget(
        kind_label="repo",
        icon="R",
        title="sase-core",
        source_path=str(directory),
        line=None,
        col=None,
        loadable_markdown=None,
    )

    error = _open_jump_target_in_tmux_pane(payload)

    assert error is None
    command = commands[0]
    assert command[command.index("-c") + 1] == str(directory)


def test_open_jump_target_in_tmux_pane_uses_parent_for_file_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "foo.md"
    file_path.write_text("hi", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        commands.append(command)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("sase.ace.tui.widgets._prompt_jump.subprocess.run", fake_run)
    monkeypatch.setattr("sase.ace.tui.widgets._prompt_jump.get_editor", lambda: "vim")

    payload = JumpTarget(
        kind_label="file",
        icon="@",
        title="foo.md",
        source_path=str(file_path),
        line=None,
        col=None,
        loadable_markdown=None,
    )

    error = _open_jump_target_in_tmux_pane(payload)

    assert error is None
    command = commands[0]
    assert command[command.index("-c") + 1] == str(tmp_path)
