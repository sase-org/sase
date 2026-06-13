"""Multi-prompt agent launch mixin."""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING

from ._launch_tasks import LaunchTaskOutcome, launch_results_tuple

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ._types import PromptContext


class MultiPromptLaunchMixin:
    """Mixin providing multi-prompt agent launch."""

    def _launch_multi_prompt_agents(
        self,
        multi: object,
        ctx: PromptContext,
        vcs_ref: tuple[str, str] | None,
        submitted_prompt: str | None = None,
    ) -> None:
        """Launch each multi-prompt segment as a separate agent.

        Snapshots the launch context on the UI thread and dispatches the
        per-segment fan-out to a tracked Textual worker task so the event loop
        stays responsive during naming-wait polls. Successful launch results
        are batched into one exact artifact-delta reconcile.
        """
        from sase.agent.multi_prompt import MultiPrompt

        assert isinstance(multi, MultiPrompt)

        # Snapshot context on the UI thread so subsequent edits to
        # ``self._prompt_context`` do not leak into the worker.
        snap = dataclasses.replace(ctx)

        # Immediate feedback while agents launch in background.
        n = len(multi.segments)
        self.notify(f"Launching {n} agent(s) for {snap.display_name}...")  # type: ignore[attr-defined]

        self._submit_launch_task(  # type: ignore[attr-defined]
            display_name=f"launch multi-prompt {snap.display_name}",
            cl_name=snap.display_name,
            project_file=snap.project_file,
            task_callable=lambda: self._run_multi_prompt_launch(
                multi, snap, vcs_ref, submitted_prompt
            ),
        )

    def _run_multi_prompt_launch(
        self,
        multi: object,
        ctx: PromptContext,
        vcs_ref: tuple[str, str] | None,
        submitted_prompt: str | None = None,
    ) -> LaunchTaskOutcome:
        """Worker-thread body for :meth:`_launch_multi_prompt_agents`."""
        from sase.agent.multi_prompt import MultiPrompt
        from sase.agent.multi_prompt_launcher import (
            MultiPromptPartialLaunchError,
            launch_multi_prompt_agents,
        )

        assert isinstance(multi, MultiPrompt)

        try:
            results = launch_multi_prompt_agents(
                segments=multi.segments,
                local_xprompts=multi.local_xprompts,
                cl_name=ctx.display_name,
                project_file=ctx.project_file,
                project_name=ctx.project_name,
                is_home_mode=ctx.is_home_mode,
                vcs_ref=vcs_ref,
                default_bare_segments_to_home=ctx.is_home_mode,
                segment_template_groups=getattr(multi, "template_groups", None),
            )
            msg = f"Started {len(results)} agent(s) for {ctx.display_name}"
            return LaunchTaskOutcome(
                msg,
                results=launch_results_tuple(results),
            )
        except MultiPromptPartialLaunchError as exc:
            from sase.agent.partial_launch import rollback_partial_launch_results

            rollback_partial_launch_results(exc.results)
            _record_failed_multi_prompt_history(multi, submitted_prompt)
            log.exception("Partial multi-prompt launch failed; children terminated")
            return LaunchTaskOutcome(
                "Partial multi-prompt launch failed; spawned agents terminated",
                severity="error",
                request_agents_refresh=True,
            )
        except Exception:
            _record_failed_multi_prompt_history(multi, submitted_prompt)
            log.exception("Multi-prompt launch failed")
            return LaunchTaskOutcome(
                "Multi-prompt launch failed (see log)",
                severity="error",
            )


def _record_failed_multi_prompt_history(
    multi: object,
    submitted_prompt: str | None,
) -> None:
    """Record the submitted multi-prompt text as failed launch history."""
    if submitted_prompt is None:
        submitted_prompt = "\n---\n".join(getattr(multi, "segments", []))
    from sase.history.prompt import record_failed_launch_prompt

    record_failed_launch_prompt(submitted_prompt)
