"""Answer a remote question or approve a remote gate."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Input, OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState

from sase.dispatch.content import (
    RemoteContentChunk,
    RemoteContentClient,
    RemoteContentError,
)

_PREVIEW_GROUP = "remote-attention-preview"


class RemoteAttentionModal(ModalScreen[dict[str, Any] | None]):
    """Show one pending remote question/gate and collect the answer intent.

    Never renders a remote path: the entry carries only opaque locators and
    an optional opaque preview content handle. When a preview handle is
    present, submission stays disabled until that preview loads and its
    digest validates; with no handle to preview, submission is available
    immediately.
    """

    BINDINGS = [
        ("escape", "dismiss_modal", "Cancel"),
        ("q", "dismiss_modal", "Cancel"),
    ]

    def __init__(
        self,
        *,
        alias: str,
        entry: Mapping[str, Any],
        client: RemoteContentClient | None = None,
    ) -> None:
        super().__init__()
        self._alias = alias
        self._entry = dict(entry)
        self._kind = str(entry.get("kind") or "gate")
        self._client = client or RemoteContentClient()
        preview = entry.get("preview")
        self._preview_handle = preview if isinstance(preview, Mapping) else None
        self._preview_ready = self._preview_handle is None
        self._preview_error: str | None = None
        self._preview_text_value = ""
        self._worker: Worker[RemoteContentChunk] | None = None

    def compose(self) -> ComposeResult:
        title = str(self._entry.get("title") or "Remote attention")
        summary = str(self._entry.get("summary") or "")
        age = _observation_age(self._entry.get("observed_at_unix"))
        yield Static(title, id="remote-attention-title")
        yield Static(f"Origin: {self._alias}  Age: {age}", id="remote-attention-meta")
        with VerticalScroll(id="remote-attention-body"):
            if summary:
                yield Static(summary, id="remote-attention-summary")
            if self._kind == "gate":
                option_list = OptionList(id="remote-attention-options")
                options = self._entry.get("options")
                if isinstance(options, list):
                    for option in options:
                        if isinstance(option, Mapping) and option.get("id"):
                            option_list.add_option(
                                Option(
                                    str(option.get("label") or option["id"]),
                                    id=str(option["id"]),
                                )
                            )
                yield option_list
            else:
                yield Input(placeholder="Your answer", id="remote-attention-answer")
            if self._preview_handle is not None:
                yield Static(self._preview_text(), id="remote-attention-preview")
        with Horizontal(id="remote-attention-actions"):
            yield Button(
                "Submit",
                id="remote-attention-submit",
                disabled=not self._preview_ready,
            )
            yield Button("Cancel", id="remote-attention-cancel")

    def on_mount(self) -> None:
        if self._preview_handle is not None:
            self._start_preview_fetch()
        elif self._kind == "gate":
            try:
                self.query_one("#remote-attention-options", OptionList).focus()
            except NoMatches:
                pass
        else:
            try:
                self.query_one("#remote-attention-answer", Input).focus()
            except NoMatches:
                pass

    def on_unmount(self) -> None:
        worker = self._worker
        if worker is not None and not worker.is_finished:
            worker.cancel()

    def _start_preview_fetch(self) -> None:
        handle = self._preview_handle
        if handle is None:
            return
        row_revision = {
            "schema_version": 1,
            "logical_key": self._entry.get("logical_key") or "",
            "revision": self._entry.get("revision") or 0,
        }
        client = self._client
        alias = self._alias
        observed_at = self._entry.get("observed_at_unix")

        def task() -> RemoteContentChunk:
            return client.open_handle(
                handle,
                row_revision=row_revision,
                origin_alias=alias,
                observed_at_unix=(
                    observed_at if isinstance(observed_at, (int, float)) else None
                ),
            )

        run_worker = getattr(self, "run_worker", None)
        if not callable(run_worker):
            try:
                self._apply_preview(task())
            except RemoteContentError as exc:
                self._fail_preview(str(exc))
            return
        self._worker = run_worker(
            task,
            thread=True,
            exclusive=True,
            group=_PREVIEW_GROUP,
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
        self._worker = None
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if isinstance(result, RemoteContentChunk):
                self._apply_preview(result)
            return
        if event.state == WorkerState.ERROR:
            self._fail_preview(str(event.worker.error or "preview fetch failed"))

    def _apply_preview(self, chunk: RemoteContentChunk) -> None:
        self._preview_text_value = chunk.data.decode("utf-8", errors="replace")
        self._preview_ready = True
        self._refresh_preview()

    def _fail_preview(self, message: str) -> None:
        self._preview_error = message
        self._preview_ready = False
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        try:
            self.query_one("#remote-attention-preview", Static).update(
                self._preview_text()
            )
        except NoMatches:
            pass
        try:
            self.query_one(
                "#remote-attention-submit", Button
            ).disabled = not self._preview_ready
        except NoMatches:
            pass

    def _preview_text(self) -> str:
        if self._preview_error:
            return f"Preview failed: {self._preview_error}"
        if self._preview_handle is None:
            return ""
        if not self._preview_ready:
            return "Loading preview…"
        return self._preview_text_value

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "remote-attention-cancel":
            self.dismiss(None)
            return
        if event.button.id == "remote-attention-submit":
            self._submit()

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    def _submit(self) -> None:
        if not self._preview_ready:
            self.notify("Preview must load before submitting", severity="warning")
            return
        if self._kind == "gate":
            self._submit_gate()
            return
        self._submit_question()

    def _submit_gate(self) -> None:
        try:
            option_list = self.query_one("#remote-attention-options", OptionList)
        except NoMatches:
            return
        if option_list.highlighted is None:
            self.notify("Select an option", severity="warning")
            return
        option = option_list.get_option_at_index(option_list.highlighted)
        option_id = str(option.id) if option.id else None
        if not option_id:
            self.notify("Select an option", severity="warning")
            return
        self.dismiss(
            {
                "kind": "gate",
                "selected_option_ids": [option_id],
                "feedback": None,
            }
        )

    def _submit_question(self) -> None:
        try:
            answer_input = self.query_one("#remote-attention-answer", Input)
        except NoMatches:
            return
        answer = answer_input.value.strip()
        if not answer:
            self.notify("Enter an answer", severity="warning")
            return
        self.dismiss(
            {
                "kind": "question",
                "question_choice": "custom",
                "custom_answer": answer,
            }
        )


def _observation_age(observed_at_unix: object) -> str:
    if not isinstance(observed_at_unix, (int, float)):
        return "unknown"
    elapsed = max(0.0, time.time() - float(observed_at_unix))
    if elapsed < 60:
        return f"{int(elapsed)}s"
    if elapsed < 3600:
        return f"{int(elapsed // 60)}m"
    return f"{int(elapsed // 3600)}h"


__all__ = ["RemoteAttentionModal"]
