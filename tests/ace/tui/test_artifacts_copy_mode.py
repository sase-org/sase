"""Copy-mode coverage for every non-PR Artifacts sub-tab."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.clipboard import ClipboardMixin
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.widgets.keybinding_footer import KeybindingFooter


class _CopyHarness(ClipboardMixin):
    """Small synchronous harness around the copy dispatch mixins."""

    def __init__(self) -> None:
        self.current_tab = "changespecs"
        self.current_artifacts_subtab = "commits"
        self.changespecs: list[Any] = []
        self._keymap_registry = load_keymap_registry({})
        self._copy_mode_active = False
        self.copies: list[tuple[str, str]] = []
        self.notifications: list[tuple[str, str]] = []
        self.copy_footer_updates = 0
        self.artifacts_footer_restores = 0
        self.tab_footer_restores = 0
        self.snapshot_copies = 0
        self.commits_pane: Any = None
        self.plans_pane: Any = None
        self.chats_pane: Any = None
        self.bugs_pane: Any = None

    def notify(
        self,
        message: str,
        *,
        severity: str = "information",
        **_kwargs: Any,
    ) -> None:
        self.notifications.append((message, severity))

    def _update_copy_footer(self) -> None:
        self.copy_footer_updates += 1

    def _sync_active_artifacts_entry_state(self) -> None:
        self.artifacts_footer_restores += 1

    def _refresh_current_tab(self) -> None:
        self.tab_footer_restores += 1

    def _copy_snapshot(self) -> None:
        self.snapshot_copies += 1

    def _schedule_artifacts_copy(
        self,
        content: str | Any,
        *,
        copied_message: str,
        task_name: str = "sase-artifacts-copy",
    ) -> None:
        del task_name
        value = content() if callable(content) else content
        self.copies.append((value, copied_message))

    def _commits_pane(self) -> Any:
        return self.commits_pane

    def action_commits_copy_sha(self) -> None:
        entry = self.commits_pane._selected_entry()
        self.copies.append((entry.commit.full_id, "Copied commit SHA"))

    def _plans_pane(self) -> Any:
        return self.plans_pane

    def _chats_pane(self) -> Any:
        return self.chats_pane

    def action_chats_copy_path(self) -> None:
        self.copies.append(
            (self.chats_pane.selected_entry.absolute_path, "Copied chat path")
        )

    def _bugs_pane(self) -> Any:
        return self.bugs_pane

    def _selected_bug_copy_context(self) -> Any:
        pane = self.bugs_pane
        if pane is None or pane.selected_issue is None or pane.project_scope is None:
            return None
        return pane, pane.selected_issue, pane.project_scope


def test_copy_mode_opens_without_a_hidden_pr_selection_and_restores_subtab() -> None:
    app = _CopyHarness()
    assert app.changespecs == []

    app.action_start_copy_mode()

    assert app._copy_mode_active is True
    assert app.copy_footer_updates == 1

    assert app._handle_copy_key("escape") is True
    assert app.artifacts_footer_restores == 1
    assert app.tab_footer_restores == 0


async def test_percent_opens_and_escape_restores_copy_footer_on_real_artifacts_app() -> (
    None
):
    async with AcePage() as page:
        page.app.current_artifacts_subtab = "chats"
        await page.expect_state("artifacts_subtab", "chats")
        footer = page.query_one_widget("#keybinding-footer", KeybindingFooter)

        await page.press("%")

        assert page.app._copy_mode_active is True
        assert footer._last_layout_inputs is not None
        assert footer._last_layout_inputs[1] == "COPY"

        await page.press("escape")

        assert page.app._copy_mode_active is False
        assert footer._last_layout_inputs is not None
        assert footer._last_layout_inputs[1] is None


@pytest.mark.parametrize("subtab", ["commits", "plans", "chats", "bugs"])
def test_each_artifacts_copy_menu_supports_snapshot_and_names_unknown_keys(
    subtab: str,
) -> None:
    app = _CopyHarness()
    app.current_artifacts_subtab = subtab

    assert app._handle_copy_key("s") is True
    assert app.snapshot_copies == 1
    assert app.artifacts_footer_restores == 1

    assert app._handle_copy_key("n") is False
    assert app.notifications[-1][0].startswith(f"Unknown copy key ({subtab.title()}:")
    assert app.artifacts_footer_restores == 2


def test_chats_percent_n_never_copies_a_changespec_name() -> None:
    app = _CopyHarness()
    app.current_artifacts_subtab = "chats"
    app.changespecs = [SimpleNamespace(name="hidden-pr")]
    app._copy_cl_name = MagicMock()  # type: ignore[method-assign]

    assert app._handle_copy_key("n") is False

    app._copy_cl_name.assert_not_called()
    assert "Chats:" in app.notifications[-1][0]


def test_commits_copy_targets_use_the_visible_commit_and_terminal_plan_tag() -> None:
    app = _CopyHarness()
    entry = SimpleNamespace(
        repo="sase",
        commit=SimpleNamespace(full_id="a" * 40),
    )
    message = (
        "Subject\n\nSASE_PLAN=plans:202607/old.md\nSASE_PLAN=plans:202607/current.md"
    )
    app.commits_pane = SimpleNamespace(
        _selected_entry=lambda: entry,
        _view_spec=lambda _entry: SimpleNamespace(message=message),
    )

    for key in ("percent_sign", "m", "r", "p"):
        assert app._handle_copy_key(key) is True

    assert [value for value, _message in app.copies] == [
        "a" * 40,
        message,
        f"sase@{'a' * 40}",
        "plans:202607/current.md",
    ]


def test_plans_copy_targets_use_the_selected_plan_payload() -> None:
    app = _CopyHarness()
    app.current_artifacts_subtab = "plans"
    proposal = SimpleNamespace(
        plan_path="/tmp/plan.md",
        title="Copy all artifacts",
        body="# Copy all artifacts\n\nBody.",
    )
    row = SimpleNamespace(proposal=proposal, archive=None, issue=None)
    app.plans_pane = SimpleNamespace(
        selected_row=lambda: row,
        selected_preview=lambda: None,
    )

    for key in ("p", "t", "b"):
        assert app._handle_copy_key(key) is True

    assert [value for value, _message in app.copies] == [
        proposal.plan_path,
        proposal.title,
        proposal.body,
    ]


def test_chats_copy_targets_use_path_agent_and_full_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _CopyHarness()
    app.current_artifacts_subtab = "chats"
    entry = SimpleNamespace(
        absolute_path="/tmp/chat.md",
        agent_local_name="copy-mode--worker",
        agent=None,
    )
    app.chats_pane = SimpleNamespace(selected_entry=entry)
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.chats_detail.read_full_chat",
        lambda _entry: "# Full transcript",
    )

    for key in ("p", "a", "t"):
        assert app._handle_copy_key(key) is True

    assert [value for value, _message in app.copies] == [
        "/tmp/chat.md",
        "copy-mode--worker",
        "# Full transcript",
    ]


def test_bugs_copy_targets_include_an_agent_ready_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _CopyHarness()
    app.current_artifacts_subtab = "bugs"
    issue = SimpleNamespace(
        number=42,
        title="Copy this issue",
        body="Reproduction steps.",
        url="https://example.test/issues/42",
    )
    app.bugs_pane = SimpleNamespace(
        selected_issue=issue,
        project_scope="alpha",
        project_file="/tmp/alpha.sase",
        snapshot=SimpleNamespace(display_name="Alpha"),
    )
    monkeypatch.setattr(
        "sase.workspace_provider.detect_workflow_type",
        lambda _path: "gh",
    )

    for key in ("b", "u", "t", "p"):
        assert app._handle_copy_key(key) is True

    assert [value for value, _message in app.copies[:3]] == [
        "#42",
        issue.url,
        issue.title,
    ]
    prompt = app.copies[3][0]
    assert prompt.startswith("#gh:Alpha Work on external bug #42")
    assert "bug_id: 42" in prompt


@pytest.mark.parametrize(
    ("subtab", "expected"),
    [
        (
            "commits",
            [
                ("%", "SHA"),
                ("m", "message"),
                ("r", "repo@SHA"),
                ("p", "plan ref"),
                ("s", "snap"),
            ],
        ),
        (
            "plans",
            [("p", "path"), ("t", "title"), ("b", "body"), ("s", "snap")],
        ),
        (
            "chats",
            [
                ("p", "path"),
                ("a", "agent"),
                ("t", "transcript"),
                ("s", "snap"),
            ],
        ),
        (
            "bugs",
            [
                ("b", "issue #"),
                ("u", "url"),
                ("t", "title"),
                ("p", "agent prompt"),
                ("s", "snap"),
            ],
        ),
    ],
)
def test_copy_footer_uses_the_active_artifacts_subtab(
    subtab: str,
    expected: list[tuple[str, str]],
) -> None:
    footer = KeybindingFooter()
    footer.set_keymap_registry(load_keymap_registry({}))
    footer._update_display = MagicMock()  # type: ignore[method-assign]

    footer.update_copy_bindings("changespecs", artifacts_subtab=subtab)

    footer._update_display.assert_called_once_with(expected, mode_label="COPY")
