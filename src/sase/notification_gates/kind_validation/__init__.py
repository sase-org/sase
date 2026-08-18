"""Validation contracts for built-in notification gate kinds."""

from sase.notification_gates.kind_validation.bead_snooze import (
    validate_bead_snooze_spec,
)
from sase.notification_gates.kind_validation.bead_stale_cleanup import (
    validate_bead_stale_cleanup_spec,
)
from sase.notification_gates.kind_validation.custom import validate_custom_spec
from sase.notification_gates.kind_validation.epic_resume import (
    validate_epic_resume_spec,
)
from sase.notification_gates.kind_validation.flag_triage import (
    validate_flag_triage_spec,
)
from sase.notification_gates.kind_validation.launch import validate_launch_spec
from sase.notification_gates.kind_validation.plan import validate_plan_spec
from sase.notification_gates.kind_validation.plugins_required import (
    validate_plugins_required_spec,
)
from sase.notification_gates.kind_validation.question import validate_question_spec
from sase.notification_gates.kind_validation.task_triage import (
    validate_task_triage_spec,
)

__all__ = [
    "validate_bead_snooze_spec",
    "validate_bead_stale_cleanup_spec",
    "validate_custom_spec",
    "validate_epic_resume_spec",
    "validate_flag_triage_spec",
    "validate_launch_spec",
    "validate_plan_spec",
    "validate_plugins_required_spec",
    "validate_question_spec",
    "validate_task_triage_spec",
]
