"""Bounded remote content viewer with origin, age, and load-more."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Static
from textual.worker import Worker, WorkerState

from sase.dispatch.content import (
    RemoteContentChunk,
    RemoteContentClient,
    RemoteContentError,
)

_CONTENT_GROUP = "remote-content"


class RemoteContentModal(ModalScreen[None]):
    """Show one remote content range and optionally extend a growing tail."""

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("q", "dismiss", "Close"),
        ("m", "load_more", "Load more"),
    ]

    def __init__(
        self,
        *,
        title: str,
        origin: str,
        age: str,
        handle: Mapping[str, Any],
        row_revision: Mapping[str, Any],
        client: RemoteContentClient,
        chunk: RemoteContentChunk | None = None,
        observed_at_unix: float | None = None,
    ) -> None:
        super().__init__()
        self._title = title
        self._origin = origin
        self._age = age
        self._handle = dict(handle)
        self._row_revision = dict(row_revision)
        self._chunk = chunk
        self._client = client
        self._observed_at_unix = observed_at_unix
        self._parts = (
            [] if chunk is None else [chunk.data.decode("utf-8", errors="replace")]
        )
        self._loading = False
        self._worker: Worker[RemoteContentChunk] | None = None
        self._load_more_pending = False

    def compose(self) -> ComposeResult:
        yield Static(self._title, id="remote-content-title")
        yield Static(
            f"Origin: {self._origin}  Age: {self._age}", id="remote-content-meta"
        )
        with VerticalScroll(id="remote-content-body"):
            yield Static(self._body_text(), id="remote-content-text")
        with Horizontal(id="remote-content-actions"):
            yield Button("Load more", id="remote-content-more")
            yield Button("Close", id="remote-content-close")

    def on_mount(self) -> None:
        if self._chunk is None:
            self._start_fetch(load_more=False)

    def on_unmount(self) -> None:
        worker = self._worker
        if worker is not None and not worker.is_finished:
            worker.cancel()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "remote-content-close":
            self.dismiss(None)
            return
        if event.button.id == "remote-content-more":
            self.action_load_more()

    def action_load_more(self) -> None:
        if self._chunk is None:
            return
        self._start_fetch(load_more=True)

    def _start_fetch(self, *, load_more: bool) -> None:
        if self._loading:
            return
        self._loading = True
        self._load_more_pending = load_more
        self._set_body(self._body_text())
        client = self._client
        handle = self._handle
        revision = self._row_revision
        origin = self._origin
        observed_at = self._observed_at_unix
        previous = self._chunk

        def task() -> RemoteContentChunk:
            if load_more and previous is not None:
                return client.continue_tail(
                    previous,
                    handle,
                    row_revision=revision,
                )
            return client.open_handle(
                handle,
                row_revision=revision,
                origin_alias=origin,
                observed_at_unix=observed_at,
            )

        run_worker = getattr(self, "run_worker", None)
        if not callable(run_worker):
            try:
                self._apply_chunk(task(), load_more=load_more)
            except RemoteContentError as exc:
                self.notify(str(exc), severity="error")
            finally:
                self._loading = False
            return
        self._worker = run_worker(
            task,
            thread=True,
            exclusive=True,
            group=_CONTENT_GROUP,
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._worker:
            return
        if event.state not in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            return
        load_more = self._load_more_pending
        self._worker = None
        self._loading = False
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if isinstance(result, RemoteContentChunk):
                self._apply_chunk(result, load_more=load_more)
            return
        if event.state == WorkerState.ERROR:
            error = event.worker.error
            self.notify(str(error or "remote content read failed"), severity="error")

    def _apply_chunk(self, chunk: RemoteContentChunk, *, load_more: bool) -> None:
        extra = chunk.data.decode("utf-8", errors="replace")
        if load_more:
            if extra:
                self._parts.append(extra)
        else:
            self._parts = [extra] if extra else []
        self._chunk = chunk
        self._set_body(self._body_text())
        if load_more and extra == "" and chunk.eof and not chunk.supports_growth:
            self.notify("End of remote content")

    def _body_text(self) -> str:
        if self._loading and not self._parts:
            return "Loading…"
        return "".join(self._parts) or " "

    def _set_body(self, text: str) -> None:
        try:
            self.query_one("#remote-content-text", Static).update(text)
        except NoMatches:
            return
