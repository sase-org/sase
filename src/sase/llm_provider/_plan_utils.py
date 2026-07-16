"""Shared plan utilities for LLM providers."""

import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

# Poll interval for plan approval responses (seconds)
_POLL_INTERVAL = 0.5


@dataclass
class PlanApprovalResult:
    """Result from plan approval flow."""

    action: str  # "approve", "epic", or "feedback"
    plan_file: str
    feedback: str | None = None
    commit_plan: bool = True
    run_coder: bool = True
    coder_prompt: str | None = None
    coder_model: str | None = None
    auto_approved: bool = field(default=False, compare=False)
    epic_launch_owner: Literal["host"] | None = field(default=None, compare=False)


def add_create_time_frontmatter(
    content: str, create_time: datetime | None = None
) -> str:
    """Add a ``create_time`` field in YAML frontmatter to plan content.

    If the content already has frontmatter (delimited by ``---``), the
    ``create_time`` field is inserted into the existing block.  If a
    ``create_time`` field already exists (e.g. added by an agent), it is
    overwritten to ensure the correct format.  Otherwise a new frontmatter
    section is prepended.

    The datetime is formatted as ``yyyy-mm-dd HH:MM:SS`` in the configured
    timezone (see :func:`sase.core.time.get_timezone`).
    """
    if create_time is None:
        from sase.core.time import get_timezone

        create_time = datetime.now(get_timezone())
    ts = create_time.strftime("%Y-%m-%d %H:%M:%S")

    # Already has frontmatter?
    if content.startswith("---\n"):
        end = content.find("\n---\n", 4)
        if end != -1:
            fm_body = content[4 : end + 1]  # includes trailing \n
            has_status = bool(re.search(r"^status:", fm_body, re.MULTILINE))
            # Overwrite existing create_time field if present.
            if re.search(r"^create_time:", fm_body, re.MULTILINE):
                fm_body = re.sub(
                    r"^create_time:.*$",
                    f"create_time: {ts}",
                    fm_body,
                    flags=re.MULTILINE,
                )
                if not has_status:
                    fm_body += "status: wip\n"
                return f"---\n{fm_body}---\n{content[end + 5 :]}"
            # Insert fields at the end of the frontmatter block.
            extra = f"create_time: {ts}"
            if not has_status:
                extra += "\nstatus: wip"
            return f"---\n{fm_body}{extra}\n---\n{content[end + 5 :]}"

    # No frontmatter — prepend a new block.
    fields = f"create_time: {ts}\nstatus: wip"
    return f"---\n{fields}\n---\n{content}"


def _mark_auto_approved_plan_handled(
    plan_file: str, agent_name: str | None, *, action: str | None = None
) -> None:
    """Best-effort: mark PlanApproval actions for this plan handled.

    Matches on the exact plan file plus the running agent's identity so only
    notifications and keyboards tied to this agent/plan are dismissed. Never
    raises.
    """
    try:
        from sase.notifications.pending_actions import (
            mark_plan_approval_auto_handled,
        )

        handled_ids = mark_plan_approval_auto_handled(
            plan_file=plan_file,
            agent_timestamp=os.environ.get("SASE_AGENT_TIMESTAMP"),
            agent_root_timestamp=os.environ.get("SASE_AGENT_ROOT_TIMESTAMP"),
            agent_name=agent_name,
            source="auto_approve",
            action=action,
        )
        from sase.notifications import mark_dismissed

        for notification_id in handled_ids:
            mark_dismissed(notification_id)
    except Exception:
        pass


def move_plan_to_sase(plan_file: str) -> Path:
    """Move a plan file into a sharded ``~/.sase/plans/YYYYMM/`` location.

    The submitted scratch file is consumed: on a same-filesystem move this is a
    rename, and a cross-filesystem move copies then unlinks the source. The
    ``sase_plan_`` prefix is stripped from the archived name, and the existing
    dedup counter keeps distinct copies when the target basename already exists.
    """
    from sase.core.paths import find_sharded_file, sharded_path

    src = Path(plan_file)
    # Strip "sase_plan_" prefix if present
    name = src.name
    if name.startswith("sase_plan_"):
        name = name[len("sase_plan_") :]
    # Plan filenames carry no embedded timestamp; shard by now() at write time.
    dest = Path(sharded_path("plans", name))
    if dest.exists() or find_sharded_file("plans", name) is not None:
        dest_path = Path(name)
        stem = dest_path.stem
        suffix = dest_path.suffix
        counter = 1
        while True:
            candidate_name = f"{stem}_{counter}{suffix}"
            candidate = Path(sharded_path("plans", candidate_name))
            if (
                not candidate.exists()
                and find_sharded_file("plans", candidate_name) is None
            ):
                dest = candidate
                break
            counter += 1
    shutil.move(str(src), str(dest))
    return dest


