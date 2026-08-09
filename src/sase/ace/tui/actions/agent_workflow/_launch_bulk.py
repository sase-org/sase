"""Bulk agent launch mixin (launching agents for many marked patches)."""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING

from ._launch_tasks import LaunchSeverity, LaunchTaskOutcome, launch_results_tuple
from ..failure_messages import with_log_panel_hint

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sase.agent.launch_types import AgentLaunchResult

    from sase.ace.patch import Patch

    from ._types import PromptContext


class BulkLaunchMixin:
    """Mixin providing bulk agent launch across marked patches."""

    # State set by AgentLaunchMixin / PromptBarMixin when entering bulk mode.
    _bulk_patches: list[Patch] | None
    # Sibling-mixin state (resolved at runtime via MRO).
    _prompt_context: PromptContext | None
    marked_indices: set[int]

    def _launch_bulk_agents(self, prompt: str) -> None:
        """Launch agents for all bulk patches.

        Args:
            prompt: The user's prompt for all agents.
        """
        bulk_patches = getattr(self, "_bulk_patches", None)
        if bulk_patches is None:
            bulk_patches = getattr(
                self,
                "_bulk_changespecs",  # legacy compatibility alias
                None,
            )
        if not bulk_patches:
            self.notify("No bulk patches", severity="error")  # type: ignore[attr-defined]
            return

        # Snapshot the bulk-patch list on the UI thread so the worker
        # cannot observe later mutations.
        patches = list(bulk_patches)
        self._bulk_patches = None
        if hasattr(self, "_bulk_patches"):
            self._bulk_patches = None  # type: ignore[attr-defined]
        if hasattr(self, "_bulk_changespecs"):
            self._bulk_changespecs = None  # type: ignore[attr-defined] # legacy compatibility alias
        self._prompt_context = None

        # Clear marks and refresh display immediately (UI state)
        self.marked_indices = set()
        self._refresh_display()  # type: ignore[attr-defined]

        n = len(patches)

        self.notify(f"Launching {n} agent(s)...")  # type: ignore[attr-defined]
        self._submit_launch_task(  # type: ignore[attr-defined]
            display_name=f"launch bulk {n} Patches",
            cl_name=f"bulk {n} Patches",
            project_file="",
            task_callable=lambda: self._run_bulk_launch(prompt, patches),
            submitted_prompt=prompt,
        )

    def _run_bulk_launch(self, prompt: str, patches: list[Patch]) -> LaunchTaskOutcome:
        """Worker-thread body for :meth:`_launch_bulk_agents`."""
        try:
            from sase.agent.launch_timing import LaunchTimingRecorder
            from sase.core.agent_launch_facade import reserve_launch_timestamp_batch
            from sase.core.paths import sase_projects_dir
            from sase.running_field import (
                get_first_available_axe_workspace,
                get_workspace_directory_for_num,
            )
            from sase.workspace_provider import detect_workflow_type

            timer = LaunchTimingRecorder(
                "tui_agent_launch_fanout",
                {"fanout_kind": "bulk", "slot_count": len(patches)},
                durable=True,
            )
            launched_count = 0
            failed_count = 0
            launch_results: list[AgentLaunchResult] = []

            for i, cs in enumerate(patches):
                if i > 0:
                    with timer.stage("fanout_sleep", seconds=1.0, slot_index=i):
                        time.sleep(1)
                project_name = cs.project_basename
                cl_name = cs.name

                from sase.ace.patch.project_spec_path import (
                    preferred_project_spec_path,
                )

                project_dir = str(sase_projects_dir() / project_name)
                project_file = preferred_project_spec_path(project_dir, project_name)

                if not os.path.isfile(project_file):
                    log.warning("No project file for %s", cl_name)
                    _log_bulk_item_failure(
                        FileNotFoundError(
                            f"No project file for {cl_name}: {project_file}"
                        ),
                        cl_name=cl_name,
                        project_name=project_name,
                        prompt=prompt,
                        slot_index=i,
                        slot_count=len(patches),
                        stage="project_file",
                        project_file=project_file,
                    )
                    failed_count += 1
                    continue

                try:
                    with timer.stage("workspace_allocation", slot_index=i):
                        workspace_num = get_first_available_axe_workspace(project_file)
                        timestamp = reserve_launch_timestamp_batch(1)[0]
                        workflow_name = f"ace(run)-{timestamp}"
                        workspace_dir, _ = get_workspace_directory_for_num(
                            workspace_num, project_name
                        )
                except RuntimeError as e:
                    log.warning("Workspace error for %s: %s", cl_name, e)
                    _log_bulk_item_failure(
                        e,
                        cl_name=cl_name,
                        project_name=project_name,
                        prompt=prompt,
                        slot_index=i,
                        slot_count=len(patches),
                        stage="workspace_allocation",
                        project_file=project_file,
                    )
                    failed_count += 1
                    continue

                # Detect VCS type and build per-Patch prompt with prefix
                workflow_type = detect_workflow_type(project_file)
                cl_prompt = f"#{workflow_type}:{cl_name} {prompt}"

                with timer.stage("low_level_spawn", slot_index=i):
                    launch_result = self._launch_background_agent(  # type: ignore[attr-defined]
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
                launch_results.append(launch_result)
                launched_count += 1

            if failed_count > 0:
                msg = f"Started {launched_count} agent(s), {failed_count} failed"
                severity: LaunchSeverity | None = "warning"
                # Any failed slot means the shared prompt was not fully launched;
                # preserve it in the stash so it stays recoverable.
                from sase.agent.failed_launch_prompt_stash import (
                    stash_failed_launch_prompt,
                )

                stash_failed_launch_prompt(prompt)
            else:
                msg = f"Started {launched_count} agent(s)"
                severity = None
            timer.finish(outcome="ok", launched=launched_count, failed=failed_count)
            return LaunchTaskOutcome(
                msg,
                results=launch_results_tuple(launch_results),
                severity=severity,
            )
        except Exception as exc:
            log.exception("Bulk launch failed")
            from sase.agent.failed_launch_prompt_stash import (
                stash_failed_launch_prompt,
            )
            from sase.logs import log_launch_failure

            stash_failed_launch_prompt(prompt)
            log_launch_failure(
                kind="bulk",
                display_name=f"bulk {len(patches)} Patches",
                exc=exc,
                prompt_preview=prompt,
                slot_count=len(patches),
            )
            # A mid-loop failure may have already spawned earlier Patches;
            # without results, only a refresh makes them visible.
            return LaunchTaskOutcome(
                with_log_panel_hint("Bulk launch failed"),
                severity="error",
                request_agents_refresh=True,
            )


def _log_bulk_item_failure(
    exc: BaseException,
    *,
    cl_name: str,
    project_name: str,
    prompt: str,
    slot_index: int,
    slot_count: int,
    stage: str,
    project_file: str,
) -> None:
    """Durably record one skipped patch in a bulk launch."""
    from sase.logs import log_launch_failure

    log_launch_failure(
        kind="bulk",
        display_name=cl_name,
        exc=exc,
        project=project_name,
        prompt_preview=prompt,
        slot_index=slot_index,
        slot_count=slot_count,
        stage=stage,
        project_file=project_file,
    )
