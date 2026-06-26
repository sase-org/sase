"""Read-only Plugins browser pane for the Config Center modal.

This widget hosts the **Plugins** tab of :class:`ConfigCenterModal`: a
master/detail layout (mirroring the XPrompts tab) that brings the
``sase plugin list`` *and* ``sase plugin show`` experience into the TUI.
Phase 2 built the read-only list browse — a header summary line, a filter
input, a grouped ``OptionList`` split into Built-in / Community sections
with CLI-matching status glyphs. Phase 3 fills in the right-hand detail
panel and the read-side affordances:

- the ``show``-equivalent detail panel, built from the promoted, console-free
  Rich renderables (:func:`sase.plugins.render.build_detail_panel` and
  :func:`~sase.plugins.render.build_community_warning_panel`) so the TUI and
  ``sase plugin show`` are visually identical. The detail follows the
  highlighted row, debounced (:class:`DetailPanelDebouncer`) so a held
  ``j``/``k`` paints exactly one final detail while the highlight stays
  instant;
- ``r`` refresh (refetch catalog + latest versions), ``o`` offline toggle
  (with a header badge), and ``v`` verbose toggle (stars / updated columns on
  the list rows; the detail panel always shows the full metadata);
- live header summary counts plus a warnings / stale-cache hint.

Phase 4 adds the **install** action (``i``, offered only for a not-installed
plugin). It plans the install off-thread with
:func:`sase.plugins.operations.plan_install` (index *and* git source), opens the
reusable :class:`~sase.ace.tui.modals.plugin_action_confirm_modal.PluginActionConfirmModal`
showing the exact ``uv`` argv (the confirmation *is* the dry-run), then runs
:func:`~sase.plugins.operations.execute_install` inside a tracked background
task so a multi-second ``uv`` run never blocks the UI; a success/error toast and
an automatic cache-first refresh follow. A one-shot ``probe_uv_tool_install``
(carried with each load) disables the action and explains why when sase is not a
managed ``uv tool install sase``; already-installed and not-found outcomes reuse
the CLI's resolution so the messaging matches.

Phase 5 adds the **update** actions, reusing Phase 4's confirm-preview modal and
tracked-task pattern. ``u`` updates the highlighted plugin (offered only when it
is installed; emphasized when an update is available) and ``U`` updates every
installed plugin at once. Both plan off-thread with
:func:`sase.plugins.operations.plan_update`, route the terminal outcomes
(:class:`~sase.plugins.operations.NotUvTool`,
:class:`~sase.plugins.operations.NoPlugins`,
:class:`~sase.plugins.operations.NotInstalled`,
:class:`~sase.plugins.operations.UpdateUnknown`) to CLI-matching toasts, preview
the exact ``uv`` upgrade argv, then run
:func:`~sase.plugins.operations.execute_update` inside a tracked background task
followed by a success/error toast and an automatic cache-first refresh.

The catalog loads cache-first off the event loop (``run_worker(thread=True)``)
so a slow ``gh`` / network call never blocks the UI; loading, empty, and error
states are surfaced in place. This pane intentionally reuses the same single
source of truth as the CLI (:func:`sase.plugins.catalog.load_plugin_catalog`,
:func:`sase.plugins.latest.enrich_with_latest`, the
:mod:`sase.plugins.operations` plan/execute layer, and the promoted renderables)
so the TUI and the CLI never drift.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

from rich.console import Group, RenderableType
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState

from sase.ace.tui.actions.task_actions import (
    TrackedTaskCompletion,
    TrackedTaskResult,
)
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.plugins.catalog import (
    PluginCatalog,
    PluginCatalogEntry,
    PluginCatalogError,
    load_plugin_catalog,
)
from sase.plugins.latest import enrich_with_latest
from sase.plugins.operations import (
    AlreadyInstalled,
    InstallNotFound,
    InstallOutcome,
    InstallPlan,
    InstallReady,
    NoPlugins,
    NotInstalled,
    NotUvTool,
    UpdateOutcome,
    UpdatePlan,
    UpdateReady,
    UpdateUnknown,
    execute_install,
    execute_update,
    plan_install,
    plan_update,
)
from sase.plugins.render import build_community_warning_panel, build_detail_panel
from sase.plugins.render_common import (
    _AVAILABLE_GLYPH,
    _COMMUNITY_STYLE,
    _INSTALLED_GLYPH,
    _UPDATE_GLYPH,
    humanize_age,
    humanize_duration,
)
from sase.uv_tool.detect import (
    NotUvToolInstall,
    UvToolInstall,
    probe_uv_tool_install,
)
from sase.uv_tool.errors import NotAUvToolInstallError, ReceiptError, UvToolError
from sase.uv_tool.runner import ChangeKind

from .plugin_action_confirm_modal import (
    PluginActionConfirmModal,
    PluginActionConfirmResult,
    PluginActionVariant,
)

#: Right-panel placeholder shown until a plugin row is highlighted.
_DETAIL_PLACEHOLDER = "Select a plugin to view its details."

_BUILTIN_GROUP = "Built-in"
_COMMUNITY_GROUP = "Community"

_HEADER_PREFIX = "__header__"
_ITEM_PREFIX = "plugin__"


@dataclass(frozen=True)
class _PluginsLoadResult:
    """Outcome of a (possibly cache-first) plugin catalog load.

    *uv_tool* is the one-shot ``probe_uv_tool_install`` result carried alongside
    the catalog so the pane learns, off-thread, whether install/update mutations
    are even possible (a managed ``uv tool install sase``). ``None`` means the
    probe was not run (e.g. a stubbed loader in tests); the pane keeps whatever
    it already detected.
    """

    catalog: PluginCatalog | None
    error: str | None
    now: float
    uv_tool: UvToolInstall | NotUvToolInstall | None = None


def _probe_uv_tool() -> UvToolInstall | NotUvToolInstall | None:
    """Best-effort uv-tool probe; never raises (mutations gate on it only)."""
    try:
        return probe_uv_tool_install()
    except Exception:  # noqa: BLE001 - a probe failure must not break browsing.
        return None


def _load_plugins_catalog(
    *,
    refresh: bool = False,
    offline: bool = False,
    now: float | None = None,
) -> _PluginsLoadResult:
    """Load the plugin catalog (merged with installed + latest). Off-thread safe.

    Mirrors ``sase plugin list``: cache-first by default, then a best-effort
    latest-version enrichment so the update markers/counts match the CLI. A
    hard catalog failure (e.g. a missing ``gh``) becomes the pane's error
    state; an enrichment failure degrades to the un-enriched catalog. The
    uv-tool probe runs here too so the mutation-availability check stays off the
    event loop.
    """
    load_now = time.time() if now is None else now
    uv_tool = _probe_uv_tool()
    try:
        catalog = load_plugin_catalog(refresh=refresh, offline=offline, now=load_now)
    except PluginCatalogError as exc:
        return _PluginsLoadResult(
            catalog=None, error=str(exc), now=load_now, uv_tool=uv_tool
        )
    try:
        catalog = enrich_with_latest(catalog, offline=offline, refresh=refresh)
    except Exception:  # noqa: BLE001 - list stays read-only; markers degrade only.
        pass
    return _PluginsLoadResult(
        catalog=catalog, error=None, now=load_now, uv_tool=uv_tool
    )


@dataclass(frozen=True)
class _InstallPreview:
    """Off-thread result of planning an install for the confirm-preview modal.

    *index_plan* is the primary plan (install from the index, ``git=False``):
    either a terminal outcome (:class:`NotUvTool` / :class:`InstallNotFound` /
    :class:`AlreadyInstalled`) or an :class:`InstallReady`. *git_plan* is the
    optional git-source variant (present only when the index plan is ready and
    the git plan also resolves), so the modal's toggle stays pure presentation.
    *error* carries a catalog/receipt failure message instead of a plan.
    """

    index_plan: InstallPlan | None
    git_plan: InstallReady | None = None
    error: str | None = None


def _plan_install_preview(name: str, *, offline: bool) -> _InstallPreview:
    """Plan ``install <name>`` (index, then git) for the confirm-preview modal.

    Delegates to :func:`sase.plugins.operations.plan_install` — the single
    source of truth shared with the CLI — once per source. Cache-first
    (``refresh=False``); the optional git variant is only resolved when the
    index plan is ready, so a terminal outcome short-circuits the second load.
    """
    try:
        index_plan = plan_install(name, git=False, offline=offline)
    except (PluginCatalogError, ReceiptError) as exc:
        return _InstallPreview(index_plan=None, error=str(exc))

    git_plan: InstallReady | None = None
    if isinstance(index_plan, InstallReady):
        try:
            candidate = plan_install(name, git=True, offline=offline)
        except (PluginCatalogError, ReceiptError):
            candidate = None
        if isinstance(candidate, InstallReady):
            git_plan = candidate
    return _InstallPreview(index_plan=index_plan, git_plan=git_plan)


def _install_summary(plan: InstallReady) -> str:
    """The resolved-plugin-set line shown in the confirm-preview modal."""
    return f"Installs {plan.spec.display_name}  (from {plan.spec.source})"


def _install_success_message(outcome: InstallOutcome) -> str:
    """A concise, CLI-flavored success toast: name + new version + elapsed."""
    spec = outcome.plan.spec
    change = outcome.change_set.get(spec.requirement.name)
    version = change.new_version if change is not None else None
    suffix = f" v{version}" if version else ""
    return (
        f"Installed {spec.display_name}{suffix} in {humanize_duration(outcome.elapsed)}"
    )


def _missing_plugin_message(
    query: str, suggestions: tuple[PluginCatalogEntry, ...]
) -> str:
    """The not-found toast, mirroring the CLI's ranked-suggestions wording."""
    if suggestions:
        names = ", ".join(entry.name for entry in suggestions)
        return f"No plugin named '{query}' in the catalog. Did you mean: {names}?"
    return f"No plugin named '{query}' in the catalog."


