"""Copy-mode coverage for every non-PR Artifacts sub-tab."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import call, MagicMock

import pytest

from sase.ace.tui.actions.clipboard import _artifacts
from sase.ace.testing import AcePage
from sase.ace.tui.actions.clipboard import ClipboardMixin
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.widgets.artifacts.chats_list import ChatRow, chat_row_target
from sase.ace.tui.widgets.artifacts.plans_list import PlanRow, plan_row_target
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
        self.files_pane: Any = None

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

    def _files_pane(self) -> Any:
        return self.files_pane

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


@pytest.mark.parametrize("subtab", ["chats", "files"])
async def test_percent_opens_and_escape_restores_copy_footer_on_real_artifacts_app(
    subtab: str,
) -> None:
    async with AcePage() as page:
        page.app.current_artifacts_subtab = subtab
        await page.expect_state("artifacts_subtab", subtab)
        footer = page.query_one_widget("#keybinding-footer", KeybindingFooter)

        await page.press("%")

        assert page.app._copy_mode_active is True
        assert footer._last_layout_inputs is not None
        assert footer._last_layout_inputs[1] == "COPY"
        if subtab == "files":
            assert footer._last_layout_inputs[0] == [
                ("@", "@ref"),
                ("!", "agent + @ref"),
                ("s", "snap"),
            ]

        await page.press("escape")

        assert page.app._copy_mode_active is False
        assert footer._last_layout_inputs is not None
        assert footer._last_layout_inputs[1] is None


@pytest.mark.parametrize("subtab", ["commits", "plans", "chats", "bugs", "files"])
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


def test_files_percent_unknown_key_never_reaches_changespec_dispatch() -> None:
    app = _CopyHarness()
    app.current_artifacts_subtab = "files"
    app.changespecs = [SimpleNamespace(name="hidden-pr")]
    app._copy_cl_name = MagicMock()  # type: ignore[method-assign]

    assert app._handle_copy_key("n") is False

    app._copy_cl_name.assert_not_called()
    assert "Files:" in app.notifications[-1][0]


@pytest.mark.parametrize("key", ["at", "exclamation_mark"])
def test_files_generic_reference_keys_degrade_safely_on_empty_scaffold(
    key: str,
) -> None:
    app = _CopyHarness()
    app.current_artifacts_subtab = "files"

    assert app._handle_copy_key(key) is True

    assert app.notifications[-1] == ("No files entry selected", "warning")


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


def test_marked_commits_copy_in_visual_order_with_labeled_sections() -> None:
    app = _CopyHarness()
    entries = tuple(
        SimpleNamespace(
            repo="sase",
            commit=SimpleNamespace(
                full_id=character * 40,
                short_id=character * 7,
            ),
        )
        for character in ("a", "b")
    )
    targets = tuple(("commit", entry.repo, entry.commit.full_id) for entry in entries)
    app._artifacts_marked_targets = {"commits": set(targets)}
    app.commits_pane = SimpleNamespace(
        result=SimpleNamespace(commits=entries),
        entry_targets=lambda: targets,
    )

    assert app._handle_copy_key("percent_sign") is True

    assert app.copies == [
        (
            "\n".join(
                (
                    "### sase@aaaaaaa",
                    "```",
                    "a" * 40,
                    "```",
                    "### sase@bbbbbbb",
                    "```",
                    "b" * 40,
                    "```",
                )
            ),
            "Copied 2 commit SHAs",
        )
    ]


def test_marked_plans_copy_the_marked_set() -> None:
    app = _CopyHarness()
    app.current_artifacts_subtab = "plans"
    rows = tuple(
        PlanRow(
            "proposal",
            f"proposal-{index}",
            "alpha",
            proposal=SimpleNamespace(
                notification=SimpleNamespace(id=f"notice-{index}"),
                plan_path=f"/tmp/plan-{index}.md",
                title=f"Plan {index}",
                body=f"Body {index}",
            ),
        )
        for index in (1, 2)
    )
    targets = tuple(plan_row_target(row) for row in rows)
    app._artifacts_marked_targets = {"plans": set(targets)}
    app.plans_pane = SimpleNamespace(
        _rows={row.row_id: row for row in rows},
        entry_targets=lambda: targets,
    )

    assert app._handle_copy_key("t") is True

    copied, message = app.copies[0]
    assert "### proposal-1\n```\nPlan 1\n```" in copied
    assert "### proposal-2\n```\nPlan 2\n```" in copied
    assert message == "Copied 2 plan titles"


def test_marked_chats_copy_the_marked_set() -> None:
    app = _CopyHarness()
    app.current_artifacts_subtab = "chats"
    entries = tuple(
        SimpleNamespace(
            absolute_path=f"/tmp/chat-{index}.md",
            basename=f"chat-{index}",
        )
        for index in (1, 2)
    )
    rows = tuple(
        ChatRow(f"chat-{index}", entry) for index, entry in enumerate(entries, start=1)
    )
    targets = tuple(chat_row_target(row) for row in rows)
    app._artifacts_marked_targets = {"chats": set(targets)}
    app.chats_pane = SimpleNamespace(
        _rows={row.option_id: row for row in rows},
        entry_targets=lambda: targets,
    )

    assert app._handle_copy_key("p") is True

    copied, message = app.copies[0]
    assert "### chat-1\n```\n/tmp/chat-1.md\n```" in copied
    assert "### chat-2\n```\n/tmp/chat-2.md\n```" in copied
    assert message == "Copied 2 chat paths"


def test_marked_bugs_copy_the_marked_set() -> None:
    app = _CopyHarness()
    app.current_artifacts_subtab = "bugs"
    issues = tuple(SimpleNamespace(number=number) for number in (41, 42))

    def issue_target(issue: Any) -> tuple[str, ...]:
        return ("bug", "alpha", str(issue.number))

    targets = tuple(issue_target(issue) for issue in issues)
    app._artifacts_marked_targets = {"bugs": set(targets)}
    app.bugs_pane = SimpleNamespace(
        project_scope="alpha",
        issues=issues,
        entry_targets=lambda: targets,
        _issue_target=issue_target,
    )

    assert app._handle_copy_key("b") is True

    copied, message = app.copies[0]
    assert "### #41\n```\n#41\n```" in copied
    assert "### #42\n```\n#42\n```" in copied
    assert message == "Copied 2 issue numbers"


@pytest.mark.parametrize(
    ("subtab", "expected"),
    [
        (
            "commits",
            [
                ("%", "SHA"),
                ("@", "@ref"),
                ("!", "agent + @ref"),
                ("m", "message"),
                ("r", "repo@SHA"),
                ("p", "plan ref"),
                ("s", "snap"),
            ],
        ),
        (
            "plans",
            [
                ("@", "@ref"),
                ("!", "agent + @ref"),
                ("p", "path"),
                ("t", "title"),
                ("b", "body"),
                ("s", "snap"),
            ],
        ),
        (
            "chats",
            [
                ("@", "@ref"),
                ("!", "agent + @ref"),
                ("p", "path"),
                ("a", "agent"),
                ("t", "transcript"),
                ("s", "snap"),
            ],
        ),
        (
            "bugs",
            [
                ("@", "@ref"),
                ("!", "agent + @ref"),
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


@pytest.mark.parametrize("subtab", ["commits", "plans", "chats", "bugs"])
def test_reference_keys_dispatch_uniformly_across_artifacts_subtabs(
    subtab: str,
) -> None:
    app = _CopyHarness()
    app.current_artifacts_subtab = subtab
    app._run_artifact_reference_action = MagicMock()  # type: ignore[method-assign]

    assert app._handle_copy_key("at") is True
    assert app._handle_copy_key("exclamation_mark") is True

    assert app._run_artifact_reference_action.call_args_list == [
        call(handoff=False),
        call(handoff=True),
    ]


async def test_marked_reference_handoff_seeds_one_project_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _CopyHarness()
    app._show_prompt_input_bar_for_home = MagicMock()  # type: ignore[attr-defined]
    selection = _artifacts._ArtifactReferenceSelection(
        subtab="bugs",
        items=(
            _artifacts._ArtifactReferenceItem(
                "#41",
                ("bug", "alpha", "41"),
                None,
                "alpha",
                "/tmp",
            ),
            _artifacts._ArtifactReferenceItem(
                "#42",
                ("bug", "alpha", "42"),
                None,
                "alpha",
                "/tmp",
            ),
        ),
        marked=True,
        prompt_project="alpha",
        prompt_display_name="Alpha",
        prompt_project_file="/tmp/alpha.sase",
    )
    app._capture_artifact_reference_selection = lambda: selection  # type: ignore[method-assign]
    monkeypatch.setattr(
        _artifacts,
        "_resolve_artifact_references",
        lambda _selection: ("@bug:Alpha#41", "@bug:Alpha#42"),
    )
    monkeypatch.setattr(
        "sase.workspace_provider.detect_workflow_type",
        lambda _project_file: "gh",
    )
    pending: list[Any] = []
    monkeypatch.setattr(
        _artifacts,
        "spawn_pump_free_task",
        lambda _owner, coroutine, **_kwargs: pending.append(coroutine),
    )

    app._run_artifact_reference_action(handoff=True)
    await pending.pop()

    app._show_prompt_input_bar_for_home.assert_called_once_with(
        initial_text="#gh:Alpha @bug:Alpha#41 @bug:Alpha#42 ",
        display_name="Alpha artifact reference",
        history_sort_key="alpha",
    )


async def test_marked_reference_copy_uses_multi_copy_format_and_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _CopyHarness()
    selection = _artifacts._ArtifactReferenceSelection(
        subtab="commits",
        items=(
            _artifacts._ArtifactReferenceItem(
                "sase@aaaaaaa",
                ("commit", "sase", "a" * 40),
                None,
                "alpha",
                "/tmp",
            ),
            _artifacts._ArtifactReferenceItem(
                "sase@bbbbbbb",
                ("commit", "sase", "b" * 40),
                None,
                "alpha",
                "/tmp",
            ),
        ),
        marked=True,
        prompt_project="alpha",
        prompt_display_name="Alpha",
        prompt_project_file="/tmp/alpha.sase",
    )
    app._capture_artifact_reference_selection = lambda: selection  # type: ignore[method-assign]
    monkeypatch.setattr(
        _artifacts,
        "_resolve_artifact_references",
        lambda _selection: (
            f"@commit:sase@{'a' * 40}",
            f"@commit:sase@{'b' * 40}",
        ),
    )
    copied: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda content: copied.append(content) or True,
    )
    pending: list[Any] = []
    monkeypatch.setattr(
        _artifacts,
        "spawn_pump_free_task",
        lambda _owner, coroutine, **_kwargs: pending.append(coroutine),
    )

    app._run_artifact_reference_action(handoff=False)
    await pending.pop()

    assert "### sase@aaaaaaa" in copied[0]
    assert f"@commit:sase@{'a' * 40}" in copied[0]
    assert "### sase@bbbbbbb" in copied[0]
    assert app.notifications[-1] == (
        "Copied 2 artifact references",
        "information",
    )


async def test_unreferenceable_chat_warns_with_the_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _CopyHarness()
    selection = _artifacts._ArtifactReferenceSelection(
        subtab="chats",
        items=(
            _artifacts._ArtifactReferenceItem(
                "imported-chat",
                ("chat", "/imports/chat.md"),
                None,
                "alpha",
                "/tmp",
            ),
        ),
        marked=False,
        prompt_project="alpha",
        prompt_display_name="Alpha",
        prompt_project_file="/tmp/alpha.sase",
    )
    app._capture_artifact_reference_selection = lambda: selection  # type: ignore[method-assign]
    monkeypatch.setattr(
        _artifacts,
        "_resolve_artifact_references",
        lambda _selection: (_ for _ in ()).throw(
            ValueError(
                "imported-chat cannot be referenced because it is an imported "
                "transcript outside the chats root"
            )
        ),
    )
    pending: list[Any] = []
    monkeypatch.setattr(
        _artifacts,
        "spawn_pump_free_task",
        lambda _owner, coroutine, **_kwargs: pending.append(coroutine),
    )

    app._run_artifact_reference_action(handoff=False)
    await pending.pop()

    assert app.notifications[-1] == (
        "imported-chat cannot be referenced because it is an imported "
        "transcript outside the chats root",
        "warning",
    )


def test_reference_resolver_renders_every_artifacts_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from sase.artifact_refs import (
        ArtifactRefContext,
        ArtifactRefDocumentRoot,
        ArtifactRefProject,
    )

    plans_root = tmp_path / "plans"
    chats_root = tmp_path / "chats"
    plan_path = plans_root / "202607" / "artifact.md"
    chat_path = chats_root / "202607" / "agent.md"
    plan_path.parent.mkdir(parents=True)
    chat_path.parent.mkdir(parents=True)
    plan_path.write_text("# Artifact")
    chat_path.write_text("# Chat")
    context = ArtifactRefContext(
        document_roots=(ArtifactRefDocumentRoot("plans", plans_root),),
        chats_root=chats_root,
        artifact_index_path=tmp_path / "index.jsonl",
        repositories=(),
        projects=(ArtifactRefProject("Alpha", "alpha"),),
    )
    monkeypatch.setattr(
        _artifacts,
        "artifact_ref_context",
        lambda *_args, **_kwargs: context,
    )
    sha = "a" * 40
    proposal = SimpleNamespace(plan_path=str(plan_path))
    row = SimpleNamespace(
        row_id="proposal",
        project="alpha",
        kind="proposal",
        proposal=proposal,
        archive=None,
        issue=None,
    )
    cases = (
        (
            "commits",
            _artifacts._ArtifactReferenceItem(
                "commit",
                ("commit", "sase", sha),
                None,
                "alpha",
                str(tmp_path),
            ),
            f"@commit:sase@{sha}",
        ),
        (
            "plans",
            _artifacts._ArtifactReferenceItem(
                "plan",
                ("plan", "alpha", "proposal", "proposal"),
                row,
                "alpha",
                str(tmp_path),
            ),
            "@plans:202607/artifact.md",
        ),
        (
            "chats",
            _artifacts._ArtifactReferenceItem(
                "chat",
                ("chat", str(chat_path)),
                None,
                "alpha",
                str(tmp_path),
            ),
            "@chat:202607/agent.md",
        ),
        (
            "bugs",
            _artifacts._ArtifactReferenceItem(
                "bug",
                ("bug", "alpha", "42"),
                None,
                "alpha",
                str(tmp_path),
            ),
            "@bug:Alpha#42",
        ),
    )
    for subtab, item, expected in cases:
        selection = _artifacts._ArtifactReferenceSelection(
            subtab=subtab,
            items=(item,),
            marked=False,
            prompt_project="alpha",
            prompt_display_name="Alpha",
            prompt_project_file="/tmp/alpha.sase",
        )
        assert _artifacts._resolve_artifact_references(selection) == (expected,)


def test_artifacts_footer_surfaces_only_a_nonzero_mark_count() -> None:
    footer = KeybindingFooter()
    footer.set_keymap_registry(load_keymap_registry({}))
    footer._update_display = MagicMock()  # type: ignore[method-assign]

    footer.show_artifacts_pane(mark_count=3)

    footer._update_display.assert_called_once_with([("u", "unmark (3)")])
