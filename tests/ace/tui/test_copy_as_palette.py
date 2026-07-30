"""Focused behavioral coverage for the registry-driven Copy as palette."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Literal
from unittest.mock import MagicMock

import pytest
from textual.app import App

from sase.ace.testing import AcePage
from sase.ace.testing.fixtures import make_changespec
from sase.ace.tui.actions.clipboard._palette import build_copy_as_context
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.modals.copy_as_modal import CopyAsModal
from sase.ace.tui.modals.copy_as_types import CopyAsContext, CopyAsRow
from sase.ace.tui.modals.preview_panel_modal import PreviewPanelModal
from sase.ace.tui.widgets import KeybindingFooter
from sase.ace.tui.widgets._prompt_preview_target import PreviewPayload


class _PaletteHarness:
    def __init__(self) -> None:
        self.current_tab = "changespecs"
        self.current_artifacts_subtab = "commits"
        self.current_idx = 0
        self.changespecs: list[Any] = []
        self._axe_items: list[Any] = []
        self._artifacts_marked_targets: dict[str, set[tuple[str, ...]]] = {}
        self._keymap_registry = load_keymap_registry({})
        self.notifications: list[tuple[str, str]] = []
        self.commits_pane: Any = None
        self.plans_pane: Any = None
        self.chats_pane: Any = None
        self.files_pane: Any = None
        self.bugs_pane: Any = None
        self.agent: Any = None

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _commits_pane(self) -> Any:
        return self.commits_pane

    def _plans_pane(self) -> Any:
        return self.plans_pane

    def _chats_pane(self) -> Any:
        return self.chats_pane

    def _files_pane(self) -> Any:
        return self.files_pane

    def _bugs_pane(self) -> Any:
        return self.bugs_pane

    def _get_selected_agent(self) -> Any:
        return self.agent


def _commit_entry(
    letter: str,
    *,
    subject: str,
    plan: str | None = None,
) -> Any:
    body = "" if plan is None else f"SASE_PLAN={plan}"
    return SimpleNamespace(
        repo="sase",
        commit=SimpleNamespace(
            full_id=letter * 40,
            short_id=letter * 7,
            subject=subject,
            body=body,
        ),
    )


def _commit_target(entry: Any) -> tuple[str, ...]:
    return ("commit", entry.repo, entry.commit.full_id)


def _commit_pane(
    entries: tuple[Any, ...],
    *,
    target_order: tuple[tuple[str, ...], ...] | None = None,
) -> Any:
    ordered = target_order or tuple(_commit_target(entry) for entry in entries)
    selected = next(entry for entry in entries if _commit_target(entry) == ordered[0])
    return SimpleNamespace(
        result=SimpleNamespace(commits=entries),
        filters=SimpleNamespace(project="sase"),
        snapshot=SimpleNamespace(display_name="SASE"),
        entry_targets=lambda: ordered,
        selected_entry_target=lambda: ordered[0],
        _selected_entry=lambda: selected,
        _view_spec=lambda _entry: pytest.fail(
            "palette construction must not build commit view specs"
        ),
    )


def _file_entry(
    artifact_id: str,
    *,
    label: str,
    kind: str,
    path: str,
    source_path: str | None,
    size_bytes: int,
) -> Any:
    return SimpleNamespace(
        id=artifact_id,
        label=label,
        kind=kind,
        path=path,
        source_path=source_path,
        size_bytes=size_bytes,
        project="sase",
        workspace_dir="/workspace",
    )


def _file_pane(
    entries: tuple[Any, ...],
    *,
    view_modes: dict[str, str],
    target_order: tuple[tuple[str, ...], ...] | None = None,
) -> Any:
    ordered = target_order or tuple(("file", entry.id) for entry in entries)
    by_target = {("file", entry.id): entry for entry in entries}
    selected = by_target[ordered[0]]
    rows = {
        entry.id: SimpleNamespace(option_id=entry.id, entry=entry) for entry in entries
    }
    snapshot = SimpleNamespace(
        display_name="SASE",
        view_modes=view_modes,
        view_mode_for=lambda entry: view_modes[entry.id],
    )
    return SimpleNamespace(
        _rows=rows,
        snapshot=snapshot,
        selected_entry=selected,
        selected_view_mode=view_modes[selected.id],
        entry_targets=lambda: ordered,
        selected_entry_target=lambda: ordered[0],
        entries_for_targets=lambda targets: tuple(
            by_target[target] for target in targets if target in by_target
        ),
        project_scope="sase",
        project_file="/workspace/sase.sase",
    )


def test_commit_rows_join_registry_keys_availability_and_warm_previews() -> None:
    app = _PaletteHarness()
    entry = _commit_entry(
        "a",
        subject="Add the Copy as palette",
        plan="plans:202607/copy_as_palette.md",
    )
    app.commits_pane = _commit_pane((entry,))

    context = build_copy_as_context(app)

    assert context is not None
    assert context.group == "artifacts_commits"
    assert context.subtitle == "SASE · sase@aaaaaaa"
    assert [(row.target, row.key_display) for row in context.rows] == [
        ("sha", "%"),
        ("reference", "@"),
        ("link", "l"),
        ("message", "m"),
        ("repo_sha", "r"),
        ("plan", "p"),
        ("json", "J"),
        ("handoff", "!"),
        ("snapshot", "s"),
    ]
    previews = {row.target: row.preview for row in context.rows}
    assert previews["sha"] == "a" * 40
    assert previews["message"] == "Add the Copy as palette"
    assert previews["plan"] == "plans:202607/copy_as_palette.md"


def test_files_rows_cover_every_default_target_with_warm_previews() -> None:
    app = _PaletteHarness()
    app.current_artifacts_subtab = "files"
    entry = _file_entry(
        "default:0123456789abcdef01234567",
        label="Copy notes",
        kind="markdown",
        path="/workspace/artifacts/copy.md",
        source_path="/workspace/notes/copy.md",
        size_bytes=2048,
    )
    app.files_pane = _file_pane(
        (entry,),
        view_modes={entry.id: "markdown"},
    )

    context = build_copy_as_context(app)

    assert context is not None
    assert context.group == "artifacts_files"
    assert context.subtitle == "SASE · Copy notes"
    assert [(row.target, row.key_display) for row in context.rows] == [
        ("contents", "%"),
        ("reference", "@"),
        ("link", "L"),
        ("path", "p"),
        ("source", "o"),
        ("label", "l"),
        ("json", "j"),
        ("handoff", "!"),
        ("snapshot", "s"),
    ]
    assert {row.target: row.preview for row in context.rows} == {
        "contents": "markdown · 2.0 KiB",
        "reference": f"@file:{entry.id}",
        "link": f"[Copy notes](file:{entry.id})",
        "path": "/workspace/artifacts/copy.md",
        "source": "/workspace/notes/copy.md",
        "label": "Copy notes",
        "json": "markdown · 2.0 KiB · metadata",
        "handoff": f"@file:{entry.id} · new agent prompt",
        "snapshot": "current Artifacts pane",
    }


def test_files_rows_filter_binary_contents_and_missing_source_from_warm_state() -> None:
    app = _PaletteHarness()
    app.current_artifacts_subtab = "files"
    entry = _file_entry(
        "default:fedcba987654321001234567",
        label="Copy image",
        kind="image",
        path="/workspace/artifacts/copy.png",
        source_path=None,
        size_bytes=4096,
    )
    app.files_pane = _file_pane(
        (entry,),
        view_modes={entry.id: "image"},
    )

    context = build_copy_as_context(app)

    assert context is not None
    targets = {row.target for row in context.rows}
    assert "contents" not in targets
    assert "source" not in targets
    assert targets == {
        "reference",
        "link",
        "path",
        "label",
        "json",
        "handoff",
        "snapshot",
    }


def test_marked_files_keep_partially_representable_targets_with_warm_counts() -> None:
    app = _PaletteHarness()
    app.current_artifacts_subtab = "files"
    text = _file_entry(
        "default:111111111111111111111111",
        label="Copy text",
        kind="file",
        path="/workspace/artifacts/copy.txt",
        source_path="/workspace/source/copy.txt",
        size_bytes=1024,
    )
    image = _file_entry(
        "default:222222222222222222222222",
        label="Copy image",
        kind="image",
        path="/workspace/artifacts/copy.png",
        source_path=None,
        size_bytes=4096,
    )
    visible_order = (("file", image.id), ("file", text.id))
    app.files_pane = _file_pane(
        (text, image),
        view_modes={text.id: "text", image.id: "image"},
        target_order=visible_order,
    )
    app._artifacts_marked_targets = {"files": set(visible_order)}

    context = build_copy_as_context(app)

    assert context is not None
    previews = {row.target: row.preview for row in context.rows}
    assert previews["contents"] == "1/2 marked · copyable contents"
    assert previews["source"] == "1/2 marked · source paths"
    assert previews["link"] == "2 marked · Markdown links"


@pytest.mark.parametrize(
    ("winner", "loser"),
    tuple(
        zip(
            (
                "snapshot",
                "reference",
                "handoff",
                "link",
                "json",
                "contents",
                "path",
                "source",
            ),
            (
                "reference",
                "handoff",
                "link",
                "json",
                "contents",
                "path",
                "source",
                "label",
            ),
            strict=True,
        )
    ),
)
def test_files_collision_winners_match_dispatch_precedence(
    winner: str,
    loser: str,
) -> None:
    app = _PaletteHarness()
    app.current_artifacts_subtab = "files"
    entry = _file_entry(
        "default:0123456789abcdef01234567",
        label="Copy notes",
        kind="markdown",
        path="/workspace/artifacts/copy.md",
        source_path="/workspace/notes/copy.md",
        size_bytes=2048,
    )
    app.files_pane = _file_pane(
        (entry,),
        view_modes={entry.id: "markdown"},
    )
    app._keymap_registry = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "copy_mode": {
                        "keys": {
                            "artifacts_files": {
                                winner: "x",
                                loser: "x",
                            }
                        }
                    }
                }
            }
        }
    )

    context = build_copy_as_context(app)

    assert context is not None
    assert next(row for row in context.rows if row.key == "x").target == winner
    assert loser not in {row.target for row in context.rows}


def test_commit_plan_target_is_filtered_when_warm_row_has_no_plan() -> None:
    app = _PaletteHarness()
    app.commits_pane = _commit_pane((_commit_entry("a", subject="No linked plan"),))

    context = build_copy_as_context(app)

    assert context is not None
    assert "plan" not in {row.target for row in context.rows}


def test_marked_commit_context_uses_visible_order_and_plural_labels() -> None:
    app = _PaletteHarness()
    first = _commit_entry("a", subject="First visible")
    second = _commit_entry("b", subject="Second visible")
    visible_order = (_commit_target(second), _commit_target(first))
    app.commits_pane = _commit_pane(
        (first, second),
        target_order=visible_order,
    )
    app._artifacts_marked_targets = {"commits": set(visible_order)}

    context = build_copy_as_context(app)

    assert context is not None
    assert context.subtitle == "2 marked commits · SASE"
    sha = next(row for row in context.rows if row.target == "sha")
    message = next(row for row in context.rows if row.target == "message")
    assert sha.label == "commit SHAs"
    assert message.label == "commit messages"
    assert sha.preview == f"{'b' * 40} · +1"
    assert message.preview == "Second visible · +1"


def test_changespec_context_filters_missing_pr_fields_and_uses_display_name() -> None:
    app = _PaletteHarness()
    app.current_artifacts_subtab = "prs"
    changespec = make_changespec(name="copy_as_palette", cl=None)
    changespec.project_display_name = "SASE"  # type: ignore[attr-defined]
    app.changespecs = [changespec]

    context = build_copy_as_context(app)

    assert context is not None
    assert context.subtitle == "SASE · copy_as_palette"
    targets = {row.target for row in context.rows}
    assert "bug" not in targets
    assert "pr_number" not in targets
    assert "link" not in targets
    assert {"raw", "name", "spec", "snapshot"} <= targets


def test_duplicate_and_rebound_accelerators_follow_dispatch_precedence() -> None:
    app = _PaletteHarness()
    app.current_artifacts_subtab = "prs"
    app.changespecs = [make_changespec(name="copy_as_palette")]
    app._keymap_registry = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "copy_mode": {
                        "keys": {
                            "changespecs": {
                                "raw": "q",
                                "name": "q",
                                "spec": "j",
                                "snapshot": "k",
                            }
                        }
                    }
                }
            }
        }
    )

    context = build_copy_as_context(app)

    assert context is not None
    by_key = {row.key: row.target for row in context.rows}
    assert by_key["q"] == "raw"
    assert "name" not in {row.target for row in context.rows}
    assert by_key["j"] == "spec"
    assert by_key["k"] == "snapshot"


@pytest.mark.parametrize(
    ("tab", "warning"),
    [
        ("commits", "No commits entry to copy"),
        ("plans", "No plans entry to copy"),
        ("chats", "No chats entry to copy"),
        ("bugs", "No bugs entry to copy"),
        ("files", "No files entry to copy"),
    ],
)
def test_empty_artifacts_context_warns(tab: str, warning: str) -> None:
    app = _PaletteHarness()
    app.current_artifacts_subtab = tab

    assert build_copy_as_context(app) is None
    assert app.notifications == [(warning, "warning")]


def test_agent_and_axe_contexts_require_a_live_selection() -> None:
    app = _PaletteHarness()
    app.current_tab = "agents"
    assert build_copy_as_context(app) is None
    assert app.notifications[-1] == ("No agent selected", "warning")

    app.current_tab = "axe"
    assert build_copy_as_context(app) is None
    assert app.notifications[-1] == ("No AXE item to copy", "warning")


class _CopyAsModalApp(App[None]):
    def __init__(self, context: CopyAsContext) -> None:
        super().__init__()
        self.context = context
        self.results: list[CopyAsRow | None] = []
        self.messages: list[tuple[str, str]] = []

    def on_mount(self) -> None:
        self.push_screen(CopyAsModal(self.context), self.results.append)

    def notify(
        self,
        message: str,
        *,
        severity: str = "information",
        **_kwargs: Any,
    ) -> None:
        self.messages.append((message, severity))


def _modal_context(*rows: CopyAsRow) -> CopyAsContext:
    return CopyAsContext(
        group="changespecs",
        subtitle="SASE · copy_as_palette",
        unknown_context="ChangeSpecs",
        rows=rows,
    )


def _row(key: str, target: str, *, category: str = "Identity") -> CopyAsRow:
    return CopyAsRow(
        key=key,
        key_display=key,
        target=target,
        label=f"Copy {target}",
        category=category,  # type: ignore[arg-type]
        preview=f"{target} preview",
    )


@pytest.mark.parametrize(
    ("key", "target"), [("q", "raw"), ("j", "spec"), ("k", "snapshot")]
)
async def test_configured_accelerators_win_over_modal_navigation(
    key: str,
    target: str,
) -> None:
    context = _modal_context(
        _row("q", "raw", category="Content"),
        _row("j", "spec", category="Content"),
        _row("k", "snapshot", category="Actions"),
    )
    app = _CopyAsModalApp(context)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press(key)
        await pilot.pause()

    assert app.results == [next(row for row in context.rows if row.target == target)]


async def test_modal_navigation_enter_unknown_and_cancel_behavior() -> None:
    first = _row("x", "name")
    second = _row("y", "raw", category="Content")
    app = _CopyAsModalApp(_modal_context(first, second))

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("z")
        assert isinstance(app.screen_stack[-1], CopyAsModal)
        assert app.messages == [("Unknown copy key (ChangeSpecs: x, y)", "warning")]

        await pilot.press("j", "enter")
        await pilot.pause()

    assert app.results == [second]


async def test_disabled_accelerator_explains_reason_and_keeps_palette_open() -> None:
    row = CopyAsRow(
        key="c",
        key_display="c",
        target="contents",
        label="Copy contents",
        category="Content",
        preview="unavailable",
        disabled_reason="Contents copy is unavailable",
    )
    app = _CopyAsModalApp(_modal_context(row))

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("c")

        assert isinstance(app.screen_stack[-1], CopyAsModal)
        assert app.messages == [("Contents copy is unavailable", "warning")]

        await pilot.press("escape")
        await pilot.pause()

    assert app.results == [None]


async def test_modal_mouse_selection_dispatches_highlighted_row() -> None:
    first = _row("x", "name")
    app = _CopyAsModalApp(_modal_context(first))

    async with app.run_test(size=(80, 24)) as pilot:
        modal = app.screen_stack[-1]
        assert isinstance(modal, CopyAsModal)
        option_list = modal.query_one("#copy-as-list")
        await pilot.click(option_list, offset=(2, 2))
        await pilot.pause()

    assert app.results == [first]


async def test_q_and_escape_cancel_when_not_configured() -> None:
    for key in ("q", "escape"):
        app = _CopyAsModalApp(_modal_context(_row("x", "name")))
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press(key)
            await pilot.pause()
        assert app.results == [None]


async def test_pr_palette_dispatch_and_lifecycle_parity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage() as page:
        page.app.current_artifacts_subtab = "prs"
        await page.expect_state("artifacts_subtab", "prs")
        copy_name = MagicMock()
        monkeypatch.setattr(page.app, "_copy_cl_name", copy_name)

        await page.press("%")
        await page.expect_modal("CopyAsModal")
        assert page.app._copy_mode_active is True

        await page.press("n")
        await page.wait_for(lambda _state: len(page.app.screen_stack) == 1)

        copy_name.assert_called_once_with()
        assert page.app._copy_mode_active is False

        await page.press("%")
        await page.expect_modal("CopyAsModal")
        await page.press("enter")
        await page.wait_for(lambda _state: len(page.app.screen_stack) == 1)

        assert copy_name.call_count == 2


async def test_real_escape_and_q_restore_normal_footer() -> None:
    async with AcePage() as page:
        page.app.current_artifacts_subtab = "prs"
        await page.expect_state("artifacts_subtab", "prs")
        footer = page.query_one_widget("#keybinding-footer", KeybindingFooter)

        for key in ("escape", "q"):
            await page.press("%")
            await page.expect_modal("CopyAsModal")
            assert footer._last_layout_inputs is not None
            assert footer._last_layout_inputs[1] == "COPY"

            await page.press(key)
            await page.wait_for(lambda _state: len(page.app.screen_stack) == 1)

            assert page.app._copy_mode_active is False
            assert footer._last_layout_inputs is not None
            assert footer._last_layout_inputs[1] is None


async def test_snapshot_dispatch_waits_until_palette_is_unmounted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_frames: list[tuple[str, bool]] = []
    async with AcePage() as page:
        page.app.current_artifacts_subtab = "prs"
        await page.expect_state("artifacts_subtab", "prs")
        monkeypatch.setattr(
            page.app,
            "_copy_snapshot",
            lambda: captured_frames.append(
                (
                    type(page.app.screen_stack[-1]).__name__,
                    "Copy as" in page.screen,
                )
            ),
        )

        await page.press("%")
        await page.expect_modal("CopyAsModal")
        await page.press("s")
        await page.wait_for(lambda _state: len(page.app.screen_stack) == 1)
        await page.pause()

    assert captured_frames == [("Screen", False)]


async def test_unknown_key_retains_real_palette_and_copy_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[tuple[str, str]] = []
    async with AcePage() as page:
        page.app.current_artifacts_subtab = "prs"
        await page.expect_state("artifacts_subtab", "prs")
        monkeypatch.setattr(
            page.app,
            "notify",
            lambda message, *, severity="information", **_kwargs: messages.append(
                (message, severity)
            ),
        )

        await page.press("%")
        await page.expect_modal("CopyAsModal")
        await page.press("x")

        assert isinstance(page.app.screen_stack[-1], CopyAsModal)
        assert page.app._copy_mode_active is True
        assert messages[-1][0].startswith("Unknown copy key (ChangeSpecs:")


async def test_copy_palette_stacks_over_forwarding_modal() -> None:
    payload = PreviewPayload(
        kind_label="file",
        icon="@",
        title="copy_as_palette.md",
        source_path="/workspace/copy_as_palette.md",
        lexer="markdown",
        content="# Copy as palette",
    )
    async with AcePage() as page:
        page.app.current_artifacts_subtab = "prs"
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(PreviewPanelModal(payload))
        await page.expect_modal("PreviewPanelModal")

        await page.press("%")
        await page.expect_modal("CopyAsModal")
        assert isinstance(page.app.screen_stack[-2], PreviewPanelModal)

        await page.press("escape")
        await page.expect_modal("PreviewPanelModal")
        assert page.app._copy_mode_active is False


def _controlled_artifact_pane(subtab: str) -> Any:
    if subtab == "commits":
        return _commit_pane((_commit_entry("a", subject="Live commit"),))
    if subtab == "plans":
        proposal = SimpleNamespace(
            notification=SimpleNamespace(id="plan-notice"),
            plan_path="/workspace/plans/copy.md",
            title="Copy palette plan",
            body="# Copy palette plan",
        )
        row = SimpleNamespace(
            kind="proposal",
            row_id="plan-row",
            project="sase",
            proposal=proposal,
            issue=None,
            archive=None,
        )
        plan_target = ("plan", "sase", "proposal", "plan-notice")
        return SimpleNamespace(
            _rows={"plan-row": row},
            snapshot=SimpleNamespace(display_name="SASE"),
            entry_targets=lambda: (plan_target,),
            selected_entry_target=lambda: plan_target,
            selected_row=lambda: row,
        )
    if subtab == "chats":
        entry = SimpleNamespace(
            absolute_path="/workspace/chats/agent.md",
            basename="agent.md",
            agent_local_name="copy-worker",
            prompt_snippet="Implement the copy palette",
            size_bytes=2048,
        )
        row = SimpleNamespace(option_id="chat-row", entry=entry)
        chat_target = ("chat", entry.absolute_path)
        return SimpleNamespace(
            _rows={"chat-row": row},
            snapshot=SimpleNamespace(display_name="SASE"),
            entry_targets=lambda: (chat_target,),
            selected_entry_target=lambda: chat_target,
            selected_entry=entry,
        )
    if subtab == "files":
        entry = SimpleNamespace(
            id="artifact-file",
            label="copy.png",
            kind="image",
            size_bytes=4096,
        )
        row = SimpleNamespace(option_id="file-row", entry=entry)
        file_target = ("file", entry.id)
        return SimpleNamespace(
            _rows={"file-row": row},
            snapshot=SimpleNamespace(display_name="SASE"),
            entry_targets=lambda: (file_target,),
            selected_entry_target=lambda: file_target,
            selected_entry=entry,
        )

    issue = SimpleNamespace(
        number=42,
        title="Copy palette bug",
        body="Add a discoverable picker",
        url="https://example.test/issues/42",
    )
    bug_target = ("bug", "sase", "42")
    return SimpleNamespace(
        issues=(issue,),
        project_scope="sase",
        snapshot=SimpleNamespace(display_name="SASE"),
        entry_targets=lambda: (bug_target,),
        selected_entry_target=lambda: bug_target,
        selected_issue=issue,
        _issue_target=lambda _issue: bug_target,
    )


@pytest.mark.parametrize("subtab", ["commits", "plans", "chats", "bugs", "files"])
async def test_percent_opens_palette_for_each_live_artifacts_subtab(
    subtab: Literal["commits", "plans", "chats", "bugs", "files"],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pane = _controlled_artifact_pane(subtab)
    async with AcePage() as page:
        page.app.current_artifacts_subtab = subtab
        await page.expect_state("artifacts_subtab", subtab)
        monkeypatch.setattr(page.app, f"_{subtab}_pane", lambda: pane)
        page.app._artifacts_marked_targets.clear()

        await page.press("%")
        await page.expect_modal("CopyAsModal")

        modal = page.app.screen_stack[-1]
        assert isinstance(modal, CopyAsModal)
        assert modal.context.group == f"artifacts_{subtab}"


@pytest.mark.parametrize("tab", ["agents", "axe"])
async def test_percent_opens_palette_for_agent_and_axe_selection(
    tab: Literal["agents", "axe"],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage(initial_tab=tab) as page:
        if tab == "agents":
            agent = SimpleNamespace(
                response_path="/workspace/chats/copy-worker.md",
                presented_agent_name="copy-worker",
                project_display_name="SASE",
                status="DONE",
            )
            monkeypatch.setattr(page.app, "_get_selected_agent", lambda: agent)
        else:
            page.app._axe_items = [SimpleNamespace(name="Copy palette")]
            page.app.current_idx = 0

        await page.press("%")
        await page.expect_modal("CopyAsModal")

        modal = page.app.screen_stack[-1]
        assert isinstance(modal, CopyAsModal)
        assert modal.context.group == tab