def _not_found_message(plan: InstallNotFound) -> str:
    """The install not-found toast (shared wording with ``update``)."""
    return _missing_plugin_message(plan.query, plan.suggestions)


@dataclass(frozen=True)
class _UpdatePreview:
    """Off-thread result of planning an update for the confirm-preview modal.

    *plan* is the single :class:`UpdatePlan` outcome — a terminal one
    (:class:`NotUvTool` / :class:`NoPlugins` / :class:`NotInstalled` /
    :class:`UpdateUnknown`) routed to a CLI-matching toast, or an
    :class:`UpdateReady` opened in the confirm-preview modal. *error* carries a
    catalog/receipt failure message instead of a plan. Unlike install, update
    offers no source toggle, so there is only ever one plan.
    """

    plan: UpdatePlan | None
    error: str | None = None


def _plan_update_preview(
    query: str | None, *, all_plugins: bool, offline: bool
) -> _UpdatePreview:
    """Plan ``update <query>`` / ``update --all`` for the confirm-preview modal.

    Delegates to :func:`sase.plugins.operations.plan_update` — the single source
    of truth shared with the CLI — once, cache-first (``refresh=False``). A
    catalog/receipt failure becomes a toast-able error rather than a plan.
    """
    try:
        plan = plan_update(query, all_plugins=all_plugins, offline=offline)
    except (PluginCatalogError, ReceiptError) as exc:
        return _UpdatePreview(plan=None, error=str(exc))
    return _UpdatePreview(plan=plan)


