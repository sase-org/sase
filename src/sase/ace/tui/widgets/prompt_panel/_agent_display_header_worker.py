"""App-owned, single-flight worker for selected-agent header enrichment."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Event, RLock
from time import monotonic
from typing import TYPE_CHECKING, Any, cast
import weakref

if TYPE_CHECKING:
    from ._agent_display_async_types import DetailHeaderEnrichmentRequest
    from ._agent_display_state import DetailHeaderSummary

_HEADER_ENRICHMENT_DRAIN_TIMEOUT_SECONDS = 2.0

_HEADER_ENRICHMENT_SERVICE_CACHE: dict[
    int, weakref.ref[_AgentDetailHeaderEnrichmentService]
] = {}
_HEADER_ENRICHMENT_SERVICE_CACHE_LOCK = RLock()


@dataclass
class _HeaderEnrichmentJob:
    panel: object
    request: DetailHeaderEnrichmentRequest
    lanes: frozenset[Any]
    cancelled: Event = field(default_factory=Event)
    suppress_display: Event = field(default_factory=Event)


def _remember_live_service(service: _AgentDetailHeaderEnrichmentService) -> None:
    _live_services()
    ident = id(service)

    def _drop(
        _ref: weakref.ref[_AgentDetailHeaderEnrichmentService],
        *,
        key: int = ident,
    ) -> None:
        with _HEADER_ENRICHMENT_SERVICE_CACHE_LOCK:
            _HEADER_ENRICHMENT_SERVICE_CACHE.pop(key, None)

    with _HEADER_ENRICHMENT_SERVICE_CACHE_LOCK:
        _HEADER_ENRICHMENT_SERVICE_CACHE[ident] = weakref.ref(service, _drop)


def _forget_live_service(service: _AgentDetailHeaderEnrichmentService) -> None:
    with _HEADER_ENRICHMENT_SERVICE_CACHE_LOCK:
        _HEADER_ENRICHMENT_SERVICE_CACHE.pop(id(service), None)


def _live_services() -> list[_AgentDetailHeaderEnrichmentService]:
    with _HEADER_ENRICHMENT_SERVICE_CACHE_LOCK:
        live: list[_AgentDetailHeaderEnrichmentService] = []
        stale: list[int] = []
        for ident, ref in _HEADER_ENRICHMENT_SERVICE_CACHE.items():
            service = ref()
            if service is None:
                stale.append(ident)
                continue
            live.append(service)
        for ident in stale:
            _HEADER_ENRICHMENT_SERVICE_CACHE.pop(ident, None)
        return live


class _AgentDetailHeaderEnrichmentService:
    """Run at most one header compute and retain only the latest pending request.

    The service is created lazily on the Textual app. A cancelled synchronous
    lane is allowed to finish, but the worker checks its cancellation event
    between lanes and never starts another compute until that lane exits.

    ``shutdown`` is nonblocking and keeps the in-flight future so a later
    ``drain`` can wait for the resolver to exit. Production unmount uses
    shutdown only; tests drain before invalidating config.
    """

    def __init__(self, app: object) -> None:
        self._app = app
        self._lock = RLock()
        self._executor: ThreadPoolExecutor | None = None
        self._active: _HeaderEnrichmentJob | None = None
        self._pending: _HeaderEnrichmentJob | None = None
        self._future: Future[object] | None = None
        self._closed = False
        self._draining = False
        _remember_live_service(self)

    @property
    def is_running(self) -> bool:
        """Match Textual worker state for the app's finite-work observers."""
        return self._active is not None or self._pending is not None

    def submit(self, panel: object, request: DetailHeaderEnrichmentRequest) -> None:
        with self._lock:
            if self._closed or self._draining:
                return
            active = self._active
            if (
                active is not None
                and not active.cancelled.is_set()
                and active.panel is panel
                and active.request.agent is request.agent
                and active.lanes == request.lanes
                and active.request.attempt_view_mode == request.attempt_view_mode
                and active.request.attempt_pinned_number
                == request.attempt_pinned_number
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
                and pending.request.attempt_pinned_number
                == request.attempt_pinned_number
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
        with self._lock:
            active = self._active
            if active is not None and active.panel is panel:
                if (
                    keep_identity is None
                    or active.request.agent_identity != keep_identity
                ):
                    active.cancelled.set()
                    if keep_identity is None:
                        active.suppress_display.set()
            pending = self._pending
            if pending is not None and pending.panel is panel:
                if (
                    keep_identity is None
                    or pending.request.agent_identity != keep_identity
                ):
                    self._pending = None

    def shutdown(self) -> None:
        """Stop accepting work, discard pending selection, and detach the pool.

        Already-running compute keeps its future so ``drain`` can wait. The
        method is idempotent and never joins the resolver; the Textual event
        loop must not block on worker completion.
        """
        with self._lock:
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

    def drain(
        self, *, timeout: float = _HEADER_ENRICHMENT_DRAIN_TIMEOUT_SECONDS
    ) -> None:
        """Wait for in-flight compute to exit without permanently closing.

        Drops pending work and suppresses late UI publication. A timeout
        keeps the live future registered and raises rather than pretending
        the resolver finished. Shared apps can submit again after a
        successful drain; a closed service stays closed.
        """
        deadline = monotonic() + timeout
        with self._lock:
            self._draining = True
            self._pending = None
            active = self._active
            if active is not None:
                active.cancelled.set()
                active.suppress_display.set()
            future = self._future
        closed = False
        in_flight = future is not None
        try:
            if future is not None:
                remaining = max(0.0, deadline - monotonic())
                try:
                    future.result(timeout=remaining)
                except TimeoutError:
                    raise RuntimeError(
                        "sase-agent-detail-header worker did not exit "
                        f"within {timeout}s; leaving the live future registered"
                    ) from None
                except Exception:
                    pass
            with self._lock:
                if self._future is future:
                    self._future = None
                if not self._closed:
                    self._active = None
                closed = self._closed
                in_flight = self._future is not None
        finally:
            with self._lock:
                self._draining = False
        if closed and not in_flight:
            _forget_live_service(self)

    def _start(self, job: _HeaderEnrichmentJob) -> None:
        with self._lock:
            if self._closed or self._draining:
                return
            self._active = job
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="sase-agent-detail-header",
                )
            try:
                self._future = self._executor.submit(self._compute, job)
            except RuntimeError:
                self._active = None
                self._future = None

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
            # Void UI callbacks must not block the worker. Drain can join the
            # future while the message loop is stopped or is itself waiting
            # for that join; ``call_from_thread`` would deadlock there.
            call_later = getattr(self._app, "call_later", None)
            if callable(call_later):
                call_later(callback, *args)
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
        with self._lock:
            if self._closed or self._draining or self._active is not job:
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
        with self._lock:
            if self._active is not job:
                return
            should_finish = (
                not self._closed
                and not self._draining
                and not job.suppress_display.is_set()
            )
            self._active = None
            pending = None if (self._closed or self._draining) else self._pending
            if pending is not None:
                self._pending = None
        if should_finish:
            finish = getattr(job.panel, "_finish_detail_header_summary", None)
            if callable(finish):
                finish(job.request, summary, error)
        if pending is not None:
            self._start(pending)

    def _start_pending(self) -> None:
        with self._lock:
            if self._closed or self._draining or self._active is not None:
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
    if isinstance(service, _AgentDetailHeaderEnrichmentService) and not service._closed:
        return service
    if (
        isinstance(service, _AgentDetailHeaderEnrichmentService)
        and service._closed
        and not getattr(app, "is_running", False)
    ):
        return None
    service = _AgentDetailHeaderEnrichmentService(app)
    app._agent_detail_header_enrichment_service = service  # type: ignore[attr-defined]
    return service


def shutdown_app_header_enrichment_service(app: object) -> None:
    """Shut down the app's worker if it was created."""
    service = getattr(app, "_agent_detail_header_enrichment_service", None)
    if service is not None:
        service.shutdown()


__all__ = [
    "app_header_enrichment_service",
    "shutdown_app_header_enrichment_service",
]
