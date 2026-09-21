"""Rich Live timeline renderer for terminal stderr."""

from __future__ import annotations

import threading
import time

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from rich import box
from rich.console import Console, ConsoleOptions, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from .events import StepStatus
from .render_plain import PlainTimelineRenderer
from .styles import (
    FINAL_GLYPH,
    STATUS_GLYPH,
    STATUS_STYLE,
    format_duration,
    format_span,
)
from .timeline import StepSnapshot, TimelineModel, elapsed, walk

_LIVE_TAIL = 3
"""Live output lines shown under a running step."""

_FAILURE_TAIL = 20
"""Output lines expanded under a failed step in the final frame."""

_VERBOSE_INTERVAL = 0.25
"""Seconds between verbose-line sweeps while the live region is up."""


@dataclass
class _Item:
    """One pre-layout frame line with the metadata budget rules need."""

    kind: str  # "step" | "tail" | "more"
    step_id: str | None
    depth: int
    status: StepStatus = "pending"
    title: str = ""
    detail: str = ""
    tail_line: str = ""
    more_count: int = 0


def _items(snapshot: tuple[StepSnapshot, ...], *, live: bool) -> list[_Item]:
    items: list[_Item] = []
    for depth, row in walk(snapshot):
        items.append(
            _Item(
                kind="step",
                step_id=row.id,
                depth=depth,
                status=row.status,
                title=row.title,
                detail=row.detail or "",
            )
        )
        if live and row.status == "running":
            for tail_line in row.tail[-_LIVE_TAIL:]:
                items.append(
                    _Item(kind="tail", step_id=row.id, depth=depth, tail_line=tail_line)
                )
    return items


