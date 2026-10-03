"""Show / save / unmount / detach lifecycle for the prompt input bar."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from sase.ace.patch.project_spec_path import preferred_project_spec_path
from sase.core.paths import sase_projects_dir

from ._types import (
    PromptContext,
    begin_prompt_session,
    invalidate_prompt_session,
)

if TYPE_CHECKING:
    from ...widgets.prompt_input_bar import PromptInputBar


class PromptBarLifecycleMixin:
    """Mount, cancelled-save, unmount, and synchronous detach for the bar."""

    _prompt_context: PromptContext | None
    # Phase ``tick-compare-skip``: matches the ``EventHandlersBase``
    # declaration; maintained by ``PromptInputBar`` mount/unmount hooks
    # and ``_detach_prompt_bar`` below.
    _active_prompt_bar: PromptInputBar | None

    def _show_prompt_input_bar(
        self,
        project_name: str | None,
        cl_name: str | None,
        update_target: str,
        history_sort_key: str,
    ) -> None:
        """Show prompt input bar for agent workflow.

        Args:
            project_name: The project name.
            cl_name: The selected Patch name (or None for project-only).
            update_target: What to checkout (Patch name or "p4head").
            history_sort_key: Launch context label propagated to spawned agents.
        """
        from sase.workflows.commit.project_file_utils import create_project_file
        from sase.core.time import generate_timestamp

        from ...widgets import PromptInputBar

        if project_name is None:
            self.notify("No project selected", severity="error")  # type: ignore[attr-defined]
            return

        project_dir = str(sase_projects_dir() / project_name)
        project_file = preferred_project_spec_path(project_dir, project_name)

        # Create project file if it doesn't exist
        if not os.path.isfile(project_file):
            if not create_project_file(project_name):
                self.notify(  # type: ignore[attr-defined]
                    f"Failed to create project file: {project_file}",
                    severity="error",
                )
                return

        timestamp = generate_timestamp()
        workflow_name = f"ace(run)-{timestamp}"
        display_name = cl_name or project_name

        # Workspace allocation happens at spawn time so launch can retry if
        # another agent claims the slot between preflight and subprocess spawn.
        workspace_num = 0
        workspace_dir = ""

        # Remove any existing prompt bar before mounting a new one.
        # Must happen before overwriting _prompt_context so the old bar's
        # text is saved with the old context.
        self._unmount_prompt_bar()
        # Phase ``space-hot-spare``: a fresh mount never reuses the spare.
        try:
            self._discard_prompt_bar_spare()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - spare discard is best-effort.
            pass

        # Store context for when prompt is submitted
        begin_prompt_session(
            self,
            PromptContext(
                project_name=project_name,
                cl_name=cl_name,
                project_file=project_file,
                workspace_dir=workspace_dir,
                workspace_num=workspace_num,
                workflow_name=workflow_name,
                timestamp=timestamp,
                history_sort_key=history_sort_key,
                display_name=display_name,
                update_target=update_target,
            ),
        )

        # Immediately show prompt input bar (workspace prep happens in runner)
        self.mount(PromptInputBar(id="prompt-input-bar"))  # type: ignore[attr-defined]

    def _save_bar_text_as_cancelled(self, bar: object) -> str:
        """Extract text from bar and save to history as cancelled.

        Safe to call even if the prompt was already saved — add_or_update_prompt
        never downgrades a non-cancelled entry to cancelled.
        """
        try:
            text = bar.current_prompt_text()  # type: ignore[attr-defined]
        except Exception:
            return ""
        return self._save_text_as_cancelled(text)

    def _save_text_as_cancelled(
        self, text: str, *, record_segments: bool = True
    ) -> str:
        """Save *text* to prompt history as cancelled, with file references.

        Shared by the whole-bar cancel safety net and the Phase 4 per-pane
        ``<ctrl+c>`` cancel, which records only the cancelled pane's text.
        Empty / whitespace-only text is ignored. ``record_segments`` lets the
        all-pane cancel path preserve the joined stack as one history row, and
        ``add_or_update_prompt`` never downgrades a non-cancelled entry to
        cancelled. A ``generated`` prompt session (member relaunch,
        mentor apply) records nothing here; file references may still stay.
        """
        text = text.strip()
        if not text:
            return ""

        from sase.history.prompt import is_recordable_prompt

        from ._types import current_prompt_session

        recorded = is_recordable_prompt(text)
        try:
            session = current_prompt_session(self)
            session_origin = session.prompt_origin if session is not None else "typed"
        except Exception:
            session_origin = "typed"
        if session_origin != "generated":
            from sase.history.prompt import add_or_update_prompt

            if record_segments:
                add_or_update_prompt(text, cancelled=True, origin="typed")
            else:
                add_or_update_prompt(
                    text, cancelled=True, record_segments=False, origin="typed"
                )

        from sase.history.file_references import (
            extract_recordable_file_refs,
            record_file_references,
        )

        refs = extract_recordable_file_refs(text)
        if refs:
            record_file_references(refs)
        if session_origin == "generated":
            return ""
        return text if recorded else ""

    def _unmount_prompt_bar(self) -> str:
        """Unmount the prompt input bar if present, saving any unsaved text.

        Cancel/dismiss path. Use ``_unmount_prompt_bar_after_submit()`` from
        the successful-submit path so the just-submitted prompt is not
        re-written to history as ``cancelled=True``.
        """
        from ._prompt_bar_stash_store import mounted_prompt_bar

        bar = mounted_prompt_bar(self)
        if bar is None:
            return ""  # Bar not present

        # Save any non-trivial text as cancelled before removing the bar.
        # This is the safety net — every dismissal code path flows through
        # here, so no prompt text can ever be silently lost. Save before
        # invalidating so a generated prompt session still skips its write.
        stored_text = self._save_bar_text_as_cancelled(bar)
        invalidate_prompt_session(self, clear_context=False)
        self._detach_prompt_bar(bar)
        return stored_text

    def _unmount_prompt_bar_after_submit(self) -> None:
        """Unmount the prompt input bar after a successful submit.

        Skips the ``_save_bar_text_as_cancelled`` safety net: on a
        successful submit the launch path itself writes the final
        non-cancelled history entry, and routing through the cancel path
        would race that write with a stale ``cancelled=True`` entry.
        """
        self._unmount_prompt_bar_without_cancel_save()

    def _unmount_prompt_bar_without_cancel_save(self) -> None:
        """Unmount the prompt input bar without the cancelled-history safety net."""
        from ._prompt_bar_stash_store import mounted_prompt_bar

        bar = mounted_prompt_bar(self)
        if bar is None:
            return  # Bar not present

        invalidate_prompt_session(self, clear_context=False)
        self._detach_prompt_bar(bar)

    def _detach_prompt_bar(self, bar: object) -> None:
        # Phase ``tick-compare-skip``: withdraw the explicit prompt-active
        # reference synchronously. The widget's own ``on_unmount`` repeats
        # this once the async removal lands; clearing here keeps the next
        # per-second tick truthful without waiting for it.
        try:
            if getattr(self, "_active_prompt_bar", None) is bar:
                self._active_prompt_bar = None
        except Exception:  # noqa: BLE001 - explicit state is best-effort.
            pass
        # Phase ``post-open-quiet``: catalog warms that landed while the prompt
        # was active deferred the Agents-detail repaint; flush it once here so
        # dismissal shows the fresh detail without an extra key-to-paint cost.
        flush_detail = getattr(
            self, "_flush_pending_selected_agent_semantic_refresh", None
        )
        if callable(flush_detail):
            try:
                flush_detail()
            except Exception:  # noqa: BLE001 - detail repaint is best-effort.
                pass
        # Detaching the bar dismisses its session: drop any pending
        # `<space>` late prefill so a later publish cannot resurrect text
        # into a newer session. `invalidate_prompt_session` already clears
        # this on its paths; this covers detaches that bypass it.
        try:
            self._pending_space_prefill = None  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - pending state is best-effort.
            pass
        # Transfer focus to a live widget *before* the forcible detach below.
        # Without this, Screen.focused can be left pointing at the PromptTextArea
        # that is about to be ripped out of the DOM, swallowing the next keys
        # the user types (e.g. j/k right after <enter>).
        self._transfer_focus_off_prompt_bar(bar)  # type: ignore[attr-defined]

        # Synchronously detach from parent's node list so the ID is freed
        # immediately. Without this, bar.remove() only schedules async
        # removal and a subsequent mount() would hit DuplicateIds.
        parent = bar._parent  # type: ignore[attr-defined]
        if parent is not None:
            parent._nodes._remove(bar)
        bar.remove()  # type: ignore[attr-defined]
        # Phase ``space-hot-spare``: the revealed bar is never recycled.
        # Schedule the next idle spare only after this removal, and only
        # when the enable flag is set.
        try:
            self._schedule_prompt_bar_spare(reason="detached")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - spare scheduling is best-effort.
            pass
