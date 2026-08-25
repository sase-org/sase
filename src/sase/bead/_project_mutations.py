"""Mutation operations for :class:`sase.bead.project.BeadProject`."""

from __future__ import annotations

from sase.bead._project_mutations_claims import BeadProjectMutationClaimsMixin
from sase.bead._project_mutations_crud import BeadProjectMutationCrudMixin
from sase.bead._project_mutations_evidence import BeadProjectMutationEvidenceMixin
from sase.bead._project_mutations_lifecycle import BeadProjectMutationLifecycleMixin
from sase.bead._project_mutations_links import BeadProjectMutationLinksMixin
from sase.bead._project_mutations_snooze import BeadProjectMutationSnoozeMixin


class BeadProjectMutationMixin(
    BeadProjectMutationCrudMixin,
    BeadProjectMutationEvidenceMixin,
    BeadProjectMutationSnoozeMixin,
    BeadProjectMutationClaimsMixin,
    BeadProjectMutationLifecycleMixin,
    BeadProjectMutationLinksMixin,
):
    """Rust-backed mutation methods for ``BeadProject``."""
