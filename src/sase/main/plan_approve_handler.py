"""Utility functions for plan approval and notification support.

Provides helpers for auto-approve checking, desktop notifications,
and tmux bell ringing. Used by the agent runner and other plan/question
orchestration code.

Facade preserving the original public import path. Implementation lives in
:mod:`sase.main.plan_approve_auto`,
:mod:`sase.main.plan_approve_cli`,
:mod:`sase.main.plan_approve_notify`, and
:mod:`sase.main.plan_approve_selection`.
"""

from __future__ import annotations

from sase.main.plan_approve_auto import (
    PlanAutoApprovalAction,
    get_auto_plan_approval_action,
    get_auto_plan_approval_argument,
    is_auto_approve_active,
)
from sase.main.plan_approve_cli import handle_plan_approve_command
from sase.main.plan_approve_notify import (
    get_tmux_prefix,
    send_desktop_notification,
)
from sase.main.plan_approve_selection import resolve_plan_for_cli

__all__ = [
    "PlanAutoApprovalAction",
    "get_auto_plan_approval_action",
    "get_auto_plan_approval_argument",
    "get_tmux_prefix",
    "handle_plan_approve_command",
    "is_auto_approve_active",
    "resolve_plan_for_cli",
    "send_desktop_notification",
]
