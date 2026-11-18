"""App-owned, single-flight worker for selected-agent header enrichment."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Event
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from ._agent_display_async_types import DetailHeaderEnrichmentRequest
    from ._agent_display_state import DetailHeaderSummary


@dataclass
class _HeaderEnrichmentJob:
    panel: object
    request: DetailHeaderEnrichmentRequest
    lanes: frozenset[Any]
    cancelled: Event = field(default_factory=Event)
    suppress_display: Event = field(default_factory=Event)


class _AgentDetailHeaderEnrichmentService:
    """Run at most one header compute and retain only the latest pending request.

    The service is created lazily on the Textual app. A cancelled synchronous
    lane is allowed to finish, but the worker checks its cancellation event
    between lanes and never starts another compute until that lane exits.
    """

    def __init__(self, app: object) -> None:
        self._app = app
        self._executor: ThreadPoolExecutor | None = None
        self._active: _HeaderEnrichmentJob | None = None
        self._pending: _HeaderEnrichmentJob | None = None
        self._closed = False

    @property
    def is_running(self) -> bool:
        """Match Textual worker state for the app's finite-work observers."""
        return self._active is not None or self._pending is not None

    def submit(self, panel: object, request: DetailHeaderEnrichmentRequest) -> None:
        if self._closed:
            return
        active = self._active
        if (
            active is not None
            and not active.cancelled.is_set()
            and active.panel is panel
            and active.request.agent is request.agent
            and active.lanes == request.lanes
            and active.request.attempt_view_mode == request.attempt_view_mode
            and active.request.attempt_pinned_number == request.attempt_pinned_number
        ):
            active.request = request
            return

        pending = self._pending
        if (
            pending is not None
            and pending.panel is panel
            and pending.request.agent is request.agent
            and pending.lanes == request.lanes
            and pending.request.attempt_view_mode == request.attempt_view_mode
            and pending.request.attempt_pinned_number == request.attempt_pinned_number
        ):
            pending.request = request
            return

        job = _HeaderEnrichmentJob(panel, request, request.lanes)
        if active is None:
            self._start(job)
            return

        # Textual cancellation cannot stop Python code already running in a
        # thread. Signal it cooperatively, then replace the sole waiting slot.
        active.cancelled.set()
        self._pending = job

    def cancel(self, panel: object, *, keep_identity: tuple[Any, ...] | None) -> None:
        active = self._active
        if active is not None and active.panel is panel:
            if keep_identity is None or active.request.agent_identity != keep_identity:
                active.cancelled.set()
                if keep_identity is None:
                    active.suppress_display.set()
        pending = self._pending
        if pending is not None and pending.panel is panel:
            if keep_identity is None or pending.request.agent_identity != keep_identity:
                self._pending = None

    def shutdown(self) -> None:
        """Stop accepting work, discard pending selection, and detach the pool."""
        if self._closed:
            return
        self._closed = True
        self._pending = None
        active = self._active
        if active is not None:
            active.cancelled.set()
            active.suppress_display.set()
        self._active = None
        executor = self._executor
        self._executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def _start(self, job: _HeaderEnrichmentJob) -> None:
        self._active = job
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="sase-agent-detail-header",
            )
        try:
            self._executor.submit(self._compute, job)
        except RuntimeError:
            self._active = None
            self._start_pending()

    def _compute(self, job: _HeaderEnrichmentJob) -> object:
        try:
            build = cast(Any, job.panel)._build_detail_header_summary

            def publish(summary: DetailHeaderSummary) -> None:
                self._call_from_worker(self._publish_on_ui, job, summary)

            summary = build(
                job.request.agent,
                lanes=job.lanes,
                should_continue=lambda: not job.cancelled.is_set(),
                publish=publish,
            )
            error: BaseException | None = None
        except BaseException as exc:  # noqa: BLE001 - reported on the UI thread
            summary = None
            error = exc
        self._call_from_worker(self._finish_on_ui, job, summary, error)
        return summary

    def _call_from_worker(self, callback: Any, *args: object) -> None:
        try:
            loop = getattr(self._app, "_loop", None)
            if loop is not None and not loop.is_running():
                return
            call_from_thread = getattr(self._app, "call_from_thread", None)
            if not callable(call_from_thread):
                return
            call_from_thread(callback, *args)
        except Exception:
            # App teardown may close the message loop before a synchronous
            # resolver finishes. It must not try to paint a dead widget.
            return

    def _publish_on_ui(
        self, job: _HeaderEnrichmentJob, summary: DetailHeaderSummary
    ) -> None:
        if self._closed or self._active is not job:
            return
        if job.suppress_display.is_set():
            return
        publish = getattr(job.panel, "_publish_detail_header_summary", None)
        if callable(publish):
            publish(job.request, summary)

    def _finish_on_ui(
        self,
        job: _HeaderEnrichmentJob,
        summary: object,
        error: BaseException | None,
    ) -> None:
        if self._active is not job:
            return
        if not self._closed and not job.suppress_display.is_set():
            finish = getattr(job.panel, "_finish_detail_header_summary", None)
            if callable(finish):
                finish(job.request, summary, error)
        self._active = None
        self._start_pending()

    def _start_pending(self) -> None:
        if self._closed or self._active is not None:
            return
        pending = self._pending
        self._pending = None
        if pending is not None:
            self._start(pending)


def app_header_enrichment_service(
    widget: object,
) -> _AgentDetailHeaderEnrichmentService | None:
    """Get the lazy app-owned service, or ``None`` for mixin-only test doubles."""
    try:
        app = widget.app  # type: ignore[attr-defined]
    except Exception:
        return None
    try:
        from textual.app import App

        if not isinstance(app, App):
            return None
    except Exception:
        return None
    service = getattr(app, "_agent_detail_header_enrichment_service", None)
    if service is None:
        service = _AgentDetailHeaderEnrichmentService(app)
        app._agent_detail_header_enrichment_service = service  # type: ignore[attr-defined]
    return service


def shutdown_app_header_enrichment_service(app: object) -> None:
    """Shut down the app's worker if it was created."""
    service = getattr(app, "_agent_detail_header_enrichment_service", None)
    if service is not None:
        service.shutdown()