def handle_plan_approval(
    plan_file: str | None,
    session_id: str,
    *,
    killed_check: Callable[[], bool] | None = None,
    agent_name: str | None = None,
    agent_model: str | None = None,
    agent_llm_provider: str | None = None,
    agent_runtime: str | None = None,
    agent_vcs_tag: str | None = None,
) -> PlanApprovalResult | None:
    """Create and mechanically wait for a tiered command-backed plan gate.

    Args:
        plan_file: Path to the plan file.
        session_id: Unique session ID for the approval flow.
        killed_check: Optional callable that returns True if the process was
            killed (SIGTERM). When provided, the poll loop checks it each
            iteration and returns None early if killed.

    Returns a ``PlanApprovalResult`` when accepted, or ``None`` if
    rejected / missing / killed.
    """
    if not plan_file:
        return None
    from sase.main.plan_approve_handler import (
        get_auto_plan_approval_action,
        get_auto_plan_approval_argument,
    )

    auto_action = get_auto_plan_approval_action()
    auto_enabled = auto_action is not None
    auto_argument = get_auto_plan_approval_argument()
    if auto_argument is None and auto_action in {"tale", "epic"}:
        auto_argument = auto_action

    from sase.plan_gate import create_plan_approval_gate

    gate = create_plan_approval_gate(
        plan_file,
        session_id,
        auto_enabled=auto_enabled,
        auto_argument=auto_argument,
        agent_name=agent_name,
        agent_model=agent_model,
        agent_llm_provider=agent_llm_provider,
        agent_runtime=agent_runtime,
        agent_vcs_tag=agent_vcs_tag,
    )
    reviewed_plan = gate.bundle_path / "plan.md"
    if auto_enabled:
        _mark_auto_approved_plan_handled(
            plan_file,
            agent_name,
            action=auto_action,
        )

    # Desktop notification + tmux bell
    from sase.main.plan_approve_handler import (
        get_tmux_prefix,
        ring_tmux_bell,
        send_desktop_notification,
    )

    if gate.notification_id is not None:
        prefix = get_tmux_prefix()
        send_desktop_notification(
            f"{prefix} Plan Complete", "Plan ready for review in sase ace"
        )
        ring_tmux_bell()

    auto_resolved = auto_enabled

    def _resolve_new_auto_setting() -> None:
        nonlocal auto_resolved
        if auto_resolved:
            return
        current_action = get_auto_plan_approval_action()
        if current_action is None:
            return
        argument = get_auto_plan_approval_argument()
        if argument is None and current_action in {"tale", "epic"}:
            argument = current_action
        from sase.plan_gate import execute_plan_gate_auto_choice

        execute_plan_gate_auto_choice(
            gate.bundle_path,
            argument,
            source="auto_approve",
        )
        auto_resolved = True
        _mark_auto_approved_plan_handled(
            plan_file,
            agent_name,
            action=current_action,
        )

    from sase.notification_gates.poller import wait_for_gate

    polled = wait_for_gate(
        gate.bundle_path,
        poll_interval=_POLL_INTERVAL,
        cancelled=killed_check,
        on_poll=_resolve_new_auto_setting,
    )
    if polled.status != "responded":
        if gate.notification_id is not None:
            from sase.notifications import mark_dismissed

            mark_dismissed(gate.notification_id)
        return None
    from sase.plan_gate import translate_plan_gate_response

    response_data = translate_plan_gate_response(gate.bundle_path, polled.payload)
    action = response_data.get("action")
    if action in ("approve", "epic", "commit"):
        raw_commit = response_data.get("commit_plan")
        commit_plan = raw_commit if isinstance(raw_commit, bool) else True
        raw_run = response_data.get("run_coder")
        run_coder = raw_run if isinstance(raw_run, bool) else True
        raw_prompt = response_data.get("coder_prompt")
        coder_prompt = (
            raw_prompt.strip() or None if isinstance(raw_prompt, str) else None
        )
        raw_model = response_data.get("coder_model")
        coder_model = raw_model.strip() or None if isinstance(raw_model, str) else None
        epic_launch_owner: Literal["host"] | None = None
        if action == "epic" and response_data.get("epic_launch_owner") == "host":
            epic_launch_owner = "host"
        if action == "commit":
            action = "approve"
            run_coder = False
        return PlanApprovalResult(
            action=action,
            plan_file=str(reviewed_plan),
            commit_plan=commit_plan,
            run_coder=run_coder,
            coder_prompt=coder_prompt,
            coder_model=coder_model,
            auto_approved=auto_resolved,
            epic_launch_owner=epic_launch_owner,
        )
    feedback = response_data.get("feedback")
    if isinstance(feedback, str) and feedback:
        return PlanApprovalResult(
            action="feedback",
            plan_file=str(reviewed_plan),
            feedback=feedback,
            auto_approved=auto_resolved,
        )
    return None
