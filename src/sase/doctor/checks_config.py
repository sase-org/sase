"""Configuration check registry for ``sase doctor``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.diagnostics import CheckSpec
from sase.doctor.checks_config_artifact_refs import check_config_artifact_refs
from sase.doctor.checks_config_external_mirror import check_config_external_mirror
from sase.doctor.checks_config_file_hooks import check_config_file_hooks
from sase.doctor.checks_config_init import check_config_init
from sase.doctor.checks_config_keymap_actions import check_config_keymap_actions
from sase.doctor.checks_config_keymap_glossary import check_config_keymap_glossary
from sase.doctor.checks_config_layers import check_config_layers
from sase.doctor.checks_config_memory_webs import check_config_memory_webs
from sase.doctor.checks_config_model_aliases import check_config_model_aliases
from sase.doctor.checks_config_notification_rules import (
    check_config_notification_rules,
)
from sase.doctor.checks_config_notification_tabs import (
    check_config_notification_tabs,
)
from sase.doctor.checks_config_repos import check_config_repos
from sase.doctor.checks_config_skills import check_config_skills_applied
from sase.doctor.checks_config_sdd import check_config_sdd
from sase.doctor.checks_config_timezone import check_config_timezone
from sase.doctor.checks_config_tribes import check_config_tribes
from sase.doctor.checks_config_macros import (
    check_config_model_macros,
    check_config_macro_definitions,
    check_config_macro_directives,
)
from sase.doctor.checks_config_retired import check_config_retired_xprompt_names

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
            id="config.timezone",
            group="config",
            title="Configured timezone",
            runner=check_config_timezone,
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
            id="config.memory_webs",
            group="config",
            title="Memory webs",
            runner=lambda: check_config_memory_webs(context),
        ),
        CheckSpec(
            id="config.model_aliases",
            group="config",
            title="Model alias migration",
            runner=check_config_model_aliases,
        ),
        CheckSpec(
            id="config.keymap_actions",
            group="config",
            title="Keymap action renames",
            runner=check_config_keymap_actions,
        ),
        CheckSpec(
            id="config.keymap_glossary",
            group="config",
            title="Glossary keymap scope",
            runner=check_config_keymap_glossary,
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
            id="config.file_hooks",
            group="config",
            title="File hook config",
            runner=check_config_file_hooks,
        ),
        CheckSpec(
            id="config.external_mirror",
            group="config",
            title="External mirror filter config",
            runner=check_config_external_mirror,
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
            id="config.notification_rules",
            group="config",
            title="Notification delivery rules",
            runner=check_config_notification_rules,
        ),
        CheckSpec(
            id="config.model_macros",
            group="config",
            title="Model macro routing",
            runner=lambda: check_config_model_macros(context),
        ),
        CheckSpec(
            id="config.macro_definitions",
            group="config",
            title="Macro definitions",
            runner=lambda: check_config_macro_definitions(context),
        ),
        CheckSpec(
            id="config.macro_directives",
            group="config",
            title="Retired macro directives",
            runner=lambda: check_config_macro_directives(context),
        ),
        CheckSpec(
            id="config.retired_xprompt_names",
            group="config",
            title="Retired xprompt names",
            runner=lambda: check_config_retired_xprompt_names(context),
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
_check_config_timezone = check_config_timezone
_check_config_init = check_config_init
_check_config_sdd = check_config_sdd
_check_config_memory_webs = check_config_memory_webs
_check_config_model_aliases = check_config_model_aliases
_check_config_keymap_actions = check_config_keymap_actions
_check_config_keymap_glossary = check_config_keymap_glossary
_check_config_notification_tabs = check_config_notification_tabs
_check_config_notification_rules = check_config_notification_rules
_check_config_repos = check_config_repos
_check_config_artifact_refs = check_config_artifact_refs
_check_config_file_hooks = check_config_file_hooks
_check_config_external_mirror = check_config_external_mirror
_check_config_tribes = check_config_tribes
_check_config_model_macros = check_config_model_macros
_check_config_macro_definitions = check_config_macro_definitions
_check_config_macro_directives = check_config_macro_directives
_check_config_retired_xprompt_names = check_config_retired_xprompt_names
_check_config_skills_applied = check_config_skills_applied


__all__ = [
    "config_check_specs",
]
