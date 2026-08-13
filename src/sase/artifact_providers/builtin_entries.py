"""Dispatcher over the Python-owned builtin artifact-reference kinds.

``stitch``, ``patch``, ``bead`` (short ids), and ``agent`` (transcript
pointer) resolve here instead of through the Rust resolver, which
deliberately returns ``unknown_kind`` for ``Stitch``/``Patch`` payloads and
leaves ``bead``/``agent`` entry-property enrichment to Python. See
``@plan:202608/artifact_ref_contract.md`` S3.6-S3.7.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path

from sase.artifact_ref_models import (
    ArtifactEntry,
    ArtifactRef,
    ArtifactRefContext,
    ArtifactRefResolutionStatus,
)
from sase.artifact_ref_operations import artifact_ref_entry_validate
from sase.artifact_ref_prompt_context import PromptRefContext


log = logging.getLogger(__name__)


BUILTIN_ENTRY_KIND_TYPES = ("stitch", "patch", "bead", "agent")


@dataclass(frozen=True, slots=True)
class BuiltinEntryOutcome:
    """The result of a Python-owned builtin-kind resolution attempt."""

    status: ArtifactRefResolutionStatus
    entry: ArtifactEntry | None = None
    prompt_text: str | None = None
    locator: str | None = None
    resolved_path: Path | None = None
    candidates: tuple[str, ...] = ()
    diagnostic: str | None = None
    canonical_reference: str | None = None


def resolve_builtin_entry(
    reference: ArtifactRef,
    *,
    context: ArtifactRefContext,
    ref_context: PromptRefContext,
) -> BuiltinEntryOutcome | None:
    """Resolve *reference* if it is a Python-owned builtin kind.

    Returns ``None`` both for kinds this dispatcher does not own and when a
    resolver decides its input is better handled by the unchanged Rust
    resolver (e.g. a full bead id) -- either way, the caller falls through to
    :func:`~sase.artifact_ref_operations.resolve_artifact_ref`.
    """

    if reference.kind_type == "stitch":
        from sase.artifact_providers.builtin_entry_stitch import resolve_stitch_entry

        return resolve_stitch_entry(reference, context=context, ref_context=ref_context)
    if reference.kind_type == "patch":
        from sase.artifact_providers.builtin_entry_patch import resolve_patch_entry

        return resolve_patch_entry(reference, context=context, ref_context=ref_context)
    if reference.kind_type == "bead":
        from sase.artifact_providers.builtin_entry_bead import resolve_bead_entry

        return resolve_bead_entry(reference, context=context, ref_context=ref_context)
    if reference.kind_type == "agent":
        from sase.artifact_providers.builtin_entry_agent import resolve_agent_entry

        return resolve_agent_entry(reference, context=context, ref_context=ref_context)
    return None


def validate_builtin_entry(entry: ArtifactEntry) -> ArtifactEntry | None:
    """Validate *entry* against the Rust wire, downgrading to ``None`` on failure.

    A malformed entry never fails the launch: the ref still resolves and
    expands, it simply carries no structured entry.
    """

    try:
        artifact_ref_entry_validate(entry.to_wire())
    except Exception:
        log.debug(
            "Builtin artifact entry %r failed validation",
            entry.stable_id,
            exc_info=True,
        )
        return None
    return entry


__all__ = [
    "BUILTIN_ENTRY_KIND_TYPES",
    "BuiltinEntryOutcome",
    "resolve_builtin_entry",
    "validate_builtin_entry",
]