def _update_subject(plan: UpdateReady) -> str:
    """The human subject of an update: 'every installed plugin' or the names."""
    if plan.all_plugins:
        return "every installed plugin"
    return ", ".join(plan.targets)


def _update_summary(plan: UpdateReady) -> str:
    """The resolved-plugin-set line shown in the confirm-preview modal.

    Mirrors the CLI's ``update --dry-run`` "Upgrades … (sase core stays pinned)".
    """
    return f"Upgrades {_update_subject(plan)}  (sase core stays pinned)"


def _update_success_message(outcome: UpdateOutcome) -> str:
    """A concise, CLI-flavored success toast: count upgraded + elapsed."""
    upgraded = sum(
        1
        for name in outcome.plan.targets
        if (change := outcome.change_set.get(name)) is not None
        and change.kind is ChangeKind.UPGRADED
    )
    if upgraded == 0:
        return "Plugins already up to date."
    plural = "plugin" if upgraded == 1 else "plugins"
    return f"Updated {upgraded} {plural} in {humanize_duration(outcome.elapsed)}"


def _not_installed_message(name: str) -> str:
    """The ``update`` not-installed toast, mirroring the CLI's wording."""
    return f"{name} is not installed. Run `sase plugin install {name}` to add it first."


def _no_plugins_message() -> str:
    """The ``update --all`` no-plugins toast, mirroring the CLI's wording."""
    return "No plugins are installed. Run `sase plugin list` to discover plugins."


class _PluginsFilterInput(Input):
    """Filter input that yields ``[`` / ``]`` to the host tab strip.

    Like the other Config Center panes, ``[`` / ``]`` must reach the host
    modal so tab switching works while typing; ``escape`` returns focus to
    the list without leaving a stale filter applied.
    """

    def on_key(self, event: events.Key) -> None:
        if event.key in ("left_square_bracket", "right_square_bracket"):
            host = self.screen
            prev_tab = getattr(host, "action_prev_center_tab", None)
            next_tab = getattr(host, "action_next_center_tab", None)
            if callable(prev_tab) and callable(next_tab):
                event.stop()
                event.prevent_default()
                (prev_tab if event.key == "left_square_bracket" else next_tab)()
        elif event.key == "escape":
            pane = self._pane()
            if pane is not None:
                event.stop()
                event.prevent_default()
                pane.cancel_input()

    def _pane(self) -> PluginsBrowserPane | None:
        node: object | None = self.parent
        while node is not None:
            if isinstance(node, PluginsBrowserPane):
                return node
            node = getattr(node, "parent", None)
        return None


