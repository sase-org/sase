"""Interactive filters for the Artifacts Commits timeline."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, SelectionList, Static

from sase.ace.tui.widgets.artifacts.commit_filters import CommitLogFilterValues
from sase.vcs_log.dates import DATE_HELP, VcsLogDateError, parse_time_bound


class CommitFiltersModal(ModalScreen[CommitLogFilterValues | None]):
    """Edit author, time-bound, repository, and row-limit filters."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "apply", "Apply"),
    ]

    def __init__(
        self,
        values: CommitLogFilterValues,
        repo_names: tuple[str, ...],
    ) -> None:
        super().__init__()
        self._values = values
        self._repo_names = repo_names

    def compose(self) -> ComposeResult:
        selected = set(self._values.repos)
        with Container(id="commit-filters-container"):
            yield Static("Log Filters", id="commit-filters-title")
            with Vertical(id="commit-filters-fields"):
                yield Label("Authors (comma-separated substrings)")
                yield Input(
                    value=", ".join(self._values.authors),
                    placeholder="e.g. Ada, @example.com",
                    id="commit-filter-authors",
                )
                with Horizontal(classes="commit-filter-bound-row"):
                    with Vertical():
                        yield Label("Since")
                        yield Input(
                            value=self._values.since_text,
                            placeholder="7d / today / YYYY-MM-DD",
                            id="commit-filter-since",
                        )
                    with Vertical():
                        yield Label("Until")
                        yield Input(
                            value=self._values.until_text,
                            placeholder="today / YYYY-MM-DDTHH:MM",
                            id="commit-filter-until",
                        )
                    with Vertical(classes="commit-filter-limit-column"):
                        yield Label("Limit (0 = all)")
                        yield Input(
                            value=str(self._values.limit),
                            type="integer",
                            id="commit-filter-limit",
                        )
                yield Label("Repositories (leave clear for the full scope)")
                if self._repo_names:
                    yield SelectionList[str](
                        *((name, name, name in selected) for name in self._repo_names),
                        id="commit-filter-repos",
                    )
                else:
                    yield Static(
                        "Repository choices appear after the first refresh.",
                        classes="commit-filter-empty-repos",
                    )
                yield Static(DATE_HELP, id="commit-filter-date-help")
            with Horizontal(id="commit-filter-buttons"):
                yield Button("Cancel", id="commit-filter-cancel")
                yield Button("Apply", variant="primary", id="commit-filter-apply")

    def on_mount(self) -> None:
        self.query_one("#commit-filter-authors", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_apply(self) -> None:
        authors = tuple(
            part.strip()
            for part in self.query_one("#commit-filter-authors", Input).value.split(",")
            if part.strip()
        )
        since_text = self.query_one("#commit-filter-since", Input).value.strip()
        until_text = self.query_one("#commit-filter-until", Input).value.strip()
        limit_text = self.query_one("#commit-filter-limit", Input).value.strip()

        try:
            since = parse_time_bound(since_text) if since_text else None
            until = parse_time_bound(until_text) if until_text else None
        except VcsLogDateError as exc:
            self.notify(str(exc), severity="error")
            return
        try:
            limit = int(limit_text)
        except ValueError:
            self.notify("Limit must be a non-negative integer", severity="error")
            return
        if limit < 0:
            self.notify("Limit must be a non-negative integer", severity="error")
            return
        if since is not None and until is not None and since > until:
            self.notify("Since must not be later than until", severity="error")
            return

        try:
            repos = tuple(
                self.query_one("#commit-filter-repos", SelectionList).selected
            )
        except Exception:
            repos = ()
        self.dismiss(
            CommitLogFilterValues(
                authors=authors,
                since_text=since_text,
                until_text=until_text,
                since=since,
                until=until,
                repos=repos,
                limit=limit,
            )
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "commit-filter-apply":
            self.action_apply()
        elif event.button.id == "commit-filter-cancel":
            self.action_cancel()


__all__ = ["CommitFiltersModal", "CommitLogFilterValues"]
