"""Prompt submission and launch-start handling for agent workflow actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._launch_bulk import (
    AcceptedBulkLaunch as _AcceptedBulkLaunch,
    LaunchBulkSubmissionMixin,
    log_bulk_item_failure as _log_bulk_item_failure,
)
from ._launch_prompt_inputs import LaunchPromptInputMixin
from ._launch_provider_guard import LaunchProviderGuardMixin
from ._launch_submission import (
    AcceptedLaunchSubmission as _AcceptedLaunchSubmission,
    LaunchSubmissionMixin,
)
from ._launch_submit_helpers import (
    launch_record_context as _launch_record_context,
    launch_record_context_from_prompt_context as _launch_record_context_from_prompt_context,
    launch_toast_label as _launch_toast_label,
    record_submit_time_vcs_replay as _record_submit_time_vcs_replay,
    submitted_vcs_xprompt_prefix as _submitted_vcs_xprompt_prefix,
    vcs_workflow_type_from_tag as _vcs_workflow_type_from_tag,
)
from ._types import PromptContext

if TYPE_CHECKING:
    from sase.ace.patch import Patch


class AgentLaunchStartMixin(
    LaunchBulkSubmissionMixin,
    LaunchSubmissionMixin,
    LaunchPromptInputMixin,
):
    """Mixin providing prompt-submit launch setup."""

    _prompt_context: PromptContext | None
    _bulk_patches: list[Patch] | None


__all__ = [
    "AgentLaunchStartMixin",
    "LaunchProviderGuardMixin",
    "_AcceptedBulkLaunch",
    "_AcceptedLaunchSubmission",
    "_launch_record_context",
    "_launch_record_context_from_prompt_context",
    "_launch_toast_label",
    "_log_bulk_item_failure",
    "_record_submit_time_vcs_replay",
    "_submitted_vcs_xprompt_prefix",
    "_vcs_workflow_type_from_tag",
]
