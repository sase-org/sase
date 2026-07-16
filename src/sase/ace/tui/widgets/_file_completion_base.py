"""Shared state and panel helpers for prompt file completion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from textual.worker import Worker, WorkerState

from sase.ace.tui.widgets._file_completion_context import FileCompletionContextMixin
from sase.ace.tui.widgets.file_completion import MAX_VISIBLE, CompletionCandidate
from sase.ace.tui.widgets.vcs_ref_completion import (
    VCS_REF_COMPLETION_KIND,
    vcs_ref_completion_title,
)
from sase.ace.tui.widgets.vcs_repo_completion import (
    VCS_REPO_COMPLETION_KIND,
    vcs_repo_completion_candidates,
    vcs_repo_completion_title,
)
from sase.xprompt.vcs_project_completion import build_vcs_project_completion_entries
from sase.xprompt.vcs_repo_completion import (
    VcsRepoFetchResult,
    VcsRepoTrigger,
    fetch_repo_candidates,
)

if TYPE_CHECKING:
    from sase.ace.tui.agent_completion import AgentCompletionCandidate
    from sase.ace.tui.widgets.xprompt_arg_assist import (
        ActiveXPromptArgHint,
        XPromptAssistEntry,
    )
    from sase.ace.tui.widgets.placeholder_completion import (
        PlaceholderCompletionResult,
    )
    from sase.xprompt.vcs_ref_completion import VcsRefTrigger


@dataclass(frozen=True)
class _VcsRepoCompletionWorkerResult:
    """Result returned by a repository completion fetch worker."""

    workflow: str
    namespace: str
    result: VcsRepoFetchResult

    @property
    def key(self) -> tuple[str, str]:
        return (self.workflow, self.namespace)


class FileCompletionBaseMixin(FileCompletionContextMixin):
    """Mixin providing shared completion state helpers."""

    if TYPE_CHECKING:
        _file_completion_candidates: list[CompletionCandidate]
        _file_completion_index: int
        _file_completion_active: bool
        _completion_kind: str
        _agent_completion_candidates: list[AgentCompletionCandidate] | None
        _active_xprompt_arg_hint: ActiveXPromptArgHint | None
        _vcs_repo_completion_key: tuple[str, str] | None
        _vcs_repo_completion_result: VcsRepoFetchResult | None
        _vcs_repo_completion_inflight: set[tuple[str, str]]
        _vcs_ref_completion_has_namespaces: bool

        def _find_prompt_bar(self) -> Any: ...
        def _placeholder_completion_at_cursor(
            self,
        ) -> PlaceholderCompletionResult | None: ...

        def _replace_via_keyboard(
            self, insert: str, start: tuple[int, int], end: tuple[int, int]
        ) -> None: ...

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _location_from_absolute(self, offset: int) -> tuple[int, int]: ...
        def _clear_xprompt_arg_hint(self) -> None: ...
        def _get_vcs_ref_trigger(self) -> VcsRefTrigger | None: ...
        def _get_vcs_repo_trigger(self) -> VcsRepoTrigger | None: ...
        def _note_optional_xprompt_spacer(self, entry: XPromptAssistEntry) -> None: ...
        def _show_xprompt_arg_hint(self, hint: ActiveXPromptArgHint) -> None: ...
        def _get_xprompt_arg_assist_entries(self) -> list[XPromptAssistEntry]: ...
        def _get_warm_xprompt_arg_assist_entries(
            self,
        ) -> list[XPromptAssistEntry] | None: ...
        def _build_warm_xprompt_completion_candidates(
            self,
            token: str,
        ) -> tuple[list[CompletionCandidate], str] | None: ...
        def _refresh_xprompt_arg_hint_from_cursor(self) -> None: ...
        def _expand_snippet_template_at_range(
            self,
            template: str,
            start: tuple[int, int],
            end: tuple[int, int],
        ) -> bool: ...

    def _update_file_completion_panel(self, token: str) -> None:
        """Sync completion UI with the current completion state."""
        bar = self._find_prompt_bar()
        if bar is None:
            return

        if not self._file_completion_active or not self._file_completion_candidates:
            bar.hide_file_completions()
            return

        rows = self._file_completion_candidates
        total = len(rows)
        if total <= MAX_VISIBLE:
            scroll_offset = 0
        else:
            half = MAX_VISIBLE // 2
            scroll_offset = max(
                0, min(self._file_completion_index - half, total - MAX_VISIBLE)
            )
        display_token = token
        if self._completion_kind == VCS_REF_COMPLETION_KIND:
            ref_trigger = self._get_vcs_ref_trigger()
            if ref_trigger is not None:
                display_token = vcs_ref_completion_title(
                    ref_trigger.workflow,
                    has_namespaces=self._vcs_ref_completion_has_namespaces,
                )
        elif self._completion_kind == VCS_REPO_COMPLETION_KIND:
            repo_trigger = self._get_vcs_repo_trigger()
            if repo_trigger is not None:
                display_token = vcs_repo_completion_title(
                    self._vcs_repo_completion_result,
                    workflow=repo_trigger.workflow,
                    namespace=repo_trigger.namespace,
                )

        bar.show_file_completions(
            display_token,
            rows,
            self._file_completion_index,
            scroll_offset,
            completion_kind=self._completion_kind,
        )

    def _clear_file_completion(self, *, clear_xprompt_arg_hint: bool = True) -> None:
        """Reset path completion state and hide panel."""
        self._file_completion_active = False
        self._file_completion_candidates = []
        self._file_completion_index = 0
        self._completion_kind = "file"
        self._agent_completion_candidates = None
        self._vcs_repo_completion_key = None
        self._vcs_repo_completion_result = None
        self._vcs_ref_completion_has_namespaces = False
        self._update_file_completion_panel("")
        if clear_xprompt_arg_hint:
            self._clear_xprompt_arg_hint()

    def _schedule_vcs_repo_completion_fetch(self, trigger: VcsRepoTrigger) -> None:
        """Fetch repo candidates in a background worker with key dedupe."""
        key = (trigger.workflow, trigger.namespace)
        if key in self._vcs_repo_completion_inflight:
            return
        self._vcs_repo_completion_inflight.add(key)

        def task() -> _VcsRepoCompletionWorkerResult:
            return _VcsRepoCompletionWorkerResult(
                workflow=trigger.workflow,
                namespace=trigger.namespace,
                result=fetch_repo_candidates(trigger.workflow, trigger.namespace),
            )

        self.run_worker(
            task,
            name=f"prompt-vcs-repo:{trigger.workflow}:{trigger.namespace}",
            group="prompt-vcs-repo",
            thread=True,
        )

    def _apply_vcs_repo_completion_result(
        self,
        worker_result: _VcsRepoCompletionWorkerResult,
    ) -> None:
        """Refresh an active repo menu from a completed worker result."""
        trigger = self._get_vcs_repo_trigger()
        if (
            trigger is None
            or (trigger.workflow, trigger.namespace) != worker_result.key
        ):
            return
        if (
            not self._file_completion_active
            or self._completion_kind != VCS_REPO_COMPLETION_KIND
        ):
            return

        candidates, used_placeholder = vcs_repo_completion_candidates(
            worker_result.result,
            trigger.query,
            trigger.namespace,
        )
        if not candidates and not used_placeholder:
            self._clear_file_completion()
            return

        previous = None
        if self._file_completion_candidates:
            previous = self._file_completion_candidates[
                self._file_completion_index
            ].name
        self._vcs_repo_completion_key = worker_result.key
        self._vcs_repo_completion_result = worker_result.result
        self._file_completion_candidates = candidates
        self._file_completion_index = 0
        if previous is not None:
            for i, candidate in enumerate(candidates):
                if candidate.name == previous:
                    self._file_completion_index = i
                    break
        self._update_file_completion_panel(trigger.query)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle repository-completion fetch worker results."""
        if event.worker.group != "prompt-vcs-repo":
            handler = getattr(super(), "on_worker_state_changed", None)
            if callable(handler):
                handler(event)
            return

        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if isinstance(result, _VcsRepoCompletionWorkerResult):
                self._vcs_repo_completion_inflight.discard(result.key)
                self._apply_vcs_repo_completion_result(result)
                return
        elif event.state in (WorkerState.ERROR, WorkerState.CANCELLED):
            # The key is encoded in the worker name after the first prefix.
            suffix = event.worker.name.removeprefix("prompt-vcs-repo:")
            workflow, sep, namespace = suffix.partition(":")
            if sep:
                self._vcs_repo_completion_inflight.discard((workflow, namespace))

        handler = getattr(super(), "on_worker_state_changed", None)
        if callable(handler):
            handler(event)

    def _snapshot_agent_completion_candidates(self) -> list[AgentCompletionCandidate]:
        """Return the per-menu visible-agent completion snapshot."""
        cached = self._agent_completion_candidates
        if cached is not None:
            return cached

        provider = getattr(self.app, "visible_agent_completion_candidates", None)
        if not callable(provider):
            self._agent_completion_candidates = []
            return self._agent_completion_candidates

        try:
            self._agent_completion_candidates = list(provider())
        except Exception:
            self._agent_completion_candidates = []
        return self._agent_completion_candidates

    def _warm_vcs_project_completion_catalog(self) -> None:
        """Warm the ``#+`` project catalog off the keystroke path.

        The catalog build touches disk (project enumeration + provider
        detection), so it must never run synchronously inside key handling
        (``sase/memory/tui_perf.md``). Building once in a background thread
        populates the module-level cache in
        :mod:`sase.xprompt.vcs_project_completion`, so the first ``#+`` opens
        the menu instantly. Gated on the real app's completion-settings
        capability so lightweight test harnesses skip it.
        """
        if getattr(self, "_vcs_project_catalog_warmed", False):
            return
        if not callable(getattr(self.app, "get_prompt_completion_settings", None)):
            return
        self._vcs_project_catalog_warmed = True
        self.run_worker(
            _warm_vcs_completion_catalogs,
            name="prompt-vcs-project-catalog",
            thread=True,
        )


def _warm_vcs_completion_catalogs() -> None:
    """Warm VCS project and ref-root namespace completion caches."""
    build_vcs_project_completion_entries()

    from sase.workspace_provider import get_workflow_names
    from sase.xprompt.vcs_ref_completion import vcs_ref_namespaces_by_workflow

    vcs_ref_namespaces_by_workflow(get_workflow_names())
