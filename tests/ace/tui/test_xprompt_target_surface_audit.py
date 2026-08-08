"""Audit tests for xprompt target behavior across prompt-stack load surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.ace.tui.modals.xprompt_definition_loader import (
    load_xprompt_definition_for_prompt_bar,
)
from sase.ace.tui.widgets._prompt_jump import PromptJumpMixin
from sase.ace.tui.widgets._prompt_jump_target import JumpTarget
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_stack import XPromptBinding

from tests.ace.tui.widgets._prompt_input_bar_stack_helpers import _PromptBarApp


class _JumpHarness(PromptJumpMixin):
    def __init__(self, bar: PromptInputBar) -> None:
        self._bar = bar
        self.app = bar.app
        self.notifications: list[tuple[str, str]] = []
        self.refocus_count = 0

    def _find_prompt_bar(self) -> PromptInputBar:
        return self._bar

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _refocus_if_needed(self) -> None:
        self.refocus_count += 1


def test_tui_surfaces_do_not_bind_prompt_stack_directly() -> None:
    """Only the bar target API and stack model may call ``_stack.bind``."""
    repo_root = Path(__file__).parents[3]
    allowed = {
        repo_root / "src/sase/ace/tui/widgets/prompt_stack.py",
        repo_root / "src/sase/ace/tui/widgets/_prompt_input_bar_stack_rendering.py",
    }
    offenders: list[str] = []

    for path in (repo_root / "src/sase/ace/tui").rglob("*.py"):
        if path in allowed:
            continue
        if "_stack.bind(" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(repo_root)))

    assert offenders == []


async def test_jump_load_targets_editable_definition(tmp_path: Path) -> None:
    source = tmp_path / "review.md"
    source.write_text("jump body", encoding="utf-8")
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        payload = JumpTarget(
            kind_label="xprompt",
            icon="#",
            title="#review",
            source_path=str(source),
            line=None,
            col=None,
            loadable_markdown="jump body",
            definition_name="review",
            is_editable=True,
        )

        _JumpHarness(bar)._load_jump_target_into_prompt(payload)
        await pilot.pause()

        target = bar.xprompt_target()
        assert target is not None
        assert target.reference == "#review"
        assert target.path == str(source)
        assert bar.active_text() == "jump body"


async def test_stash_restore_replacement_clears_existing_target(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets.frontmatter_panel.frontmatter_field_schema",
        lambda: [],
    )
    source = tmp_path / "review.md"
    source.write_text("draft", encoding="utf-8")
    app = _PromptBarApp("draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar.target_xprompt(
            XPromptBinding.for_file(source, reference="#review"),
            source_markdown="draft",
        )

        bar.stash_all_and_load_xprompt_markdown("restored")
        await pilot.pause()
        await pilot.pause()

        assert bar.xprompt_target() is None
        assert bar.active_text() == "restored"


async def test_history_pane_load_leaves_existing_target(tmp_path: Path) -> None:
    source = tmp_path / "review.md"
    source.write_text("first\n---\nsecond", encoding="utf-8")
    app = _PromptBarApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        binding = XPromptBinding.for_file(source, reference="#review")
        bar.load_stack_from_xprompt_markdown("first\n---\nsecond", binding=binding)
        await pilot.pause()
        target = bar.xprompt_target()
        text_area = bar.active_text_area()

        assert bar.load_prompt_into_pane(text_area, text_area.id or "", "history")
        await pilot.pause()

        assert bar.xprompt_target() == target
        assert bar.all_prompt_texts() == ["first", "history"]


async def test_read_only_definition_payload_has_no_target(tmp_path: Path) -> None:
    source = tmp_path / "builtin.md"
    source.write_text("read only", encoding="utf-8")

    loaded = await load_xprompt_definition_for_prompt_bar(
        name="builtin",
        source_path=str(source),
        editable=False,
        reference="#builtin",
    )

    assert loaded.binding is None
    assert loaded.read_only is True
    assert loaded.read_only_path == str(source)
    assert loaded.markdown == "read only"