class PluginsBrowserPane(Vertical):
    """Read-only browser for the SASE plugin catalog (Config Center → Plugins)."""

    can_focus = False

    BINDINGS = [
        ("j", "next_option", "Next"),
        ("k", "prev_option", "Previous"),
        ("i", "install", "Install"),
        ("u", "update", "Update"),
        ("U", "update_all", "Update all"),
        ("r", "refresh", "Refresh"),
        ("o", "toggle_offline", "Offline"),
        ("v", "toggle_verbose", "Verbose"),
        ("slash", "focus_filter", "Filter"),
    ]

    def __init__(self, *, auto_load: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._auto_load = auto_load
        self._catalog: PluginCatalog | None = None
        self._error: str | None = None
        self._loading = auto_load
        self._now = time.time()
        self._filter_text = ""
        self._offline = False
        self._verbose = False
        self._grouped: list[tuple[str, str, list[PluginCatalogEntry]]] = []
        self._worker: Worker[Any] | None = None
        #: Worker computing an install plan/preview before the confirm modal.
        self._plan_worker: Worker[Any] | None = None
        #: Worker computing an update plan/preview before the confirm modal.
        self._update_plan_worker: Worker[Any] | None = None
        #: One-shot uv-tool detection: gates whether mutations are possible.
        #: ``None`` until the first real load probes it.
        self._uv_tool: UvToolInstall | NotUvToolInstall | None = None
        #: Debounces the (cheap-but-not-free) detail rebuild so a held j/k
        #: paints exactly one final detail; created on mount once an app exists.
        self._detail_debouncer: DetailPanelDebouncer | None = None
        #: Name of the plugin currently shown in the detail panel (dedup guard).
        self._detail_name: str | None = None
        #: Plugin to re-highlight after the next reload (selection preservation).
        self._restore_name: str | None = None

    # -- composition --

    def compose(self) -> ComposeResult:
        yield Static(self._summary_text(), id="plugins-summary", markup=False)
        yield _PluginsFilterInput(
            placeholder="/ filter plugins…", id="plugins-filter-input"
        )
        with Horizontal(id="plugins-panels"):
            with Vertical(id="plugins-list-panel"):
                yield Static(self._status_message(), id="plugins-status", markup=False)
                yield OptionList(*self._create_options(), id="plugins-list")
            with Vertical(id="plugins-detail-panel"):
                with VerticalScroll(id="plugins-detail-scroll"):
                    yield Static(_DETAIL_PLACEHOLDER, id="plugins-detail", markup=False)
        yield Static(self._hints(), id="plugins-hints", markup=False)

    def on_mount(self) -> None:
        self._detail_debouncer = DetailPanelDebouncer(self.app)
        self._sync_state_visibility()
        if self._auto_load:
            self._start_load(force=False)

    def focus_default(self) -> None:
        """Focus the list (browse-first) when the Plugins tab activates."""
        option_list = self._option_list()
        if option_list is not None:
            option_list.focus()

    # -- loading --

    def _start_load(self, *, force: bool) -> None:
        self._loading = True
        self._error = None
        # Re-highlight whatever is selected now once the reload lands so a
        # refresh / offline toggle doesn't snap the user back to the top.
        self._restore_name = self._highlighted_name()
        self._sync_state_visibility()
        self._update_static("#plugins-summary", self._summary_text())
        self._update_static("#plugins-hints", self._hints())
        refresh = force
        offline = self._offline

        def task() -> _PluginsLoadResult:
            return _load_plugins_catalog(refresh=refresh, offline=offline)

        self._worker = self.run_worker(task, thread=True, exclusive=True)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._plan_worker:
            if event.state == WorkerState.SUCCESS:
                self._plan_worker = None
                self._on_install_preview(event.worker.result)
            elif event.state == WorkerState.ERROR:
                self._plan_worker = None
                self._notify(self._worker_error_text(event.worker), severity="error")
            return
        if event.worker is self._update_plan_worker:
            if event.state == WorkerState.SUCCESS:
                self._update_plan_worker = None
                self._on_update_preview(event.worker.result)
            elif event.state == WorkerState.ERROR:
                self._update_plan_worker = None
                self._notify(
                    self._worker_error_text(event.worker, kind="update"),
                    severity="error",
                )
            return
        if event.worker is not self._worker:
            return
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            self._loading = False
            self._catalog = getattr(result, "catalog", None)
            self._error = getattr(result, "error", None)
            self._now = getattr(result, "now", self._now)
            # Keep a previously-detected probe result if a stubbed loader (or a
            # failed probe) returns None — "detect once" per the epic.
            probed = getattr(result, "uv_tool", None)
            if probed is not None:
                self._uv_tool = probed
            self._render_all()
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._error = (
                str(event.worker.error) if event.worker.error else "load failed"
            )
            self._render_all()

    @staticmethod
    def _worker_error_text(worker: Worker[Any], *, kind: str = "install") -> str:
        if worker.error:
            return str(worker.error)
        return f"Could not plan the {kind}."

    # -- rendering --

    def _render_all(self) -> None:
        self._rebuild_groups()
        self._update_static("#plugins-summary", self._summary_text())
        self._update_static("#plugins-hints", self._hints())
        self._rebuild_options()
        self._sync_state_visibility()
        # A fresh load may have changed the highlighted plugin's data (e.g. a
        # new latest version), so force the detail to repaint immediately.
        self._render_detail_now(force=True)

    def _rebuild_groups(self) -> None:
        self._grouped = []
        catalog = self._catalog
        if catalog is None:
            return
        builtin = [e for e in catalog.builtin_entries if self._matches(e)]
        community = [e for e in catalog.community_entries if self._matches(e)]
        if builtin:
            self._grouped.append((_BUILTIN_GROUP, "bold dim", builtin))
        if community:
            self._grouped.append(
                (_COMMUNITY_GROUP, f"bold {_COMMUNITY_STYLE}", community)
            )

    def _matches(self, entry: PluginCatalogEntry) -> bool:
        needle = self._filter_text.strip().casefold()
        if not needle:
            return True
        haystack = "\n".join(
            part
            for part in (entry.name, entry.repo, entry.description, *entry.topics)
            if part
        ).casefold()
        return needle in haystack

    def _rebuild_options(self) -> None:
        option_list = self._option_list()
        if option_list is None:
            return
        preferred = self._restore_name
        self._restore_name = None
        option_list.clear_options()
        for opt in self._create_options():
            option_list.add_option(opt)
        if preferred is not None and self._highlight_named(option_list, preferred):
            return
        self._skip_to_first_item(option_list)

    def _create_options(self) -> list[Option]:
        """Build OptionList items: disabled section headers + plugin rows."""
        options: list[Option] = []
        for group, style, entries in self._grouped:
            header = Text(f"── {group} ──", style=style)
            options.append(Option(header, id=f"{_HEADER_PREFIX}{group}", disabled=True))
            for entry in entries:
                options.append(
                    Option(self._row_text(entry), id=f"{_ITEM_PREFIX}{entry.name}")
                )
        return options

    def _row_text(self, entry: PluginCatalogEntry) -> Text:
        """A single list row: status glyph + name + version + update marker."""
        text = Text()
        text.append("  ")
        if entry.installed.installed:
            text.append(_INSTALLED_GLYPH, style="green")
        else:
            text.append(_AVAILABLE_GLYPH, style="dim")
        text.append(" ")
        text.append(entry.name, style="bold")
        version = self._version_label(entry)
        if version:
            text.append("  ")
            text.append(version, style="dim")
        if entry.update_available:
            text.append("  ")
            text.append(_UPDATE_GLYPH, style="bold cyan")
        if self._verbose:
            text.append("  ")
            text.append(f"★{entry.stars}", style="dim")
            if entry.updated_at:
                text.append("  ")
                text.append(entry.updated_at, style="dim")
        return text

    @staticmethod
    def _version_label(entry: PluginCatalogEntry) -> str:
        info = entry.installed
        if info.installed:
            if entry.latest.source == "editable":
                return "editable"
            if entry.latest.source == "git":
                return "git"
            if entry.update_available and info.version and entry.latest.version:
                return f"v{info.version} → v{entry.latest.version}"
            if info.version:
                return f"v{info.version}"
            return "installed"
        if entry.latest.version:
            return f"latest v{entry.latest.version}"
        return ""

    def _skip_to_first_item(self, option_list: OptionList) -> None:
        """Highlight the first non-header option, if any."""
        for index in range(option_list.option_count):
            if self._is_item(option_list, index):
                option_list.highlighted = index
                return

    def _highlight_named(self, option_list: OptionList, name: str) -> bool:
        """Highlight the row for *name* if it is present; return success."""
        target = f"{_ITEM_PREFIX}{name}"
        for index in range(option_list.option_count):
            opt = option_list.get_option_at_index(index)
            if opt.id == target:
                option_list.highlighted = index
                return True
        return False

    # -- detail panel --

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Repaint the detail panel for the newly highlighted row (debounced).

        The cursor highlight is already instant (the ``OptionList`` paints it
        itself); only the comparatively expensive detail rebuild is funneled
        through the debouncer so a held j/k collapses to one final paint. The
        hints line (which gates ``i install`` on the highlighted row) is cheap,
        so it refreshes immediately.
        """
        self._update_static("#plugins-hints", self._hints())
        self._schedule_detail()

    def _schedule_detail(self) -> None:
        debouncer = self._detail_debouncer
        if debouncer is None:
            self._render_detail_now()
            return
        debouncer.schedule(self._render_detail_now)

    def _render_detail_now(self, *, force: bool = False) -> None:
        """Paint the detail panel for the currently highlighted plugin.

        Re-reads the live highlight (so the latest selection wins after a
        debounced burst) and skips redundant work when the same plugin is
        already shown, unless *force* is set (used after a reload whose data
        may have changed under an unchanged selection).
        """
        entry = self._current_entry()
        name = entry.name if entry is not None else None
        if not force and name == self._detail_name:
            return
        self._detail_name = name
        self._update_detail(entry)

    def _update_detail(self, entry: PluginCatalogEntry | None) -> None:
        detail = self._detail_widget()
        if detail is None:
            return
        if entry is None:
            detail.update(_DETAIL_PLACEHOLDER)
            return
        detail.update(self._detail_renderable(entry))

    @staticmethod
    def _detail_renderable(entry: PluginCatalogEntry) -> RenderableType:
        """The ``show``-equivalent detail: community warning (if any) + panel."""
        parts: list[RenderableType] = []
        if entry.is_community:
            parts.append(build_community_warning_panel(entry))
        parts.append(build_detail_panel(entry))
        return Group(*parts)

    def _current_entry(self) -> PluginCatalogEntry | None:
        option_list = self._option_list()
        if option_list is None or option_list.highlighted is None:
            return None
        try:
            opt = option_list.get_option_at_index(option_list.highlighted)
        except Exception:
            return None
        if not opt.id or str(opt.id).startswith(_HEADER_PREFIX):
            return None
        return self._entry_by_name(str(opt.id).removeprefix(_ITEM_PREFIX))

    def _entry_by_name(self, name: str) -> PluginCatalogEntry | None:
        for _, _, entries in self._grouped:
            for entry in entries:
                if entry.name == name:
                    return entry
        return None

    def _highlighted_name(self) -> str | None:
        entry = self._current_entry()
        return entry.name if entry is not None else None

    # -- state visibility --

    def _sync_state_visibility(self) -> None:
        """Show the list when populated, else the status placeholder.

        A *reload* (refresh / offline toggle) keeps the already-painted rows
        visible — the header reports "loading…" instead — so the list never
        flashes away and the focused highlight is preserved. The status
        placeholder is reserved for the initial load, the error state, and the
        genuinely empty / no-match cases.
        """
        has_rows = any(entries for _, _, entries in self._grouped)
        try:
            status = self.query_one("#plugins-status", Static)
            option_list = self.query_one("#plugins-list", OptionList)
        except Exception:
            return
        status.update(self._status_message())
        show_status = self._error is not None or not has_rows
        status.display = show_status
        option_list.display = not show_status

    # -- dynamic text --

    def _summary_text(self) -> Text:
        """Header summary: counts line + offline badge + warning/stale hint."""
        text = Text(self._summary_line())
        if self._offline:
            text.append("   ")
            text.append("⚠ OFFLINE", style="bold yellow")
        if isinstance(self._uv_tool, NotUvToolInstall):
            text.append("\n")
            text.append("⚠ ", style="yellow")
            text.append(
                "Install/update unavailable — sase is not a `uv tool` install.",
                style="yellow",
            )
        hint = self._summary_hint()
        if hint is not None:
            text.append("\n")
            text.append("⚠ ", style="yellow")
            text.append(hint, style="yellow")
        return text

    def _summary_line(self) -> str:
        if self._loading:
            return "SASE Plugins · loading…"
        catalog = self._catalog
        if catalog is None:
            return "SASE Plugins · unavailable"
        total = len(catalog.entries)
        installed = catalog.installed_count
        updates = catalog.updates_available
        age = humanize_age(catalog.age_seconds(self._now))
        return (
            f"{total} plugins · {installed} installed · "
            f"{updates} updates available · cached {age}"
        )

    def _summary_hint(self) -> str | None:
        """A warning / stale-cache line to surface under the counts, if any."""
        catalog = self._catalog
        if self._loading or catalog is None:
            return None
        if catalog.warnings:
            return catalog.warnings[0]
        if catalog.stale:
            age = humanize_age(catalog.age_seconds(self._now))
            return f"cache is stale (last updated {age}) — press r to refresh"
        return None

    def _status_message(self) -> str:
        if self._loading:
            return "Loading plugins…"
        if self._error is not None:
            return f"Could not load plugins:\n{self._error}"
        if self._catalog is None:
            return "Plugin catalog unavailable."
        if not self._catalog.entries:
            return "No SASE plugins found."
        if not any(entries for _, _, entries in self._grouped):
            return "No plugins match the current filter."
        return ""

    def _hints(self) -> str:
        offline = " (on)" if self._offline else ""
        verbose = " (on)" if self._verbose else ""
        parts: list[str] = []
        if self._can_install_highlighted():
            parts.append("i install")
        if self._can_update_highlighted():
            entry = self._current_entry()
            emphasize = entry is not None and entry.update_available
            parts.append("u update ↑" if emphasize else "u update")
        if self._can_update_all():
            parts.append("U update-all")
        parts.extend(
            [
                "r refresh",
                f"o offline{offline}",
                f"v verbose{verbose}",
                "/ filter",
                "[ / ] tab",
                "esc close",
            ]
        )
        return " · ".join(parts)

    def _can_install_highlighted(self) -> bool:
        """Whether the highlighted plugin can be installed right now.

        False when sase is not a managed ``uv tool`` install (mutations are
        impossible) or the highlighted row is absent / already installed.
        """
        if isinstance(self._uv_tool, NotUvToolInstall):
            return False
        entry = self._current_entry()
        return entry is not None and not entry.installed.installed

    def _can_update_highlighted(self) -> bool:
        """Whether the highlighted plugin can be updated right now.

        True only when sase is a managed ``uv tool`` install and the highlighted
        row is already installed (an update is *emphasized* in the hint when one
        is available, but the action is offered for any installed plugin so a
        forced re-check stays discoverable).
        """
        if isinstance(self._uv_tool, NotUvToolInstall):
            return False
        entry = self._current_entry()
        return entry is not None and entry.installed.installed

    def _can_update_all(self) -> bool:
        """Whether ``update --all`` is possible: uv-tool install with plugins."""
        if isinstance(self._uv_tool, NotUvToolInstall):
            return False
        catalog = self._catalog
        return catalog is not None and catalog.installed_count > 0

    # -- navigation --

    def action_next_option(self) -> None:
        """Move to the next non-header option."""
        option_list = self._option_list()
        if option_list is None:
            return
        current = option_list.highlighted
        start = 0 if current is None else current + 1
        for index in range(start, option_list.option_count):
            if self._is_item(option_list, index):
                option_list.highlighted = index
                return

    def action_prev_option(self) -> None:
        """Move to the previous non-header option."""
        option_list = self._option_list()
        if option_list is None or option_list.highlighted is None:
            return
        for index in range(option_list.highlighted - 1, -1, -1):
            if self._is_item(option_list, index):
                option_list.highlighted = index
                return

    def action_focus_filter(self) -> None:
        try:
            self.query_one("#plugins-filter-input", _PluginsFilterInput).focus()
        except Exception:
            pass

    # -- read-side actions (refresh / offline / verbose) --

    def action_refresh(self) -> None:
        """Refetch the catalog and latest versions (the ``-r/--refresh`` analog)."""
        if self._loading:
            return
        self._start_load(force=True)

    def action_toggle_offline(self) -> None:
        """Toggle offline (cache-only) mode and reload (the ``-o`` analog)."""
        if self._loading:
            return
        self._offline = not self._offline
        self._start_load(force=False)

    def action_toggle_verbose(self) -> None:
        """Toggle the list rows' verbose columns (stars / updated)."""
        self._verbose = not self._verbose
        self._rebuild_options()
        self._update_static("#plugins-hints", self._hints())
        self._render_detail_now(force=True)

    # -- install action --

    def action_install(self) -> None:
        """Install the highlighted plugin (``i``) via a confirm-preview modal.

        Offered only for a *not-installed* plugin. Short-circuits with the CLI's
        actionable message when sase is not a managed ``uv tool`` install, then
        plans the install off-thread (so a cache read never blocks the UI) and
        opens the confirm-preview modal; the actual ``uv`` run happens later, in
        a tracked background task, only if the user confirms.
        """
        if self._loading or self._plan_worker is not None:
            return
        entry = self._current_entry()
        if entry is None:
            return
        if entry.installed.installed:
            self._notify(f"{entry.name} is already installed.")
            return
        if isinstance(self._uv_tool, NotUvToolInstall):
            self._notify(str(NotAUvToolInstallError(self._uv_tool)), severity="warning")
            return
        self._begin_install_plan(entry.name)

    def _begin_install_plan(self, name: str) -> None:
        offline = self._offline

        def task() -> _InstallPreview:
            return _plan_install_preview(name, offline=offline)

        self._plan_worker = self.run_worker(
            task, thread=True, exclusive=True, group="plugin-plan"
        )

    def _on_install_preview(self, preview: _InstallPreview | None) -> None:
        """Route a planned install to a toast (terminal) or the confirm modal."""
        if preview is None:
            return
        if preview.error is not None:
            self._notify(preview.error, severity="error")
            return
        plan = preview.index_plan
        if isinstance(plan, NotUvTool):
            self._notify(str(plan.error), severity="warning")
        elif isinstance(plan, InstallNotFound):
            self._notify(_not_found_message(plan), severity="error")
        elif isinstance(plan, AlreadyInstalled):
            self._notify(f"{plan.spec.display_name} is already installed.")
        elif isinstance(plan, InstallReady):
            self._open_install_modal(plan, preview.git_plan)

    def _open_install_modal(
        self, index_plan: InstallReady, git_plan: InstallReady | None
    ) -> None:
        plans: dict[str, InstallReady] = {"index": index_plan}
        variants = [
            PluginActionVariant(
                key="index",
                label="from index",
                argv=tuple(index_plan.argv),
                summary=_install_summary(index_plan),
            )
        ]
        if git_plan is not None:
            plans["git"] = git_plan
            variants.append(
                PluginActionVariant(
                    key="git",
                    label="from git",
                    argv=tuple(git_plan.argv),
                    summary=_install_summary(git_plan),
                )
            )
        name = index_plan.spec.display_name
        modal = PluginActionConfirmModal(
            title=f"Install {name}",
            intro=f"Confirm to install {name} into sase's uv tool environment.",
            variants=variants,
            panel_title="Confirm install",
        )

        def _on_confirmed(result: PluginActionConfirmResult | None) -> None:
            if result is None:
                return
            self._submit_install_task(name, plans.get(result.variant_key, index_plan))

        self.app.push_screen(modal, _on_confirmed)

    def _submit_install_task(self, name: str, plan: InstallReady) -> None:
        """Run ``execute_install`` in a tracked background task (never blocks)."""

        def task() -> TrackedTaskResult[InstallOutcome]:
            try:
                outcome = execute_install(plan)
            except UvToolError as exc:
                return TrackedTaskResult(
                    success=False, message=str(exc), error=str(exc)
                )
            return TrackedTaskResult(
                success=True,
                message=_install_success_message(outcome),
                payload=outcome,
            )

        submit = getattr(self.app, "_submit_tracked_task", None)
        if submit is None:
            return
        submit(
            "plugin-install",
            name,
            "",
            task,
            display_name=f"install {name}",
            dedup_key=f"plugin-install:{name}",
            duplicate_message=f"An install is already running for {name}.",
            on_complete=self._on_install_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )

    def _on_install_complete(
        self, completion: TrackedTaskCompletion[InstallOutcome]
    ) -> None:
        """Toast the CLI-matching outcome and refresh the row in place."""
        if completion.success:
            self._notify(completion.message)
            # Re-merge installed state so the freshly-installed row flips to ●.
            if self.is_mounted and not self._loading:
                self._start_load(force=False)
        else:
            detail = completion.error or completion.message
            self._notify(f"Install failed: {detail}", severity="error")

    # -- update actions --

    def action_update(self) -> None:
        """Update the highlighted plugin (``u``) via a confirm-preview modal.

        Offered only for an *installed* plugin. Short-circuits with the CLI's
        actionable message when sase is not a managed ``uv tool`` install or the
        highlighted plugin is not installed, then plans the update off-thread and
        opens the confirm-preview modal; the ``uv`` upgrade runs later, in a
        tracked background task, only if the user confirms.
        """
        if self._loading or self._update_plan_worker is not None:
            return
        entry = self._current_entry()
        if entry is None:
            return
        if isinstance(self._uv_tool, NotUvToolInstall):
            self._notify(str(NotAUvToolInstallError(self._uv_tool)), severity="warning")
            return
        if not entry.installed.installed:
            self._notify(_not_installed_message(entry.name), severity="warning")
            return
        self._begin_update_plan(entry.name, all_plugins=False)

    def action_update_all(self) -> None:
        """Update every installed plugin (``U``) via a confirm-preview modal.

        Short-circuits with the CLI's actionable message when sase is not a
        managed ``uv tool`` install; the no-plugins case is reported from the
        plan (the receipt, not the catalog, is the source of truth).
        """
        if self._loading or self._update_plan_worker is not None:
            return
        if isinstance(self._uv_tool, NotUvToolInstall):
            self._notify(str(NotAUvToolInstallError(self._uv_tool)), severity="warning")
            return
        self._begin_update_plan(None, all_plugins=True)

    def _begin_update_plan(self, query: str | None, *, all_plugins: bool) -> None:
        offline = self._offline

        def task() -> _UpdatePreview:
            return _plan_update_preview(query, all_plugins=all_plugins, offline=offline)

        self._update_plan_worker = self.run_worker(
            task, thread=True, exclusive=True, group="plugin-update-plan"
        )

    def _on_update_preview(self, preview: _UpdatePreview | None) -> None:
        """Route a planned update to a toast (terminal) or the confirm modal."""
        if preview is None:
            return
        if preview.error is not None:
            self._notify(preview.error, severity="error")
            return
        plan = preview.plan
        if isinstance(plan, NotUvTool):
            self._notify(str(plan.error), severity="warning")
        elif isinstance(plan, NoPlugins):
            self._notify(_no_plugins_message())
        elif isinstance(plan, NotInstalled):
            self._notify(_not_installed_message(plan.name), severity="warning")
        elif isinstance(plan, UpdateUnknown):
            self._notify(
                _missing_plugin_message(plan.query, plan.suggestions), severity="error"
            )
        elif isinstance(plan, UpdateReady):
            self._open_update_modal(plan)

    def _open_update_modal(self, plan: UpdateReady) -> None:
        if plan.all_plugins:
            title = "Update all plugins"
            intro = (
                "Confirm to upgrade every installed plugin (sase core stays pinned)."
            )
        else:
            name = plan.targets[0]
            title = f"Update {name}"
            intro = f"Confirm to upgrade {name} (sase core stays pinned)."
        variants = [
            PluginActionVariant(
                key="update",
                label="update",
                argv=tuple(plan.argv),
                summary=_update_summary(plan),
            )
        ]
        modal = PluginActionConfirmModal(
            title=title,
            intro=intro,
            variants=variants,
            panel_title="Confirm update",
        )

        def _on_confirmed(result: PluginActionConfirmResult | None) -> None:
            if result is None:
                return
            self._submit_update_task(plan)

        self.app.push_screen(modal, _on_confirmed)

    def _submit_update_task(self, plan: UpdateReady) -> None:
        """Run ``execute_update`` in a tracked background task (never blocks)."""

        def task() -> TrackedTaskResult[UpdateOutcome]:
            try:
                outcome = execute_update(plan)
            except UvToolError as exc:
                return TrackedTaskResult(
                    success=False, message=str(exc), error=str(exc)
                )
            return TrackedTaskResult(
                success=True,
                message=_update_success_message(outcome),
                payload=outcome,
            )

        submit = getattr(self.app, "_submit_tracked_task", None)
        if submit is None:
            return
        label = "all plugins" if plan.all_plugins else plan.targets[0]
        dedup = "plugin-update:all" if plan.all_plugins else f"plugin-update:{label}"
        submit(
            "plugin-update",
            label,
            "",
            task,
            display_name=f"update {label}",
            dedup_key=dedup,
            duplicate_message=f"An update is already running for {label}.",
            on_complete=self._on_update_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )

    def _on_update_complete(
        self, completion: TrackedTaskCompletion[UpdateOutcome]
    ) -> None:
        """Toast the CLI-matching outcome and refresh the row(s) in place."""
        if completion.success:
            self._notify(completion.message)
            # Re-merge installed state so upgraded rows reflect the new version.
            if self.is_mounted and not self._loading:
                self._start_load(force=False)
        else:
            detail = completion.error or completion.message
            self._notify(f"Update failed: {detail}", severity="error")

    def _notify(
        self,
        message: str,
        *,
        severity: Literal["information", "warning", "error"] = "information",
    ) -> None:
        """Toast *message*, tolerating an already-unmounted pane/app."""
        try:
            self.app.notify(message, severity=severity)
        except Exception:
            pass

    # -- input events --

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "plugins-filter-input":
            return
        self._filter_text = event.value
        self._rebuild_groups()
        self._rebuild_options()
        self._sync_state_visibility()
        self._render_detail_now(force=True)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "plugins-filter-input":
            # Keep the filter applied; hand control back to the list.
            self.focus_default()

    def cancel_input(self) -> None:
        """Drop any in-progress filter and return focus to the list."""
        if self._filter_text:
            self._filter_text = ""
            self._set_filter_value("")
            self._rebuild_groups()
            self._rebuild_options()
            self._sync_state_visibility()
            self._render_detail_now(force=True)
        self.focus_default()

    # -- helpers --

    def _option_list(self) -> OptionList | None:
        try:
            return self.query_one("#plugins-list", OptionList)
        except Exception:
            return None

    def _detail_widget(self) -> Static | None:
        try:
            return self.query_one("#plugins-detail", Static)
        except Exception:
            return None

    @staticmethod
    def _is_item(option_list: OptionList, index: int) -> bool:
        try:
            opt = option_list.get_option_at_index(index)
        except Exception:
            return False
        return bool(opt.id) and not str(opt.id).startswith(_HEADER_PREFIX)

    def _set_filter_value(self, value: str) -> None:
        try:
            self.query_one("#plugins-filter-input", _PluginsFilterInput).value = value
        except Exception:
            pass

    def _update_static(self, selector: str, content: Text | str) -> None:
        try:
            self.query_one(selector, Static).update(content)
        except Exception:
            pass
