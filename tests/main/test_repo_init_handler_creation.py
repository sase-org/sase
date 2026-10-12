"""Tests for remote sidecar creation by ``sase repo init``."""

from tests.main._test_repo_init_handler_creation_confirmation import (
    test_missing_custom_private_sidecar_requires_fresh_confirmation,
    test_missing_agents_sidecar_requires_loud_role_specific_confirmation,
    test_declined_agents_sidecar_continues_other_sidecars,
    test_declined_attachments_private_sidecar_continues_other_sidecars,
    test_non_tty_refuses_only_agents_creation_and_explains_rerun,
    test_declined_sidecar_creation_does_not_materialize,
    test_non_tty_and_yes_cannot_authorize_sidecar_creation,
    test_noninteractive_bare_init_defers_missing_sidecar_creation,
)
from tests.main._test_repo_init_handler_creation_sidecars import (
    test_existing_sidecar_initializes_without_creation_prompt,
    test_public_sidecar_prompt_defaults_yes_and_names_public,
    test_public_sidecar_refused_when_beads_private,
    test_private_primary_forces_private_sidecar_creation,
    test_private_primary_rerun_without_missing_sidecars_stays_quiet,
    test_unverifiable_primary_creates_private_sidecars_without_config_rewrite,
    test_private_primary_plan_declares_private_sidecars,
)

__all__ = [
    "test_missing_custom_private_sidecar_requires_fresh_confirmation",
    "test_missing_agents_sidecar_requires_loud_role_specific_confirmation",
    "test_declined_agents_sidecar_continues_other_sidecars",
    "test_declined_attachments_private_sidecar_continues_other_sidecars",
    "test_non_tty_refuses_only_agents_creation_and_explains_rerun",
    "test_declined_sidecar_creation_does_not_materialize",
    "test_non_tty_and_yes_cannot_authorize_sidecar_creation",
    "test_noninteractive_bare_init_defers_missing_sidecar_creation",
    "test_existing_sidecar_initializes_without_creation_prompt",
    "test_public_sidecar_prompt_defaults_yes_and_names_public",
    "test_public_sidecar_refused_when_beads_private",
    "test_private_primary_forces_private_sidecar_creation",
    "test_private_primary_rerun_without_missing_sidecars_stays_quiet",
    "test_unverifiable_primary_creates_private_sidecars_without_config_rewrite",
    "test_private_primary_plan_declares_private_sidecars",
]
