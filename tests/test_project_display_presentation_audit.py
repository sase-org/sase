"""Syntax-aware guards for audited project-display presentation boundaries."""

from __future__ import annotations

import pytest

from _project_display_presentation_audit_canonical import (
    test_audited_human_sinks_do_not_render_canonical_identity_directly,
    test_canonical_exemptions_name_existing_sites_and_rationales,
    test_patch_completion_catalog_projects_display_fields,
)
from _project_display_presentation_audit_fallbacks import (
    test_display_fallback_exemptions_name_existing_sites_and_rationales,
    test_project_display_name_fallback_lives_only_in_chokepoint,
)
from _project_display_presentation_audit_metadata import (
    test_audited_tui_render_helpers_are_free_of_io_and_subprocess_calls,
    test_project_metadata_loaders_stay_at_reviewed_tui_worker_boundaries,
)
from _project_display_presentation_audit_path_labels import (
    test_path_label_exemptions_name_existing_sites_and_rationales,
    test_project_labels_never_derive_from_paths,
)

pytestmark = pytest.mark.contract
