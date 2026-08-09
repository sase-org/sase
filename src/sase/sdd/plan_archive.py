"""Shared preparation of plans entering the canonical SDD plan archive."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from sase.sdd.store import SddStore

PlanTier = Literal["tale", "epic"]


@dataclass(frozen=True)
class _PlanArchiveResult:
    """The canonical plan path and whether this call wrote it."""

    path: Path
    written: bool


def plan_archive_destination(
    source: Path,
    store: SddStore,
    *,
    yyyymm: str | None = None,
    destination_name: str | None = None,
) -> Path:
    """Return the canonical archive destination for *source*.

    A plan already anywhere below the store's plans root is canonical and
    retains its existing month. External plans are sharded into the current
    ``YYYYMM`` directory.
    """
    source = source.expanduser().resolve(strict=False)
    plans_root = store.kind_root("plans").expanduser().resolve(strict=False)
    if _is_relative_to(source, plans_root):
        return source

    if yyyymm is None:
        from sase.sdd.files import get_yyyymm

        yyyymm = get_yyyymm()
    archive_name = destination_name or source.name
    if not archive_name or Path(archive_name).name != archive_name:
        raise ValueError("plan archive destination_name must be a file name")
    return plans_root / yyyymm / archive_name


def archive_plan_file(
    source: Path,
    store: SddStore,
    *,
    tier: PlanTier,
    yyyymm: str | None = None,
    destination_name: str | None = None,
    preserve_existing: bool = True,
    primary_root: Path | None = None,
    prompt_path: Path | None = None,
    expect_prompt_snapshot: bool = False,
) -> _PlanArchiveResult:
    """Prepare *source* and copy it into the canonical plan archive.

    Formatting, create-time metadata, tier normalization, and committed-plan
    validation are centralized here so approval surfaces and ``sase bead
    work <plan-file>`` cannot drift. Plans already in the archive are a no-op.
    With ``preserve_existing`` (the resumable command default), an existing
    destination is also retained so its ``bead_id`` link is never overwritten
    by a retry from the original planner artifact.

    ``expect_prompt_snapshot`` is for callers that own a guaranteed prompt
    snapshot (e.g. an epic approval, where the agent always writes the prompt
    snapshot independently of this archive call). When set, the reciprocal
    ``PROMPT`` link is projected from the canonical path unconditionally,
    instead of probing the filesystem for it — the probe otherwise races the
    snapshot's own write/push and can lose, permanently archiving the plan
    without its link. A genuinely missing snapshot is not caught here or by
    ``sase plan links validate`` (which no longer checks where a PROMPT
    bullet resolves); it instead surfaces once the agents-sidecar prompt
    archive is validated.

    This helper only writes the file. Its caller owns commit and push policy.
    """
    from sase.sdd.files import get_yyyymm

    source = source.expanduser().resolve(strict=False)
    plans_root = store.kind_root("plans").expanduser().resolve(strict=False)
    if _is_relative_to(source, plans_root):
        return _PlanArchiveResult(path=source, written=False)

    archive_month = yyyymm or get_yyyymm()
    destination = plan_archive_destination(
        source,
        store,
        yyyymm=archive_month,
        destination_name=destination_name,
    )
    if preserve_existing and destination.is_file():
        return _PlanArchiveResult(path=destination, written=False)

    from sase.file_references import format_with_prettier
    from sase.llm_provider._plan_utils import add_create_time_frontmatter
    from sase.sdd.committed_plan_validation import validate_plan_for_commit
    from sase.sdd.checkout_anchor import resolve_checkout_anchor
    from sase.sdd.frontmatter import parse_frontmatter, set_frontmatter_fields
    from sase.sdd.plan_tiers import read_plan_tier_from_content
    from sase.sdd.plan_header_writes import project_plan_header_sections

    content = format_with_prettier(source.read_text(encoding="utf-8"))
    content = add_create_time_frontmatter(content)
    authored_tier = read_plan_tier_from_content(content)
    frontmatter, _body, _had_frontmatter = parse_frontmatter(content)
    normalized_fields: dict[str, str] = {"tier": tier}
    if tier == "tale" and authored_tier != "tale" and "size" not in frontmatter:
        normalized_fields["size"] = "medium"
    content = set_frontmatter_fields(content, normalized_fields)
    # Validate before projection: projection only rewrites derived header
    # sections into canonical form, so a document that fails here would fail
    # identically after projection, but projection itself raises a bare,
    # location-less ValueError on a malformed header block. Validating first
    # turns that into the same actionable diagnostic every other validation
    # surface uses, and does it before anything is written to disk.
    validate_plan_for_commit(
        content,
        tier=tier,
        path=source,
        yyyymm=archive_month,
    )
    content = project_plan_header_sections(
        content,
        sdd_dir=store.sdd_dir,
        plan_path=destination,
        plans_root=plans_root,
        prompt_path=_resolved_prompt_path(
            destination, prompt_path, expect_prompt_snapshot=expect_prompt_snapshot
        ),
        store=store,
        primary_root=primary_root or resolve_checkout_anchor().primary_root,
    )
    content = format_with_prettier(content)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")
    return _PlanArchiveResult(path=destination, written=True)


def _resolved_prompt_path(
    destination: Path,
    prompt_path: Path | None,
    *,
    expect_prompt_snapshot: bool = False,
) -> Path | None:
    if prompt_path is not None:
        return prompt_path

    # Historical prompts remain in the plans tree until the migration phase.
    # New prompt archives live in the agents sidecar and are indicated by the
    # caller's explicit expectation rather than a plans-tree existence probe.
    archived_prompt = destination.parent / "prompts" / destination.name
    if expect_prompt_snapshot:
        return prompt_path or destination
    return archived_prompt if archived_prompt.is_file() else None


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


__all__ = [
    "archive_plan_file",
    "plan_archive_destination",
]
