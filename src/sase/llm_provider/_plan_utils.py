"""Shared plan utilities for LLM providers."""

import json
import os
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from sase.plan_approval_choices import (
    default_member_ids_from_request_data,
    plan_approval_member_request_payload,
    selected_member_ids_from_response_data,
)

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
    selected_member_ids: tuple[str, ...] | None = field(default=None, compare=False)
    auto_approved: bool = field(default=False, compare=False)
    epic_launch_owner: Literal["host"] | None = field(default=None, compare=False)


def _auto_approval_result(auto_action: str, plan_file: str) -> PlanApprovalResult:
    """Build the runner result for an auto-approved plan.

    Bare ``%auto``/``%a`` plan mode resolves to ``auto_action == "approve"``.
    That mirrors the interactive "Approve" choice, so it should run the coder
    without committing an SDD tale. Tale and epic auto modes keep committing.
    """
    return PlanApprovalResult(
        action=auto_action,
        plan_file=plan_file,
        commit_plan=auto_action != "approve",
        selected_member_ids=_auto_default_member_ids(),
        auto_approved=True,
    )


def _validated_auto_approval_result(
    auto_action: str, plan_file: str
) -> PlanApprovalResult:
    """Validate a tiered auto-approval before consuming its pending action."""
    from sase.plan_approval_actions import resolve_plan_approval_choice

    resolved_action = resolve_plan_approval_choice(plan_file, auto_action)
    return _auto_approval_result(resolved_action, plan_file)


def _auto_default_member_ids() -> tuple[str, ...]:
    payload = plan_approval_member_request_payload()
    return default_member_ids_from_request_data(payload, auto_mode=True)


