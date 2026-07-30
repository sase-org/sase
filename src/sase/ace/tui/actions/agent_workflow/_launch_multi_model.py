"""Prompt fan-out launch mixin (``%alt(...)`` / ``%{...}`` directives)."""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from sase.core.paths import sase_subdir

from ._launch_tasks import LaunchTaskOutcome, launch_results_tuple
from ..failure_messages import with_log_panel_hint

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sase.core.agent_launch_wire import LaunchFanoutPlanWire
    from sase.xprompt.models import XPrompt

    from ._types import PromptContext


class MultiModelLaunchMixin:
    """Mixin providing prompt fan-out agent launch."""

    def _launch_multi_model_agents(
        self,
        model_prompts: list[str],
        ctx: PromptContext,
        vcs_ref: tuple[str, str] | None,
        has_wait: bool,
        fanout_kind: str = "model",
        local_xprompts: dict[str, XPrompt] | None = None,
        submitted_xprompt: str | None = None,
        fanout_plan: LaunchFanoutPlanWire | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> None:
        """Launch one agent per slot for a prompt fan-out directive.

        Each prompt in *model_prompts* is either a source prompt paired with
        *fanout_plan* or a compatibility list of already-expanded slot prompts.

        Args:
            model_prompts: Per-slot prompts to launch.
            ctx: The prompt context with project/workspace info.
            vcs_ref: Resolved VCS reference, if any.
            has_wait: Whether the prompt has ``%wait`` directives.
            fanout_kind: Launch fan-out kind used for telemetry.
            local_xprompts: Local prompt definitions parsed from frontmatter.
        """
        n = len(model_prompts)
        snap = dataclasses.replace(ctx)
        local_xprompts = dict(local_xprompts or {})

        slot_count = len(fanout_plan.slots) if fanout_plan is not None else n
        self.notify(  # type: ignore[attr-defined]
            f"Launching {slot_count} agent(s) for {snap.display_name}..."
        )
        self._submit_launch_task(  # type: ignore[attr-defined]
            display_name=f"launch fanout {snap.display_name}",
            cl_name=snap.display_name,
            project_file=snap.project_file,
            task_callable=lambda: self._run_multi_model_launch(
                model_prompts,
                snap,
                vcs_ref,
                has_wait,
                fanout_kind,
                local_xprompts,
                submitted_xprompt,
                fanout_plan,
                extra_env,
            ),
            submitted_prompt=submitted_xprompt,
        )

    def _run_multi_model_launch(
        self,
        model_prompts: list[str],
        ctx: PromptContext,
        vcs_ref: tuple[str, str] | None,
        has_wait: bool,
        fanout_kind: str = "model",
        local_xprompts: dict[str, XPrompt] | None = None,
        submitted_xprompt: str | None = None,
        fanout_plan: LaunchFanoutPlanWire | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> LaunchTaskOutcome:
        """Worker-thread body for :meth:`_launch_multi_model_agents`."""
        from sase.agent.launch_timing import LaunchTimingRecorder

        slot_count = (
            len(fanout_plan.slots) if fanout_plan is not None else len(model_prompts)
        )
        timer = LaunchTimingRecorder(
            "tui_agent_launch_fanout",
            {
                "fanout_kind": fanout_kind,
                "slot_count": slot_count,
                "project_name": ctx.project_name,
                "home_mode": ctx.is_home_mode,
            },
            durable=True,
        )
        from sase.agent.multi_prompt_launcher import (
            MultiPromptPartialLaunchError,
            launch_multi_prompt_agents,
        )

        try:
            with timer.stage(
                "launch_multi_prompt_agents",
                slot_count=slot_count,
                deferred_workspace=has_wait,
            ):
                results = launch_multi_prompt_agents(
                    segments=model_prompts,
                    local_xprompts=local_xprompts or {},
                    cl_name=ctx.display_name,
                    project_file=ctx.project_file,
                    project_name=ctx.project_name,
                    is_home_mode=ctx.is_home_mode,
                    vcs_ref=vcs_ref,
                    default_bare_segments_to_home=ctx.is_home_mode,
                    preplanned_fanout_plans=(
                        [fanout_plan] if fanout_plan is not None else None
                    ),
                    extra_env=extra_env,
                )

            msg = f"Started {len(results)} agent(s) for {ctx.display_name}"
            timer.finish(outcome="ok", launched=len(results))
            return LaunchTaskOutcome(
                msg,
                results=launch_results_tuple(results),
            )
        except MultiPromptPartialLaunchError as exc:
            from sase.agent.partial_launch import rollback_partial_launch_results

            rollback_partial_launch_results(exc.results)
            timer.finish(outcome="error")
            log.exception("Prompt fan-out launch failed")
            _record_failed_fanout_history(model_prompts, submitted_xprompt)
            _record_fanout_launch_failure(
                exc,
                ctx=ctx,
                vcs_ref=vcs_ref,
                has_wait=has_wait,
                fanout_kind=fanout_kind,
                slot_count=slot_count,
                submitted_xprompt=submitted_xprompt,
            )
            return LaunchTaskOutcome(
                with_log_panel_hint(
                    "Prompt fan-out launch failed; spawned agents terminated"
                ),
                severity="error",
                request_agents_refresh=True,
                refresh_notifications=True,
            )
        except Exception as exc:
            timer.finish(outcome="error")
            log.exception("Prompt fan-out launch failed")
            _record_failed_fanout_history(model_prompts, submitted_xprompt)
            _record_fanout_launch_failure(
                exc,
                ctx=ctx,
                vcs_ref=vcs_ref,
                has_wait=has_wait,
                fanout_kind=fanout_kind,
                slot_count=slot_count,
                submitted_xprompt=submitted_xprompt,
            )
            return LaunchTaskOutcome(
                with_log_panel_hint("Prompt fan-out launch failed"),
                severity="error",
                refresh_notifications=True,
            )


def _record_failed_fanout_history(
    model_prompts: list[str],
    submitted_xprompt: str | None,
) -> None:
    """Record the source prompt for a failed fan-out launch."""
    from sase.history.prompt import record_failed_launch_prompt

    record_failed_launch_prompt(
        submitted_xprompt
        if submitted_xprompt is not None
        else "\n---\n".join(model_prompts)
    )


def _record_fanout_launch_failure(
    exc: BaseException,
    *,
    ctx: PromptContext,
    vcs_ref: tuple[str, str] | None,
    has_wait: bool,
    fanout_kind: str,
    slot_count: int,
    submitted_xprompt: str | None = None,
) -> None:
    """Persist a compact notification for fan-out failures before agents exist."""
    try:
        from datetime import datetime

        from sase.core.time import get_timezone
        from sase.logs import log_launch_failure
        from sase.notifications import Notification, append_notification

        # Route the failure detail through the shared launch-failure logger so
        # fan-out lands in the same canonical log as every other launch kind.
        log_launch_failure(
            kind="fanout",
            display_name=ctx.display_name,
            exc=exc,
            project=ctx.project_name,
            workspace_num=ctx.workspace_num,
            prompt_preview=submitted_xprompt,
            fanout_kind=fanout_kind,
            slot_count=slot_count,
            home_mode=ctx.is_home_mode,
            deferred_workspace=has_wait,
            vcs_ref=None if vcs_ref is None else f"{vcs_ref[0]}:{vcs_ref[1]}",
        )

        exc_summary = f"{type(exc).__name__}: {exc}"
        report_path = _write_fanout_failure_report(
            exc_summary,
            ctx=ctx,
            vcs_ref=vcs_ref,
            has_wait=has_wait,
            fanout_kind=fanout_kind,
            slot_count=slot_count,
            submitted_xprompt=submitted_xprompt,
        )
        notes = [
            f"Prompt fan-out launch failed for {ctx.display_name}",
            exc_summary,
            (
                f"kind={fanout_kind} slots={slot_count} "
                f"project={ctx.project_name} home_mode={ctx.is_home_mode}"
            ),
        ]
        append_notification(
            Notification(
                id=str(uuid4()),
                timestamp=datetime.now(get_timezone()).isoformat(),
                sender="user-agent",
                notes=notes,
                files=[str(report_path)],
                action="ViewErrorReport",
                action_data={
                    "error_report_path": str(report_path),
                    "source": "tui_prompt_fanout",
                    "fanout_kind": fanout_kind,
                    "slot_count": str(slot_count),
                    "project_name": ctx.project_name,
                    "display_name": ctx.display_name,
                },
            )
        )
    except Exception:
        log.warning(
            "Failed to record prompt fan-out failure notification", exc_info=True
        )


def _write_fanout_failure_report(
    exc_summary: str,
    *,
    ctx: PromptContext,
    vcs_ref: tuple[str, str] | None,
    has_wait: bool,
    fanout_kind: str,
    slot_count: int,
    submitted_xprompt: str | None = None,
) -> Path:
    from datetime import datetime

    from sase.core.time import get_timezone

    report_dir = sase_subdir("notifications") / "fanout_failures"
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(get_timezone()).strftime("%Y%m%d_%H%M%S_%f")
    report_path = report_dir / f"prompt_fanout_failure_{timestamp}.txt"
    vcs_label = "" if vcs_ref is None else f"{vcs_ref[0]}:{vcs_ref[1]}"
    lines = [
        "Prompt fan-out launch failed before any child agents were created.",
        "",
        f"Error: {exc_summary}",
        f"Fanout kind: {fanout_kind}",
        f"Slot count: {slot_count}",
        f"Display name: {ctx.display_name}",
        f"Project name: {ctx.project_name}",
        f"Project file: {ctx.project_file}",
        f"History key: {ctx.history_sort_key}",
        f"Home mode: {ctx.is_home_mode}",
        f"Deferred workspace: {has_wait}",
        f"VCS ref: {vcs_label}",
    ]
    if submitted_xprompt is not None:
        from sase.axe.runner_reporting import format_markdown_fenced_block

        lines.extend(
            [
                "",
                "## Submitted XPrompt",
                "",
                format_markdown_fenced_block(submitted_xprompt, "markdown"),
            ]
        )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path
