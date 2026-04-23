"""Bulk agent launch mixin (launching agents for many marked changespecs)."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import TYPE_CHECKING

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sase.ace.changespec import ChangeSpec

    from ._types import PromptContext


class BulkLaunchMixin:
    """Mixin providing bulk agent launch across marked changespecs."""

    # State set by AgentLaunchMixin / PromptBarMixin when entering bulk mode.
    _bulk_changespecs: list[ChangeSpec] | None
    # Sibling-mixin state (resolved at runtime via MRO).
    _prompt_context: PromptContext | None
    marked_indices: set[int]

    def _launch_bulk_agents(self, prompt: str) -> None:
        """Launch agents for all bulk changespecs.

        Args:
            prompt: The user's prompt for all agents.
        """
        if not self._bulk_changespecs:
            self.notify("No bulk changespecs", severity="error")  # type: ignore[attr-defined]
            return

        changespecs = self._bulk_changespecs
        self._bulk_changespecs = None
        self._prompt_context = None

        # Clear marks and refresh display immediately (UI state)
        self.marked_indices = set()
        self._refresh_display()  # type: ignore[attr-defined]

        n = len(changespecs)

        def _run() -> None:
            try:
                from sase.workspace_provider import detect_workflow_type
                from sase.core.time import generate_timestamp
                from sase.running_field import (
                    get_first_available_axe_workspace,
                    get_workspace_directory_for_num,
                )

                launched_count = 0
                failed_count = 0

                for i, cs in enumerate(changespecs):
                    if i > 0:
                        time.sleep(1)
                    project_name = cs.project_basename
                    cl_name = cs.name

                    project_file = os.path.expanduser(
                        f"~/.sase/projects/{project_name}/{project_name}.gp"
                    )

                    if not os.path.isfile(project_file):
                        log.warning("No project file for %s", cl_name)
                        failed_count += 1
                        continue

                    try:
                        workspace_num = get_first_available_axe_workspace(project_file)
                        timestamp = generate_timestamp()
                        workflow_name = f"ace(run)-{timestamp}"
                        workspace_dir, _ = get_workspace_directory_for_num(
                            workspace_num, project_name
                        )
                    except RuntimeError as e:
                        log.warning("Workspace error for %s: %s", cl_name, e)
                        failed_count += 1
                        continue

                    # Detect VCS type and build per-CL prompt with prefix
                    workflow_type = detect_workflow_type(project_file)
                    cl_prompt = f"#{workflow_type}:{cl_name} {prompt}"

                    self._launch_background_agent(  # type: ignore[attr-defined]
                        cl_name=cl_name,
                        project_file=project_file,
                        workspace_dir=workspace_dir,
                        workspace_num=workspace_num,
                        workflow_name=workflow_name,
                        prompt=cl_prompt,
                        timestamp=timestamp,
                        update_target="" if workflow_type else cl_name,
                        project_name=project_name,
                        history_sort_key=cl_name,
                        vcs_ref=(workflow_type, cl_name),
                    )
                    launched_count += 1

                self.call_later(self._schedule_agents_async_refresh)  # type: ignore[attr-defined]

                if failed_count > 0:
                    msg = f"Started {launched_count} agent(s), {failed_count} failed"
                    self.call_later(  # type: ignore[attr-defined]
                        lambda: self.notify(msg, severity="warning")  # type: ignore[attr-defined]
                    )
                else:
                    msg = f"Started {launched_count} agent(s)"
                    self.call_later(lambda: self.notify(msg))  # type: ignore[attr-defined]
            except Exception:
                log.exception("Bulk launch failed")
                self.call_later(  # type: ignore[attr-defined]
                    lambda: self.notify(  # type: ignore[attr-defined]
                        "Bulk launch failed (see log)", severity="error"
                    )
                )

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        self.notify(f"Launching {n} agent(s)...")  # type: ignore[attr-defined]
