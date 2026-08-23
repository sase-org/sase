"""Live inline-filter session behavior for the Admin Center Procs pane."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.query.limit_token import LimitTokenError, apply_limit, extract_limit
from sase.ace.tui._proc_query import ProcQueryFilter, ProfileQueryError
from sase.core.time import local_now

from ..proc_observer import ObservedProc
from .procs_filter_bar import ProcsFilterBar

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
    from textual.widgets import OptionList
else:
    _MixinBase = object

#: Errors a hand-typed query can raise: a bad dialect term or a bad
#: host-owned ``limit:`` token. Both carry a ``.message`` the bar renders.
_QueryError = (ProfileQueryError, LimitTokenError)


class ProcsPaneFilterMixin(_MixinBase):
    """Own the Procs pane's committed/live filter query and its matches."""

    if TYPE_CHECKING:
        # Loosely typed to match the other Procs mixins' declarations;
        # narrower attributes (like ``.query``) go through an ignore comment.
        _session_state: object
        _tasks: list[ObservedProc]

        def _option_list(self) -> OptionList | None: ...

        def _refresh_snapshot(
            self,
            *,
            highlight_index: int | None = None,
            prior_identity: str | None = None,
        ) -> None: ...

        def _restore_target(self) -> tuple[str | None, int | None]: ...

    def _init_procs_filter_session(self) -> None:
        self._query_filter = ProcQueryFilter()
        self._filter_query: str = self._session_state.query  # type: ignore[attr-defined]
        self._filter_session_open = False
        self._filter_restore_query: str | None = None
        self._live_filter_query: str | None = None
        self._filter_scoped_total = 0
        self._filter_truncated = False

    def show_filters(self) -> None:
        """Open and focus the inline Procs filter bar."""
        bar = self.query_one(ProcsFilterBar)
        if self._filter_session_open:
            bar.focus_editor()
            return
        self._filter_session_open = True
        self._filter_restore_query = self._filter_query
        self._live_filter_query = self._filter_query
        bar.open(self._filter_query)

    def action_focus_filter(self) -> None:
        """Reveal (or refocus) the Procs filter bar."""
        self.show_filters()

    def _sync_filter_bar(self) -> None:
        """Reflect a query persisted from a prior session in the bar's rest state."""
        self.query_one(ProcsFilterBar).set_query(self._filter_query)

    def consume_priority_tab(self) -> bool:
        """Let the filter bar's own completion menu claim ``Tab`` first."""
        return self.query_one(ProcsFilterBar).has_highlighted_completion()

    def on_procs_filter_bar_query_changed(
        self, event: ProcsFilterBar.QueryChanged
    ) -> None:
        event.stop()
        try:
            self._query_filter.parse(event.text)
        except _QueryError as exc:
            self.query_one(ProcsFilterBar).set_status(None, exact=False, error=exc)
            return
        self._live_filter_query = event.text
        prior_identity, highlighted = self._restore_target()
        self._refresh_snapshot(
            highlight_index=highlighted, prior_identity=prior_identity
        )
        self._report_filter_status()

    def on_procs_filter_bar_submitted(self, event: ProcsFilterBar.Submitted) -> None:
        event.stop()
        try:
            self._query_filter.parse(event.text)
        except _QueryError as exc:
            self.query_one(ProcsFilterBar).set_status(None, exact=False, error=exc)
            self.notify(getattr(exc, "message", str(exc)), severity="error")
            return
        self._commit_filter_query(event.text)
        self._close_filter_session()
        self._focus_task_list()

    def on_procs_filter_bar_dismissed(self, event: ProcsFilterBar.Dismissed) -> None:
        event.stop()
        restore = self._filter_restore_query
        self._close_filter_session()
        if restore is not None:
            self._commit_filter_query(restore)
        self._focus_task_list()

    def _commit_filter_query(self, query: str) -> None:
        self._filter_query = query
        self._session_state.query = query  # type: ignore[attr-defined]
        prior_identity, highlighted = self._restore_target()
        self._refresh_snapshot(
            highlight_index=highlighted, prior_identity=prior_identity
        )
        self._report_filter_status()

    def _close_filter_session(self) -> None:
        self.query_one(ProcsFilterBar).close()
        self._filter_session_open = False
        self._filter_restore_query = None
        self._live_filter_query = None

    def _focus_task_list(self) -> None:
        option_list = self._option_list()
        if option_list is not None:
            option_list.focus()

    def _display_filter_query(self) -> str:
        """Return the query currently governing the rendered rows."""
        if self._filter_session_open and self._live_filter_query is not None:
            return self._live_filter_query
        return self._filter_query

    def _merged_tasks(self) -> list[ObservedProc]:
        scoped = super()._merged_tasks()  # type: ignore[misc]
        return self._filtered_tasks(scoped)

    def _filtered_tasks(self, rows: list[ObservedProc]) -> list[ObservedProc]:
        """Apply the active query, then the ``limit:`` cap, to *rows*."""
        self._filter_scoped_total = len(rows)
        query = self._display_filter_query()
        if not query.strip():
            self._filter_truncated = False
            return rows
        try:
            matched = self._query_filter.matching(query, rows, now=local_now())
            cap = extract_limit(query)[1]
        except _QueryError:
            # A parse failure is already reported by the query-changed
            # handler, which never reaches here; a stale committed query
            # falls back to the unfiltered scope rather than blanking rows.
            self._filter_truncated = False
            return rows
        capped, truncated = apply_limit(matched, cap)
        self._filter_truncated = truncated
        return list(capped)

    def _report_filter_status(self) -> None:
        bar = self.query_one(ProcsFilterBar)
        if not self._display_filter_query().strip():
            bar.clear_status()
            return
        truncated = self._filter_truncated
        bar.set_status(
            len(self._tasks),
            exact=not truncated,
            error=None,
            coverage_label="capped" if truncated else None,
            lower_bound=truncated,
        )


__all__ = ["ProcsPaneFilterMixin"]
