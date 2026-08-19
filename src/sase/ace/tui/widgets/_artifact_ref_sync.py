"""The ``@<kind>::`` ref-sync gesture: trigger, session-worker, and state machine."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sase.artifact_ref_sync import (
    ArtifactRefSyncOutcome,
    ArtifactRefSyncPlan,
    plan_artifact_ref_sync,
    run_artifact_ref_sync,
)
from sase.feature_flags.registry import FeatureFlag
from sase.feature_flags.snapshot import current_flags

from ._artifact_ref_highlight import resolve_artifact_ref_warm_workspace
from .artifact_ref_completion import (
    ARTIFACT_REF_COMPLETION_KIND,
    ArtifactRefCompletionCatalog,
    ArtifactRefSyncCompletionMetadata,
)
from .file_completion import CompletionCandidate

if TYPE_CHECKING:
    from textual.timer import Timer
    from textual.widgets import TextArea as _MixinBase

    from sase.artifact_refs import ArtifactRefContext
    from sase.ace.tui.actions._proc_action_types import TrackedProcCompletion
    from sase.ace.tui.widgets.artifact_ref_completion import (
        ArtifactRefCompletionContext,
    )
else:
    _MixinBase = object


_RefSyncPhase = Literal["running", "reloading", "settled_ok", "settled_error"]
_ARTIFACT_REF_SYNC_DISMISS_SECONDS = 2.5
_ARTIFACT_REF_SYNC_SPINNER_INTERVAL = 0.1


@dataclass(slots=True)
class _RefSyncState:
    """One in-flight or settled ``@<kind>::`` sync for one ``(project, kind)``."""

    phase: _RefSyncPhase
    plan: ArtifactRefSyncPlan
    detail: str = ""
    frame: int = 0
    new_payloads: frozenset[str] = field(default_factory=frozenset)
    before_payloads: frozenset[str] = field(default_factory=frozenset)


class ArtifactRefSyncMixin(_MixinBase):
    """Own the ``@<kind>::`` gesture: trigger detection, sync, and status rows."""

    if TYPE_CHECKING:
        _artifact_ref_completion_catalogs_by_project: dict[
            str | None, ArtifactRefCompletionCatalog
        ]
        _artifact_ref_contexts_by_project: dict[str | None, ArtifactRefContext]
        _artifact_ref_known_kinds_by_project: dict[str | None, frozenset[str]]
        _artifact_ref_kinds_warming: set[str | None]
        _completion_kind: str
        _file_completion_active: bool
        _file_completion_candidates: list[CompletionCandidate]
        _vim_mode: str
        app: Any
        cursor_location: tuple[int, int]
        is_mounted: bool

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _find_prompt_bar(self) -> Any: ...
        def _get_artifact_ref_completion_context(
            self,
        ) -> ArtifactRefCompletionContext | None: ...
        def _get_warm_artifact_ref_completion_catalog(
            self,
        ) -> ArtifactRefCompletionCatalog | None: ...
        def _get_warm_artifact_ref_context(self) -> ArtifactRefContext | None: ...
        def _get_warm_artifact_ref_known_kinds(self) -> frozenset[str] | None: ...
        def _try_artifact_ref_completion(self, *, force: bool = False) -> bool: ...
        def _update_file_completion_panel(self, token: str) -> None: ...
        def _warm_current_artifact_ref_completion_catalog(self) -> None: ...
        def _xprompt_arg_assist_project_from_text(self) -> str | None: ...

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._artifact_ref_sync_states: dict[tuple[str | None, str], _RefSyncState] = {}
        self._artifact_ref_sync_spinner_timer: Timer | None = None
        super().__init__(*args, **kwargs)

    def on_unmount(self) -> None:
        """Stop the spinner timer; the background sync still runs to completion."""
        super_on_unmount = getattr(super(), "on_unmount", None)
        if callable(super_on_unmount):
            super_on_unmount()
        self._stop_artifact_ref_sync_spinner()

    # -- Trigger ----------------------------------------------------------

    def _artifact_ref_sync_trigger(self) -> str | None:
        """Return the kind to sync when the cursor sits at an empty ``@<kind>:``."""
        if self._vim_mode != "insert":
            return None
        bar = self._find_prompt_bar()
        if bar is not None and getattr(bar, "_mode", "prompt") != "prompt":
            return None
        if not current_flags().enabled(FeatureFlag.ref_sync_gesture):
            return None
        context = self._get_artifact_ref_completion_context()
        if context is None or context.stage != "payload" or context.kind is None:
            return None
        if context.partial_payload != "":
            return None
        cursor_offset = self._absolute_offset(self.cursor_location)
        if context.replacement_end != cursor_offset:
            return None
        known_kinds = self._get_warm_artifact_ref_known_kinds()
        if known_kinds is None or context.kind not in known_kinds:
            return None
        return context.kind

    # -- Start / execute ----------------------------------------------------

    def _start_artifact_ref_sync(self, kind: str) -> None:
        """Refresh *kind*'s sources now, then reopen the payload menu."""
        project = self._xprompt_arg_assist_project_from_text()
        key = (project, kind)
        existing = self._artifact_ref_sync_states.get(key)
        if existing is not None and existing.phase in ("running", "reloading"):
            return

        workspace_dir, workspace_num = self._artifact_ref_sync_workspace()
        context = self._get_warm_artifact_ref_context()
        if context is not None:
            plan = plan_artifact_ref_sync(
                context,
                kind,
                workspace_dir=workspace_dir,
                workspace_num=workspace_num,
            )
        else:
            plan = ArtifactRefSyncPlan(
                kind=kind, mode="rescan", role=None, label=kind, checkout=None
            )

        before_payloads = _catalog_kind_payloads(
            self._get_warm_artifact_ref_completion_catalog(), kind
        )
        self._artifact_ref_sync_states[key] = _RefSyncState(
            phase="running",
            plan=plan,
            before_payloads=before_payloads,
        )
        self._start_artifact_ref_sync_spinner()
        self._try_artifact_ref_completion(force=False)

        from sase.ace.tui.actions._proc_action_types import TrackedProcResult

        def body() -> TrackedProcResult[ArtifactRefSyncOutcome]:
            outcome = run_artifact_ref_sync(
                plan,
                workspace_dir=workspace_dir,
                workspace_num=workspace_num,
            )
            return TrackedProcResult(
                success=outcome.ok,
                message=outcome.detail or "synced",
                payload=outcome,
            )

        def on_complete(
            completion: TrackedProcCompletion[ArtifactRefSyncOutcome],
        ) -> None:
            outcome = completion.payload
            if outcome is None:
                outcome = ArtifactRefSyncOutcome(
                    plan=plan,
                    ok=completion.success,
                    detail=completion.error or completion.message,
                )
            self._on_artifact_ref_sync_complete(outcome, project, kind)

        self.app._submit_session_worker(
            "ref-sync",
            body,
            on_complete=on_complete,
            display_name=f"sync @{kind}",
            dedup_key=f"ref-sync:{project}:{kind}",
            duplicate_message=f"Already syncing @{kind}",
        )

    def _artifact_ref_sync_workspace(self) -> tuple[Path, int]:
        """Resolve the workspace identically to the completion catalog warm."""
        project = self._xprompt_arg_assist_project_from_text()
        workspace_dir: str | None = None
        workspace_num = 1
        prompt_context = getattr(self.app, "_prompt_context", None)
        if prompt_context is not None:
            raw_workspace_dir = getattr(prompt_context, "workspace_dir", None)
            if isinstance(raw_workspace_dir, str) and raw_workspace_dir:
                workspace_dir = raw_workspace_dir
            raw_workspace_num = getattr(prompt_context, "workspace_num", None)
            if isinstance(raw_workspace_num, int) and raw_workspace_num > 0:
                workspace_num = raw_workspace_num
        return resolve_artifact_ref_warm_workspace(
            project, workspace_dir, workspace_num
        )

    # -- Completion ----------------------------------------------------------

    def _on_artifact_ref_sync_complete(
        self,
        outcome: ArtifactRefSyncOutcome,
        project: str | None,
        kind: str,
    ) -> None:
        """UI-thread completion handler for the background sync worker."""
        if not self.is_mounted:
            return
        key = (project, kind)
        state = self._artifact_ref_sync_states.get(key)
        if state is None:
            return
        if not outcome.ok:
            state.phase = "settled_error"
            state.detail = outcome.detail or "sync failed"
            self._repaint_or_toast_artifact_ref_sync(project, kind, success=False)
            return
        state.phase = "reloading"
        self._evict_artifact_ref_completion_cache(project)
        self._warm_current_artifact_ref_completion_catalog()

    def _evict_artifact_ref_completion_cache(self, project: str | None) -> None:
        self._artifact_ref_completion_catalogs_by_project.pop(project, None)
        self._artifact_ref_contexts_by_project.pop(project, None)
        self._artifact_ref_known_kinds_by_project.pop(project, None)
        self._artifact_ref_kinds_warming.discard(project)

    def _finish_artifact_ref_sync_reload_for_project(self, project: str | None) -> None:
        """Settle every ``reloading`` sync for *project* once its catalog re-warms."""
        pending = [
            kind
            for (
                candidate_project,
                kind,
            ), state in self._artifact_ref_sync_states.items()
            if candidate_project == project and state.phase == "reloading"
        ]
        for kind in pending:
            self._finish_artifact_ref_sync_reload(project, kind)

    def _finish_artifact_ref_sync_reload(self, project: str | None, kind: str) -> None:
        """Diff the freshly warmed catalog against the pre-sync snapshot."""
        if not self.is_mounted:
            return
        key = (project, kind)
        state = self._artifact_ref_sync_states.get(key)
        if state is None or state.phase != "reloading":
            return
        catalog = self._artifact_ref_completion_catalogs_by_project.get(project)
        after_payloads = _catalog_kind_payloads(catalog, kind)
        state.new_payloads = after_payloads - state.before_payloads
        state.phase = "settled_ok"
        state.detail = ""
        self._arm_artifact_ref_sync_dismiss_timer(project, kind)
        self._repaint_or_toast_artifact_ref_sync(project, kind, success=True)

    def _arm_artifact_ref_sync_dismiss_timer(
        self, project: str | None, kind: str
    ) -> None:
        self.set_timer(
            _ARTIFACT_REF_SYNC_DISMISS_SECONDS,
            lambda: self._dismiss_artifact_ref_sync(project, kind),
        )

    def _dismiss_artifact_ref_sync(self, project: str | None, kind: str) -> None:
        if not self.is_mounted:
            return
        key = (project, kind)
        state = self._artifact_ref_sync_states.get(key)
        if state is None or state.phase != "settled_ok":
            return
        del self._artifact_ref_sync_states[key]
        self._repaint_or_toast_artifact_ref_sync(project, kind, success=True)

    def _repaint_or_toast_artifact_ref_sync(
        self,
        project: str | None,
        kind: str,
        *,
        success: bool,
    ) -> None:
        if (
            self._file_completion_active
            and self._completion_kind == ARTIFACT_REF_COMPLETION_KIND
            and self._xprompt_arg_assist_project_from_text() == project
        ):
            refresh = getattr(self, "_refresh_file_completion_from_cursor", None)
            if callable(refresh):
                refresh()
            return
        if success:
            return
        state = self._artifact_ref_sync_states.get((project, kind))
        label = state.plan.label if state is not None else kind
        detail = state.detail if state is not None else ""
        message = f"{label} sync failed: {detail}" if detail else f"{label} sync failed"
        try:
            self.app.notify(message, severity="warning", markup=False)
        except Exception:
            pass

    # -- Spinner ----------------------------------------------------------

    def _start_artifact_ref_sync_spinner(self) -> None:
        if self._artifact_ref_sync_spinner_timer is not None:
            return
        self._artifact_ref_sync_spinner_timer = self.set_interval(
            _ARTIFACT_REF_SYNC_SPINNER_INTERVAL,
            self._tick_artifact_ref_sync_spinner,
        )

    def _stop_artifact_ref_sync_spinner(self) -> None:
        if self._artifact_ref_sync_spinner_timer is not None:
            self._artifact_ref_sync_spinner_timer.stop()
            self._artifact_ref_sync_spinner_timer = None

    def _tick_artifact_ref_sync_spinner(self) -> None:
        active = [
            state
            for state in self._artifact_ref_sync_states.values()
            if state.phase in ("running", "reloading")
        ]
        if not active:
            self._stop_artifact_ref_sync_spinner()
            return
        for state in active:
            state.frame += 1
        if not (
            self._file_completion_active
            and self._completion_kind == ARTIFACT_REF_COMPLETION_KIND
            and self._file_completion_candidates
        ):
            return
        first = self._file_completion_candidates[0]
        if not isinstance(first.metadata, ArtifactRefSyncCompletionMetadata):
            return
        context = self._get_artifact_ref_completion_context()
        if context is None or context.kind is None:
            return
        project = self._xprompt_arg_assist_project_from_text()
        row = self._artifact_ref_sync_row(project, context.kind)
        if row is None:
            return
        self._file_completion_candidates[0] = row
        self._update_file_completion_panel(context.prefix)

    # -- Row / new-payload lookup (consumed by the completion pipeline) ----

    def _artifact_ref_sync_row(
        self,
        project: str | None,
        kind: str,
    ) -> CompletionCandidate | None:
        state = self._artifact_ref_sync_states.get((project, kind))
        if state is None:
            return None
        verb = "cloning" if state.plan.mode == "clone" else "syncing"
        if state.phase in ("running", "reloading"):
            display_phase = "running"
            label = f"{verb} {state.plan.label} …"
            detail = ""
        elif state.phase == "settled_ok":
            display_phase = "settled_ok"
            label = f"{state.plan.label} synced · {len(state.new_payloads)} new"
            detail = ""
        else:
            display_phase = "settled_error"
            label = f"{state.plan.label} sync failed"
            detail = state.detail
        return CompletionCandidate(
            display=label,
            insertion="",
            is_dir=False,
            name="",
            metadata=ArtifactRefSyncCompletionMetadata(
                kind=kind,
                phase=display_phase,
                label=label,
                detail=detail,
                frame=state.frame,
            ),
        )

    def _artifact_ref_sync_new_payloads(
        self,
        project: str | None,
        kind: str,
    ) -> frozenset[str]:
        state = self._artifact_ref_sync_states.get((project, kind))
        return frozenset() if state is None else state.new_payloads


def _catalog_kind_payloads(
    catalog: ArtifactRefCompletionCatalog | None,
    kind: str,
) -> frozenset[str]:
    """Return the payload keys the warm catalog already indexes for *kind*.

    Commit/bug rows are session-local snapshots outside the static catalog, so
    they always diff to an empty set here; that only means the "new" badge
    never lights up for those kinds, not that the sync itself is skipped.
    """
    if catalog is None:
        return frozenset()
    return frozenset(catalog.payload_metadata.get(kind.casefold(), {}))


__all__ = ["ArtifactRefSyncMixin"]