def _plan_approval_project_name(project_dir: str | None) -> str | None:
    if not project_dir:
        return None
    try:
        from sase.workspace_provider import get_workspace_name

        return get_workspace_name(project_dir)
    except Exception:
        return None


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
    """Handle plan approval flow.

    Creates a TUI notification via ``notify_plan_approval()``, then polls for
    the user's response.  Sends desktop notification and tmux bell.

    Args:
        plan_file: Path to the plan file.
        session_id: Unique session ID for the approval flow.
        killed_check: Optional callable that returns True if the process was
            killed (SIGTERM). When provided, the poll loop checks it each
            iteration and returns None early if killed.

    Returns a ``PlanApprovalResult`` when accepted, or ``None`` if
    rejected / missing / killed.
    """
    from sase.main.plan_approve_handler import get_auto_plan_approval_action

    auto_action = get_auto_plan_approval_action()
    if auto_action is not None:
        if not plan_file:
            return None
        result = _validated_auto_approval_result(auto_action, plan_file)
        # Auto-approval resolves the plan outside the notification + Telegram
        # callback path. Any notification or inline keyboard already sent for
        # this plan must be cleared, so record handled-state and dismiss the
        # matching notification if it exists.
        _mark_auto_approved_plan_handled(plan_file, agent_name, action=auto_action)
        return result

    if not plan_file:
        return None

    from sase.core.paths import sharded_path

    # Session IDs carry no timestamp → shard by now() at write time.
    response_dir = Path(sharded_path("plan_approval", session_id))
    response_dir.mkdir(parents=True, exist_ok=True)

    request_path = response_dir / "plan_request.json"
    response_path = response_dir / "plan_response.json"

    if response_path.exists():
        response_path.unlink()

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    member_payload = plan_approval_member_request_payload(
        project=_plan_approval_project_name(project_dir)
    )
    request_data = {
        "plan_file": plan_file,
        "session_id": session_id,
        "timestamp": time.time(),
        **member_payload,
    }
    with open(request_path, "w", encoding="utf-8") as f:
        json.dump(request_data, f, indent=2)

    from sase.notifications.senders import notify_plan_approval

    agent_cl_name = os.environ.get("SASE_AGENT_CL_NAME")
    agent_project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
    agent_timestamp = os.environ.get("SASE_AGENT_TIMESTAMP")
    agent_root_timestamp = os.environ.get("SASE_AGENT_ROOT_TIMESTAMP")
    raw_default_member_ids = member_payload.get("default_member_ids")
    default_member_ids = (
        tuple(
            member_id
            for member_id in raw_default_member_ids
            if isinstance(member_id, str)
        )
        if isinstance(raw_default_member_ids, list)
        else ()
    )
    notify_plan_approval(
        plan_file=plan_file,
        response_dir=str(response_dir),
        session_id=session_id,
        project_dir=project_dir,
        agent_cl_name=agent_cl_name,
        agent_project_file=agent_project_file,
        agent_timestamp=agent_timestamp,
        agent_root_timestamp=agent_root_timestamp,
        agent_name=agent_name,
        agent_model=agent_model,
        agent_llm_provider=agent_llm_provider,
        agent_runtime=agent_runtime,
        agent_vcs_tag=agent_vcs_tag,
        default_member_ids=default_member_ids,
    )

    # Desktop notification + tmux bell
    from sase.main.plan_approve_handler import (
        get_tmux_prefix,
        ring_tmux_bell,
        send_desktop_notification,
    )

    prefix = get_tmux_prefix()
    send_desktop_notification(
        f"{prefix} Plan Complete", "Plan ready for review in sase ace"
    )
    ring_tmux_bell()

    # Poll for response (blocks until the user acts)
    while True:
        if killed_check is not None and killed_check():
            return None

        if response_path.exists():
            try:
                with open(response_path, encoding="utf-8") as f:
                    response_data = json.load(f)

                if request_path.exists():
                    try:
                        with open(request_path, encoding="utf-8") as f:
                            request_data = json.load(f)
                        if not isinstance(request_data, dict):
                            request_data = {}
                    except (json.JSONDecodeError, OSError):
                        request_data = {}
                    request_path.unlink()
                else:
                    request_data = {}

                action = response_data.get("action")
                if action in ("approve", "epic", "commit"):
                    response_path.unlink()
                    assert plan_file is not None
                    # Read custom approval fields with type validation
                    raw_commit = response_data.get("commit_plan")
                    commit_plan = raw_commit if isinstance(raw_commit, bool) else True
                    raw_run = response_data.get("run_coder")
                    run_coder = raw_run if isinstance(raw_run, bool) else True
                    raw_prompt = response_data.get("coder_prompt")
                    coder_prompt = (
                        raw_prompt.strip() or None
                        if isinstance(raw_prompt, str)
                        else None
                    )
                    raw_model = response_data.get("coder_model")
                    coder_model = (
                        raw_model.strip() or None
                        if isinstance(raw_model, str)
                        else None
                    )
                    selected_member_ids = selected_member_ids_from_response_data(
                        response_data,
                        request_data,
                    )
                    raw_epic_launch_owner = response_data.get("epic_launch_owner")
                    epic_launch_owner: Literal["host"] | None = None
                    if action == "epic" and raw_epic_launch_owner == "host":
                        epic_launch_owner = "host"
                    # Backward compat: old "commit" action maps to
                    # approve with run_coder=False
                    if action == "commit":
                        action = "approve"
                        run_coder = False
                    return PlanApprovalResult(
                        action=action,
                        plan_file=plan_file,
                        commit_plan=commit_plan,
                        run_coder=run_coder,
                        coder_prompt=coder_prompt,
                        coder_model=coder_model,
                        selected_member_ids=selected_member_ids,
                        epic_launch_owner=epic_launch_owner,
                    )
                # Rejection with feedback: return result so caller
                # can spawn a replanner agent with the feedback.
                feedback = response_data.get("feedback")
                if feedback:
                    response_path.unlink()
                    assert plan_file is not None
                    return PlanApprovalResult(
                        action="feedback",
                        plan_file=plan_file,
                        feedback=feedback,
                    )
                # Plain rejection — no response needed.
                return None
            except (json.JSONDecodeError, OSError):
                pass

        auto_action = get_auto_plan_approval_action()
        if auto_action is not None:
            result = _validated_auto_approval_result(auto_action, plan_file)
            if request_path.exists():
                request_path.unlink()
            _mark_auto_approved_plan_handled(plan_file, agent_name, action=auto_action)
            return result

        time.sleep(_POLL_INTERVAL)