class LiveTimelineRenderer:
    """Full-screen-style step timeline in a transient rich Live region.

    The frame is a rounded cyan panel titled ``sase update · <mode>`` with the
    overall elapsed clock as a right-aligned subtitle. Any exception raised
    while building or refreshing a frame degrades the renderer: the Live
    region stops and a plain renderer takes over for the rest of the run, so
    rendering can never fail an update.
    """

    def __init__(
        self,
        console: Console,
        model: TimelineModel,
        *,
        verbose: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Bind to ``console`` and ``model`` without starting Live yet."""
        self._console = console
        self._model = model
        self._verbose = verbose
        self._clock = clock
        self._header_mode = ""
        self._t0: float | None = None
        self._live: Live | None = None
        self._plain: PlainTimelineRenderer | None = None
        self._failed_over = False
        self._seen_tail: dict[str, int] = {}
        self._stop = threading.Event()
        self._watcher: threading.Thread | None = None
        self._verbose_lock = threading.Lock()

    @property
    def degraded(self) -> bool:
        """Return True once frame rendering has failed and plain took over."""
        return self._failed_over

    def set_header(self, mode: str) -> None:
        """Set the install mode shown in the panel title."""
        self._header_mode = mode
        if self._plain is not None:
            self._plain.set_header(mode)

    def header_title(self) -> str:
        """Return the panel title."""
        if self._header_mode:
            return f"sase update · {self._header_mode}"
        return "sase update"

    def __enter__(self) -> LiveTimelineRenderer:
        """Start the transient Live region and the verbose watcher."""
        self._t0 = self._clock()
        self._live = Live(
            self._Frame(self),
            console=self._console,
            transient=True,
            refresh_per_second=10,
        )
        self._live.start()
        if self._verbose:
            self._stop.clear()
            self._watcher = threading.Thread(
                target=self._watch_verbose, name="live-timeline-verbose", daemon=True
            )
            self._watcher.start()
        return self

    def __exit__(self, *exc: object) -> None:
        """Stop the watcher and whichever renderer is active."""
        del exc
        self._stop.set()
        watcher, self._watcher = self._watcher, None
        if watcher is not None and watcher is not threading.current_thread():
            watcher.join(timeout=5.0)
        live, self._live = self._live, None
        if live is not None:
            try:
                live.stop()
            except Exception:  # noqa: BLE001 - progress must never fail a run
                pass
        if self._plain is not None:
            self._plain.detach()

    class _Frame:
        """Zero-arg renderable that degrades the renderer instead of raising."""

        def __init__(self, renderer: LiveTimelineRenderer) -> None:
            self._renderer = renderer

        def __rich_console__(
            self, console: Console, options: ConsoleOptions
        ) -> Iterator[RenderableType]:
            del console, options
            yield self.__rich__()

        def __rich__(self) -> RenderableType:
            try:
                return self._renderer.frame()
            except Exception:  # noqa: BLE001 - reported via degrade, not raised
                self._renderer._fail_over()  # noqa: SLF001 - owned renderable
                return Text("progress unavailable", style="dim")

    def _fail_over(self) -> None:
        self._failed_over = True

    def _switch_if_degraded(self) -> None:
        if not self._failed_over or self._plain is not None:
            return
        live, self._live = self._live, None
        if live is not None:
            try:
                live.stop()
            except Exception:  # noqa: BLE001 - already degraded
                pass
        plain = PlainTimelineRenderer(
            self._console, self._model, verbose=self._verbose, clock=self._clock
        )
        plain.set_header(self._header_mode)
        try:
            plain.attach()
        except Exception:  # noqa: BLE001 - plain ticker is best effort
            pass
        self._plain = plain

    def _watch_verbose(self) -> None:
        while not self._stop.wait(_VERBOSE_INTERVAL):
            try:
                self.poll_verbose()
            except Exception:  # noqa: BLE001 - progress must never fail a run
                pass

    def poll_verbose(self) -> None:
        """Print output lines above the live region (verbose mode only)."""
        self._switch_if_degraded()
        if self._plain is not None:
            self._plain.poll()
            return
        if not self._verbose or self._live is None:
            return
        live = self._live
        with self._verbose_lock:
            rows = walk(self._model.snapshot())
            pending: list[str] = []
            for _depth, row in rows:
                seen = self._seen_tail.get(row.id, 0)
                pending.extend(row.tail[seen:])
                self._seen_tail[row.id] = len(row.tail)
        for line in pending:
            try:
                live.console.print(
                    Text.assemble(("    ", ""), ("│ ", "dim"), Text(line))
                )
            except Exception:  # noqa: BLE001 - degrade instead of failing
                self._fail_over()
                return

    def frame(self) -> Panel:
        """Build the current live frame."""
        snapshot = self._model.snapshot()
        now = self._clock()
        table = self._render_items(
            self._fit_items(_items(snapshot, live=True)), snapshot, now, live=True
        )
        return self._panel(table, now)

    def print_final(self, *, expand_failures: bool = True) -> None:
        """Print the static final frame: no spinner, no tails, failures expanded."""
        self._switch_if_degraded()
        if self._plain is not None:
            self._plain.print_final()
            return
        try:
            snapshot = self._model.snapshot()
            now = self._clock()
            items = _items(snapshot, live=False)
            if expand_failures:
                items = self._expand_failures(items, snapshot)
            table = self._render_items(items, snapshot, now, live=False)
            self._console.print(self._panel(table, now))
            footer = self._slowest_footer(snapshot, now)
            if footer is not None:
                self._console.print(footer)
        except Exception:  # noqa: BLE001 - degrade instead of failing
            self._fail_over()
            self._switch_if_degraded()
            if self._plain is not None:
                self._plain.print_final()

    def _panel(self, table: Table, now: float) -> Panel:
        t0 = self._t0 if self._t0 is not None else now
        return Panel(
            table,
            box=box.ROUNDED,
            border_style="cyan",
            title=self.header_title(),
            subtitle=format_span(now - t0),
            subtitle_align="right",
        )

    def _table(self) -> Table:
        table = Table(box=None, show_header=False, pad_edge=False, expand=True)
        table.add_column("glyph", width=2, no_wrap=True)
        # Capped so result details fit the 80-column target frame; longer
        # titles ellipsize instead of squeezing the detail column.
        table.add_column("title", no_wrap=True, overflow="ellipsis", max_width=28)
        table.add_column("detail", ratio=1, no_wrap=True, overflow="ellipsis")
        table.add_column("duration", justify="right", no_wrap=True)
        return table

    def _render_items(
        self,
        items: list[_Item],
        snapshot: tuple[StepSnapshot, ...],
        now: float,
        *,
        live: bool,
    ) -> Table:
        by_id = {row.id: row for _depth, row in walk(snapshot)}
        table = self._table()
        for item in items:
            if item.kind == "tail":
                tail = Text.assemble(
                    ("    " * item.depth + "    ", ""),
                    ("│ ", "dim"),
                    Text(item.tail_line),
                )
                table.add_row(Text(""), tail, Text(""), Text(""))
            elif item.kind == "more":
                table.add_row(
                    Text(""),
                    Text(f"{'    ' * item.depth}+{item.more_count} more", style="dim"),
                    Text(""),
                    Text(""),
                )
            else:
                row = by_id.get(item.step_id or "")
                table.add_row(
                    self._glyph(item, live=live),
                    Text("    " * item.depth + item.title),
                    Text(item.detail, style="dim"),
                    Text(
                        format_duration(elapsed(row, now))
                        if row is not None and row.started_at is not None
                        else "",
                        style="dim",
                    ),
                )
        return table

    def _glyph(self, item: _Item, *, live: bool) -> RenderableType:
        if live and item.status == "running":
            return Spinner("dots", style="cyan")
        glyphs = STATUS_GLYPH if live else FINAL_GLYPH
        return Text(glyphs[item.status], style=STATUS_STYLE[item.status])

    def _fit_items(self, items: list[_Item]) -> list[_Item]:
        budget = self._row_budget()
        if len(items) <= budget:
            return items
        collapsed = self._collapse_finished_children(items)
        if len(collapsed) <= budget:
            return collapsed
        without_tails = [item for item in collapsed if item.kind != "tail"]
        if len(without_tails) <= budget:
            return without_tails
        return self._keep_visible(without_tails, budget)

    def _row_budget(self) -> int:
        try:
            height = self._console.height
        except Exception:  # noqa: BLE001 - fall back to a sane default
            height = None
        return max(1, (height or 25) - 2)

    def _collapse_finished_children(self, items: list[_Item]) -> list[_Item]:
        snapshot = self._model.snapshot()
        collapsible: dict[str, int] = {}
        for _depth, row in walk(snapshot):
            if row.status in ("done", "warned", "skipped", "failed"):
                finished = [
                    child.id
                    for child in row.children
                    if child.status in ("done", "warned", "skipped")
                ]
                if finished:
                    collapsible[row.id] = len(finished)
        if not collapsible:
            return items
        depths = {row.id: depth for depth, row in walk(snapshot)}
        hidden = {
            child.id
            for _depth, row in walk(snapshot)
            if row.id in collapsible
            for child in row.children
            if child.status in ("done", "warned", "skipped")
        }
        out: list[_Item] = []
        emitted: set[str] = set()
        for item in items:
            if item.kind == "step" and item.step_id in hidden:
                parent = self._parent_of(item.step_id)
                if parent is not None and parent not in emitted:
                    emitted.add(parent)
                    out.append(
                        _Item(
                            kind="more",
                            step_id=parent,
                            depth=depths.get(parent, 0) + 1,
                            more_count=collapsible[parent],
                        )
                    )
                continue
            if item.kind == "tail" and item.step_id in hidden:
                continue
            out.append(item)
        return out

    def _parent_of(self, step_id: str) -> str | None:
        for _depth, row in walk(self._model.snapshot()):
            if any(child.id == step_id for child in row.children):
                return row.id
        return None

    def _keep_visible(self, items: list[_Item], budget: int) -> list[_Item]:
        """Last-resort truncation that never hides the running step or failures."""
        if budget <= 0:
            return []
        if len(items) <= budget:
            return items
        by_id = {row.id: row for _depth, row in walk(self._model.snapshot())}

        def pinned(item: _Item) -> bool:
            if item.kind != "step" or item.step_id is None:
                return False
            row = by_id.get(item.step_id)
            return row is not None and row.status in ("running", "failed")

        keep = {i for i, item in enumerate(items) if pinned(item)}
        for i in range(len(items) - 1, -1, -1):
            if len(keep) >= budget:
                break
            keep.add(i)
        return [item for i, item in enumerate(items) if i in keep]

    def _expand_failures(
        self, items: list[_Item], snapshot: tuple[StepSnapshot, ...]
    ) -> list[_Item]:
        tails = {
            row.id: row for _depth, row in walk(snapshot) if row.status == "failed"
        }
        if not tails:
            return items
        depths = {row.id: depth for depth, row in walk(snapshot)}
        out: list[_Item] = []
        for item in items:
            out.append(item)
            if (
                item.kind == "step"
                and item.step_id in tails
                and item.status == "failed"
            ):
                depth = depths.get(item.step_id or "", 0)
                for tail_line in tails[item.step_id or ""].tail[-_FAILURE_TAIL:]:
                    out.append(
                        _Item(
                            kind="tail",
                            step_id=item.step_id,
                            depth=depth,
                            tail_line=tail_line,
                        )
                    )
        return out

    def _slowest_footer(
        self, snapshot: tuple[StepSnapshot, ...], now: float
    ) -> Text | None:
        ran = [
            row
            for _depth, row in walk(snapshot)
            if row.started_at is not None and row.ended_at is not None
        ]
        if len(ran) <= 1:
            return None
        slowest = max(ran, key=lambda row: elapsed(row, now))
        return Text(
            f"slowest: {slowest.title} ({format_duration(elapsed(slowest, now))})",
            style="dim",
        )
