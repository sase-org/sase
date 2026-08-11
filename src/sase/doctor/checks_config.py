"""Configuration check registry for ``sase doctor``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.diagnostics import CheckSpec
from sase.doctor.checks_config_artifact_refs import check_config_artifact_refs
from sase.doctor.checks_config_init import check_config_init
from sase.doctor.checks_config_layers import check_config_layers
from sase.doctor.checks_config_model_aliases import check_config_model_aliases
from sase.doctor.checks_config_notification_tabs import (
    check_config_notification_tabs,
)
from sase.doctor.checks_config_repos import check_config_repos
from sase.doctor.checks_config_skills import check_config_skills_applied
from sase.doctor.checks_config_sdd import check_config_sdd
from sase.doctor.checks_config_tribes import check_config_tribes
from sase.doctor.checks_config_xprompts import (
    check_config_model_xprompts,
    check_config_xprompt_definitions,
)

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


def config_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return Phase 2 config check specs."""
    return (
        CheckSpec(
            id="config.layers",
            group="config",
            title="Config layers",
            runner=check_config_layers,
        ),
        CheckSpec(
            id="config.init",
            group="config",
            title="Initialization planners",
            runner=lambda: check_config_init(context),
        ),
        CheckSpec(
            id="config.sdd",
            group="config",
            title="SDD validation",
            runner=lambda: check_config_sdd(context),
        ),
        CheckSpec(
            id="config.model_aliases",
            group="config",
            title="Model alias migration",
            runner=check_config_model_aliases,
        ),
        CheckSpec(
            id="config.repos",
            group="config",
            title="Sidecar repo config",
            runner=check_config_repos,
        ),
        CheckSpec(
            id="config.artifact_refs",
            group="config",
            title="Artifact reference config",
            runner=check_config_artifact_refs,
        ),
        CheckSpec(
            id="config.tribes",
            group="config",
            title="Tribe descriptions",
            runner=check_config_tribes,
        ),
        CheckSpec(
            id="config.notification_tabs",
            group="config",
            title="Notification tab icons",
            runner=check_config_notification_tabs,
        ),
        CheckSpec(
            id="config.model_xprompts",
            group="config",
            title="Model xprompt routing",
            runner=lambda: check_config_model_xprompts(context),
        ),
        CheckSpec(
            id="config.xprompt_definitions",
            group="config",
            title="XPrompt definitions",
            runner=lambda: check_config_xprompt_definitions(context),
        ),
        CheckSpec(
            id="config.skills.applied",
            group="config",
            title="Applied generated skills",
            runner=check_config_skills_applied,
            deep=True,
        ),
    )


_check_config_layers = check_config_layers
_check_config_init = check_config_init
_check_config_sdd = check_config_sdd
_check_config_model_aliases = check_config_model_aliases
_check_config_notification_tabs = check_config_notification_tabs
_check_config_repos = check_config_repos
_check_config_artifact_refs = check_config_artifact_refs
_check_config_tribes = check_config_tribes
_check_config_model_xprompts = check_config_model_xprompts
_check_config_xprompt_definitions = check_config_xprompt_definitions
_check_config_skills_applied = check_config_skills_applied


__all__ = [
    "config_check_specs",
]
