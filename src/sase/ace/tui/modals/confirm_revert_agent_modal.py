"""Confirmation modal for reverting agent commits (single or bulk)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.cells import cell_len
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from sase.ace.revert_agent import BulkRevertPreview

if TYPE_CHECKING:
    from sase.ace.revert_agent import RepoRevertPlan, RevertCommit, RevertPreview

# How many commit rows to show before collapsing the remainder into a count.
_MAX_COMMIT_ROWS = 10
_MAX_SDD_PATHS = 6
# How many skipped (no-match) target names to list before collapsing.
_MAX_SKIPPED_TARGETS = 6
_REPO_CARD_WIDTH = 54
_STATUS_GLYPH = "●"
_BLOCKED_GLYPH = "▲"
_REVERT_GLYPH = "⟲"


def _truncate_plain(value: str, max_cells: int) -> str:
    """Collapse and truncate text to a fixed terminal cell width."""
    plain = " ".join(value.split())
    if cell_len(plain) <= max_cells:
        return plain
    if max_cells <= 3:
        return "." * max_cells

    limit = max_cells - 3
    out = ""
    for char in plain:
        if cell_len(out + char) > limit:
            break
        out += char
    return out.rstrip() + "..."


def _noun(count: int, singular: str, plural: str | None = None) -> str:
    if count == 1:
        return singular
    return plural or f"{singular}s"


class ConfirmRevertAgentModal(ModalScreen[bool]):
    """Confirm reverting agent commits.

    Renders either a single-agent :class:`RevertPreview` or a multi-agent
    :class:`BulkRevertPreview`. Both modes show the per-repository commit
    groups, blocked repositories that will be skipped, and the per-repo
    transaction semantics.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
        Binding("y", "confirm", "Yes"),
        Binding("n", "cancel", "No"),
        Binding("j", "scroll_repos_down", "Scroll down", priority=True),
        Binding("down", "scroll_repos_down", "Scroll down", priority=True),
        Binding("k", "scroll_repos_up", "Scroll up", priority=True),
        Binding("up", "scroll_repos_up", "Scroll up", priority=True),
    ]

    def __init__(self, preview: RevertPreview | BulkRevertPreview) -> None:
        super().__init__()
        self.add_class("confirm-dialog")
        self._preview = preview
        self._is_bulk = isinstance(preview, BulkRevertPreview)

    def compose(self) -> ComposeResult:
        dialog = Container(
            id="revert-confirm-container",
            classes="confirm-dialog-panel confirm-dialog--danger",
        )
        dialog.border_title = self._build_border_title()
        dialog.border_subtitle = "y revert · n/esc cancel · j/k scroll"
        with dialog:
            yield Label(self._subtitle(), id="revert-confirm-subtitle")
            yield Static(self._summary_text(), id="revert-confirm-summary")
            with VerticalScroll(id="revert-confirm-repos"):
                yield from self._compose_repo_cards()
            yield Static(
                self._sdd_summary(),
                id="revert-confirm-sdd",
                classes="revert-confirm-caption",
            )
            if self._is_bulk:
                yield Static(
                    self._skipped_summary(),
                    id="revert-confirm-skipped",
                    classes="revert-confirm-caption",
                )
            yield Static(
                self._transaction_summary(),
                id="revert-confirm-semantics",
                classes="revert-confirm-caption",
            )
            with Horizontal(id="revert-confirm-buttons"):
                yield Button("Revert (y)", id="confirm-btn", variant="error")
                yield Button("Cancel (n)", id="cancel-btn", variant="primary")

    def _build_border_title(self) -> Text:
        title = Text()
        title.append(_REVERT_GLYPH, style="bold red")
        title.append("  Revert Agent + Opened Repos", style="bold")
        return title

    def _compose_repo_cards(self) -> ComposeResult:
        revertable = self._preview.revertable_repos
        if revertable:
            for repo in revertable:
                yield Static(
                    self._repo_card_text(repo),
                    classes="revert-confirm-repo-card",
                )
        elif self._preview.commits:
            yield Static(
                self._standalone_commit_card_text(),
                classes="revert-confirm-repo-card",
            )

        for repo in self._preview.blocked_repos:
            yield Static(
                self._blocked_card_text(repo),
                classes="revert-confirm-blocked-card",
            )

    def _subtitle(self) -> str:
        if self._is_bulk:
            preview = self._preview
            assert isinstance(preview, BulkRevertPreview)
            return f"{preview.target_count} marked agents"

        preview = self._preview
        assert not isinstance(preview, BulkRevertPreview)
        scope_word = "family" if preview.scope == "family" else "agent"
        return f"Agent {preview.agent_name} · scope {scope_word}"

    def _summary_text(self) -> Text:
        commit_count = self._preview.commit_count
        repo_count = self._revertable_repo_count()
        commit_noun = _noun(commit_count, "commit")
        repo_noun = _noun(repo_count, "repository", "repositories")

        text = Text()
        text.append("!  ", style="bold red")
        external_count = sum(
            plan.discard_local_changes for plan in self._preview.revertable_repos
        )
        if commit_count:
            text.append("Reverting ", style="bold red")
            text.append(str(commit_count), style="bold")
            text.append(f" {commit_noun} across ")
            text.append(str(repo_count), style="bold")
            text.append(f" {repo_noun}.")
            if external_count:
                text.append(
                    f" Cleaning {external_count} opened external repo(s) in place."
                )
        else:
            text.append("Discarding local changes in ", style="bold red")
            text.append(str(external_count), style="bold")
            text.append(" opened external repo(s).")
        return text

    def _commit_lines(self) -> Text:
        commits: tuple[RevertCommit, ...] = self._preview.commits
        return self._commit_lines_for(commits)

    def _repo_commit_lines(self) -> Text:
        repos = self._preview.revertable_repos
        if not repos:
            return self._commit_lines()

        text = Text()
        for index, repo in enumerate(repos):
            if index:
                text.append("\n\n")
            text.append_text(self._repo_card_text(repo))
        return text

    def _commit_lines_for(
        self,
        commits: tuple[RevertCommit, ...],
        *,
        indent: str = "",
    ) -> Text:
        shown = commits[:_MAX_COMMIT_ROWS]
        text = Text()
        for index, commit in enumerate(shown):
            if index:
                text.append("\n")
            self._append_commit_row(text, commit, indent=indent)
        remaining = len(commits) - len(shown)
        if remaining > 0:
            if shown:
                text.append("\n")
            text.append(f"{indent}... and {remaining} more", style="dim")
        return text

    def _blocked_summary(self) -> Text:
        blocked: tuple[RepoRevertPlan, ...] = self._preview.blocked_repos
        if not blocked:
            return Text("Blocked (will be skipped): (none)", style="dim")
        text = Text()
        for index, repo in enumerate(blocked):
            if index:
                text.append("\n\n")
            text.append_text(self._blocked_card_text(repo))
        return text

    def _sdd_summary(self) -> Text:
        sdd_paths = self._preview.sdd_paths
        if not sdd_paths:
            return Text("SDD provenance: (none)", style="dim")
        shown = sdd_paths[:_MAX_SDD_PATHS]
        summary = ", ".join(shown)
        remaining = len(sdd_paths) - len(shown)
        if remaining > 0:
            summary += f", +{remaining} more"
        return Text(f"SDD provenance: {summary}", style="dim")

    def _skipped_summary(self) -> Text:
        preview = self._preview
        assert isinstance(preview, BulkRevertPreview)
        skipped = preview.skipped_target_names
        if not skipped:
            return Text("Skipped (no commits): (none)", style="dim")
        shown = skipped[:_MAX_SKIPPED_TARGETS]
        summary = ", ".join(shown)
        remaining = len(skipped) - len(shown)
        if remaining > 0:
            summary += f", +{remaining} more"
        return Text(f"Skipped (no commits): {summary}", style="dim")

    def _transaction_summary(self) -> Text:
        has_external_cleanup = any(
            plan.discard_local_changes for plan in self._preview.revertable_repos
        )
        if has_external_cleanup:
            message = (
                "Opened external repos are cleaned in place without network access. "
                "Commit reverts remain independent per repository."
            )
        elif self._is_bulk:
            message = (
                "Each repository is reverted independently; a failure in one "
                "repo does not undo completed repos."
            )
        else:
            message = (
                "This creates one revert commit per repository and pushes each "
                "when a remote/branch is available."
            )
        return Text(message, style="dim")

    def _repo_card_text(self, repo: RepoRevertPlan) -> Text:
        return self._revertable_card_text(
            repo.repo_label,
            repo.is_primary,
            repo.commits,
            repo_kind=repo.repo_kind,
            discard_local_changes=repo.discard_local_changes,
        )

    def _standalone_commit_card_text(self) -> Text:
        return self._revertable_card_text(
            "workspace",
            True,
            self._preview.commits,
            repo_kind="linked",
        )

    def _revertable_card_text(
        self,
        repo_label: str,
        is_primary: bool,
        commits: tuple[RevertCommit, ...],
        *,
        repo_kind: str,
        discard_local_changes: bool = False,
    ) -> Text:
        text = self._repo_header_text(
            repo_label,
            is_primary=is_primary,
            commit_count=len(commits),
            repo_kind=repo_kind,
            discard_local_changes=discard_local_changes,
        )
        if commits:
            text.append("\n")
            text.append_text(self._commit_lines_for(commits, indent="  "))
        else:
            message = (
                "local changes will be discarded"
                if discard_local_changes
                else "(no commits)"
            )
            text.append(f"\n  {message}", style="dim")
        return text

    def _blocked_card_text(self, repo: RepoRevertPlan) -> Text:
        reason = repo.blocked_reason or "blocked"
        text = Text()
        text.append(f"{_BLOCKED_GLYPH}  ", style="bold yellow")
        text.append(_truncate_plain(repo.repo_label, 24), style="bold")
        text.append(
            f" {self._repo_kind(repo.is_primary, repo.repo_kind)}",
            style="dim",
        )
        text.append("  BLOCKED · will be skipped", style="bold yellow")
        text.append(f"\n   {repo.commit_count} commit(s) matched", style="dim")
        text.append("\n   Reason: ", style="dim")
        text.append(reason, style="bold yellow")
        return text

    def _repo_header_text(
        self,
        repo_label: str,
        *,
        is_primary: bool,
        commit_count: int,
        repo_kind: str,
        discard_local_changes: bool,
    ) -> Text:
        kind = self._repo_kind(is_primary, repo_kind)
        count = (
            "local changes" if discard_local_changes else f"{commit_count} commit(s)"
        )
        fixed_cells = 3 + 1 + cell_len(kind) + 1 + cell_len(count)
        label_width = max(12, _REPO_CARD_WIDTH - fixed_cells - 2)
        label = _truncate_plain(repo_label, label_width)

        line = Text()
        line.append(f"{_STATUS_GLYPH}  ", style="bold green")
        line.append(label, style="bold")
        line.append(" ")
        line.append(kind, style="dim")
        line.append(" " * max(1, _REPO_CARD_WIDTH - line.cell_len - cell_len(count)))
        line.append(count, style="dim")
        return line

    def _append_commit_row(
        self,
        text: Text,
        commit: RevertCommit,
        *,
        indent: str,
    ) -> None:
        marker = "  sdd" if commit.sdd_paths else ""
        sha = _truncate_plain(commit.sha, 12)
        prefix_cells = cell_len(indent) + cell_len(sha) + 2
        subject_width = max(10, _REPO_CARD_WIDTH - prefix_cells - cell_len(marker))
        subject = _truncate_plain(commit.subject, subject_width)

        text.append(indent, style="dim")
        text.append(sha, style="bold cyan")
        text.append("  ")
        text.append(subject, style="dim")
        if marker:
            text.append(marker, style="bold black on cyan")

    def _repo_kind(self, is_primary: bool, repo_kind: str) -> str:
        return "primary" if is_primary else repo_kind

    def _revertable_repo_count(self) -> int:
        repo_count = len(self._preview.revertable_repos)
        if repo_count:
            return repo_count
        return 1 if self._preview.commits else 0

    def on_mount(self) -> None:
        """Default focus to the safe action."""
        self.query_one("#cancel-btn", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-btn":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_scroll_repos_down(self) -> None:
        self._scroll_repos(3)

    def action_scroll_repos_up(self) -> None:
        self._scroll_repos(-3)

    def _scroll_repos(self, rows: int) -> None:
        scroll = self.query_one("#revert-confirm-repos", VerticalScroll)
        scroll.scroll_relative(y=rows, animate=False)
