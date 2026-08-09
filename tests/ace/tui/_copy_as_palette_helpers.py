"""Shared helpers for Copy as palette tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from textual.app import App

from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.modals.copy_as_modal import CopyAsModal
from sase.ace.tui.modals.copy_as_types import CopyAsContext, CopyAsRow
from sase.ace.tui.widgets.artifacts.beads_list import BeadRow, bead_row_target
from sase.bead.model import Issue, IssueType


class PaletteHarness:
    def __init__(self) -> None:
        self.current_tab = "patches"
        self.current_artifacts_subtab = "commits"
        self.current_files_subtab = "plans"
        self.current_idx = 0
        self.patches: list[Any] = []
        self._axe_items: list[Any] = []
        self._artifacts_marked_targets: dict[str, set[tuple[str, ...]]] = {}
        self._keymap_registry = load_keymap_registry({})
        self.notifications: list[tuple[str, str]] = []
        self.commits_pane: Any = None
        self.beads_pane: Any = None
        self.plans_pane: Any = None
        self.chats_pane: Any = None
        self.files_pane: Any = None
        self.bugs_pane: Any = None
        self.agent: Any = None

    @property
    def current_artifacts_pane_key(self) -> str:
        """Expose the active leaf pane like ``AceApp`` does."""

        # A few unit cases assign a leaf directly because this harness predates
        # the nested Files shell. Keep that shorthand local to the harness.
        if self.current_artifacts_subtab in {"plans", "chats", "other"}:
            return self.current_artifacts_subtab
        if self.current_artifacts_subtab == "files":
            return "other"
        return self.current_artifacts_subtab

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _commits_pane(self) -> Any:
        return self.commits_pane

    def _plans_pane(self) -> Any:
        return self.plans_pane

    def _beads_pane(self) -> Any:
        return self.beads_pane

    def _chats_pane(self) -> Any:
        return self.chats_pane

    def _files_pane(self) -> Any:
        return self.files_pane

    def _bugs_pane(self) -> Any:
        return self.bugs_pane

    def _get_selected_agent(self) -> Any:
        return self.agent


def commit_entry(
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


def commit_target(entry: Any) -> tuple[str, ...]:
    return ("commit", entry.repo, entry.commit.full_id)


def commit_pane(
    entries: tuple[Any, ...],
    *,
    target_order: tuple[tuple[str, ...], ...] | None = None,
) -> Any:
    ordered = target_order or tuple(commit_target(entry) for entry in entries)
    selected = next(entry for entry in entries if commit_target(entry) == ordered[0])
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


def file_entry(
    artifact_id: str,
    *,
    label: str,
    kind: str,
    path: str | None,
    source_path: str | None,
    size_bytes: int,
    vcs_repo: str | None = None,
    vcs_sha: str | None = None,
    vcs_relpath: str | None = None,
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
        vcs_repo=vcs_repo,
        vcs_sha=vcs_sha,
        vcs_relpath=vcs_relpath,
    )


def file_pane(
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


def bead_pane(
    *,
    description: str = "Polish the copy palette.",
    notes: str = "Keep previews warm.",
    design: str = "plans:202608/copy_palette.md",
) -> Any:
    issue = Issue(
        id="sase-copy.1",
        title="Complete bead copy mode",
        issue_type=IssueType.PHASE,
        parent_id="sase-copy",
        description=description,
        notes=notes,
        design=design,
    )
    row = BeadRow("phase", "phase:sase-copy.1", "sase", issue)
    target = bead_row_target(row)
    return SimpleNamespace(
        _rows={row.row_id: row},
        snapshot=SimpleNamespace(display_names={"sase": "SASE"}),
        entry_targets=lambda: (target,),
        selected_entry_target=lambda: target,
        selected_row=lambda: row,
        project_scope="sase",
    )


class CopyAsModalApp(App[None]):
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


def modal_context(*rows: CopyAsRow) -> CopyAsContext:
    return CopyAsContext(
        group="patches",
        subtitle="SASE · copy_as_palette",
        unknown_context="Patches",
        rows=rows,
    )


def copy_as_row(
    key: str,
    target: str,
    *,
    category: str = "Identity",
) -> CopyAsRow:
    return CopyAsRow(
        key=key,
        key_display=key,
        target=target,
        label=f"Copy {target}",
        category=category,  # type: ignore[arg-type]
        preview=f"{target} preview",
    )


def controlled_artifact_pane(subtab: str) -> Any:
    if subtab == "commits":
        return commit_pane((commit_entry("a", subject="Live commit"),))
    if subtab == "beads":
        return bead_pane()
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
    if subtab == "other":
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
