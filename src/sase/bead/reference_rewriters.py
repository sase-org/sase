"""Pure planners for bead-ID references outside the canonical bead store.

The Rust core owns bead-ID token boundaries and produces the migration map.
This module limits host-side rewrites to structured fields owned by plans and
ChangeSpecs, leaving free-form historical text byte-identical.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path

from sase.core.bead_prefix_migration import rewrite_id_tokens


class ReferenceRewriteAction(StrEnum):
    """Disposition for one planned reference target."""

    REWRITE = "rewrite"
    SKIP = "skip"
    BLOCKER = "blocker"


@dataclass(frozen=True, slots=True)
class ReferenceRewritePlan:
    """Complete, deterministic rewrite decision for one file preimage."""

    path: Path
    target_kind: str
    preimage_digest: str
    rewritten_bytes: bytes
    action: ReferenceRewriteAction
    replacement_counts: Mapping[str, int]
    reason: str | None = None

    @property
    def changed(self) -> bool:
        return self.action is ReferenceRewriteAction.REWRITE

    @property
    def total_replacements(self) -> int:
        return sum(self.replacement_counts.values())


def plan_plan_reference_rewrite(
    path: Path | str,
    preimage: bytes,
    bead_id_map: Mapping[str, str],
    *,
    bead_url_resolver: Callable[[str], str | None] | None = None,
) -> ReferenceRewritePlan:
    """Plan one codec-driven plan-frontmatter and generated-header rewrite."""

    target = Path(path)
    digest = _digest(preimage)
    decoded = _decode(target, preimage, "plan", digest)
    if isinstance(decoded, ReferenceRewritePlan):
        return decoded
    replacements = dict(bead_id_map)
    audit = rewrite_id_tokens(decoded, replacements)
    if audit.total_replacements == 0:
        return _skip(target, "plan", digest, preimage, "no mapped bead IDs")

    from sase.sdd.plan_tiers import parse_plan_frontmatter

    frontmatter, parse_error = parse_plan_frontmatter(decoded)
    if parse_error is not None:
        return _blocker(target, "plan", digest, preimage, parse_error)
    if not decoded.startswith("---\n"):
        if decoded.startswith("---"):
            return _blocker(
                target,
                "plan",
                digest,
                preimage,
                "unsupported or malformed plan frontmatter opening",
            )
        from sase.sdd.plan_header_block import (
            PlanHeaderSectionKind,
            parse_plan_header_block,
        )

        parsed_without_frontmatter = parse_plan_header_block(decoded)
        orphan_bead_header = next(
            (
                section
                for section in parsed_without_frontmatter.sections
                if section.kind is PlanHeaderSectionKind.BEAD
                and any(
                    value is not None
                    and rewrite_id_tokens(value, replacements).total_replacements
                    for value in (section.label, section.target)
                )
            ),
            None,
        )
        if orphan_bead_header is not None:
            return _blocker(
                target,
                "plan",
                digest,
                preimage,
                "mapped generated BEAD header has no owning bead frontmatter",
            )
        return _skip(
            target,
            "plan",
            digest,
            preimage,
            "mapped IDs occur only outside owned plan frontmatter",
        )

    field_updates: dict[str, str] = {}
    counts: dict[str, int] = {}
    for field in ("bead_id", "bead", "parent_bead"):
        value = frontmatter.get(field)
        if value in (None, ""):
            continue
        if not isinstance(value, str):
            outcome = rewrite_id_tokens(str(value), replacements)
            if outcome.total_replacements:
                return _blocker(
                    target,
                    "plan",
                    digest,
                    preimage,
                    f"mapped bead ID is stored in non-string `{field}` frontmatter",
                )
            continue
        outcome = rewrite_id_tokens(value, replacements)
        if outcome.total_replacements == 0:
            continue
        if value.strip() not in replacements:
            return _blocker(
                target,
                "plan",
                digest,
                preimage,
                f"ambiguous mapped bead ID in `{field}` frontmatter",
            )
        field_updates[field] = outcome.text
        _merge_counts(counts, outcome.replacement_counts)

    from sase.sdd.plan_header_block import (
        PlanHeaderDisposition,
        PlanHeaderSectionKind,
        parse_plan_header_block,
    )

    parsed_header = parse_plan_header_block(decoded)
    prior_bead = next(
        (
            section
            for section in parsed_header.sections
            if section.kind is PlanHeaderSectionKind.BEAD
        ),
        None,
    )
    header_has_mapping = False
    if prior_bead is not None:
        for value in (prior_bead.label, prior_bead.target):
            if value is None:
                continue
            outcome = rewrite_id_tokens(value, replacements)
            if outcome.total_replacements:
                header_has_mapping = True
                _merge_counts(counts, outcome.replacement_counts)

    if not field_updates and not header_has_mapping:
        return _skip(
            target,
            "plan",
            digest,
            preimage,
            "mapped IDs occur only outside owned plan fields",
        )
    if parsed_header.disposition is PlanHeaderDisposition.INVALID:
        return _blocker(
            target,
            "plan",
            digest,
            preimage,
            parsed_header.reason or "invalid generated plan header",
        )

    from sase.sdd.frontmatter import set_frontmatter_fields

    rewritten = (
        set_frontmatter_fields(decoded, field_updates) if field_updates else decoded
    )
    primary = frontmatter.get("bead_id") or frontmatter.get("bead")
    if isinstance(primary, str) and primary.strip():
        canonical_primary = replacements.get(primary.strip(), primary.strip())

        def resolve_target(bead_id: str) -> str | None:
            if bead_url_resolver is not None:
                return bead_url_resolver(bead_id)
            if prior_bead is None or prior_bead.target is None:
                return None
            target_outcome = rewrite_id_tokens(prior_bead.target, replacements)
            if bead_id == canonical_primary:
                return target_outcome.text
            return None

        from sase.sdd.plan_header_writes import refresh_bead_plan_section

        rewritten = refresh_bead_plan_section(
            rewritten,
            page_target_resolver=resolve_target,
        )
    elif header_has_mapping:
        return _blocker(
            target,
            "plan",
            digest,
            preimage,
            "mapped generated BEAD header has no owning bead frontmatter",
        )

    postimage = rewritten.encode("utf-8")
    if postimage == preimage:
        return _skip(target, "plan", digest, preimage, "owned fields are unchanged")
    return ReferenceRewritePlan(
        target,
        "plan",
        digest,
        postimage,
        ReferenceRewriteAction.REWRITE,
        dict(sorted(counts.items())),
    )


def plan_changespec_reference_rewrite(
    path: Path | str,
    preimage: bytes,
    bead_id_map: Mapping[str, str],
) -> ReferenceRewritePlan:
    """Plan exact mapped-ID rewrites in ChangeSpec ``BUG`` and ``REFS`` fields."""

    target = Path(path)
    digest = _digest(preimage)
    decoded = _decode(target, preimage, "changespec", digest)
    if isinstance(decoded, ReferenceRewritePlan):
        return decoded
    replacements = dict(bead_id_map)
    audit = rewrite_id_tokens(decoded, replacements)
    if audit.total_replacements == 0:
        return _skip(target, "changespec", digest, preimage, "no mapped bead IDs")

    try:
        from sase.core.parser_facade import parse_project_bytes

        parsed_before = parse_project_bytes(str(target), preimage)
    except Exception as exc:  # noqa: BLE001 - converted to a migration blocker.
        return _blocker(
            target,
            "changespec",
            digest,
            preimage,
            f"ChangeSpec parser rejected preimage: {exc}",
        )

    lines = decoded.splitlines(keepends=True)
    rewritten_lines: list[str] = []
    counts: dict[str, int] = {}
    current_name: str | None = None
    affected_names: set[str] = set()
    in_refs = False
    blocker: str | None = None

    for line in lines:
        bare, ending = _line_parts(line)
        if bare.startswith("NAME: "):
            current_name = bare[6:].strip()
            in_refs = False
        elif bare.startswith("REFS:"):
            in_refs = True
            if bare != "REFS:":
                outcome = rewrite_id_tokens(bare, replacements)
                if outcome.total_replacements:
                    blocker = "ambiguous mapped bead ID on malformed REFS header"
        elif _is_changespec_header(bare):
            in_refs = False

        updated = bare
        if bare.startswith("BUG: "):
            outcome = rewrite_id_tokens(bare[5:], replacements)
            if outcome.total_replacements:
                if current_name is None:
                    blocker = "mapped BUG field is outside a ChangeSpec"
                updated = f"BUG: {outcome.text}"
                _merge_counts(counts, outcome.replacement_counts)
                if current_name is not None:
                    affected_names.add(current_name)
        elif bare.startswith("BUG:"):
            outcome = rewrite_id_tokens(bare, replacements)
            if outcome.total_replacements:
                blocker = "ambiguous mapped bead ID on malformed BUG field"
        elif in_refs and bare.startswith("  ") and bare.strip():
            prefix = bare[: len(bare) - len(bare.lstrip())]
            outcome = rewrite_id_tokens(bare.lstrip(), replacements)
            if outcome.total_replacements:
                if current_name is None:
                    blocker = "mapped REFS entry is outside a ChangeSpec"
                updated = f"{prefix}{outcome.text}"
                _merge_counts(counts, outcome.replacement_counts)
                if current_name is not None:
                    affected_names.add(current_name)
        elif in_refs and bare.strip():
            outcome = rewrite_id_tokens(bare, replacements)
            if outcome.total_replacements:
                blocker = "ambiguous mapped bead ID in malformed REFS entry"
        rewritten_lines.append(f"{updated}{ending}")

    if blocker is not None:
        return _blocker(target, "changespec", digest, preimage, blocker)
    if not counts:
        return _skip(
            target,
            "changespec",
            digest,
            preimage,
            "mapped IDs occur only outside BUG and REFS",
        )

    parsed_names = {record.name for record in parsed_before}
    missing = sorted(affected_names - parsed_names)
    if missing:
        return _blocker(
            target,
            "changespec",
            digest,
            preimage,
            "owned fields belong to malformed ChangeSpec(s): " + ", ".join(missing),
        )

    postimage = "".join(rewritten_lines).encode("utf-8")
    try:
        parsed_after = parse_project_bytes(str(target), postimage)
    except Exception as exc:  # noqa: BLE001 - converted to a migration blocker.
        return _blocker(
            target,
            "changespec",
            digest,
            preimage,
            f"ChangeSpec parser rejected rewrite: {exc}",
        )
    before_identity = [(item.name, item.status) for item in parsed_before]
    after_identity = [(item.name, item.status) for item in parsed_after]
    if after_identity != before_identity:
        return _blocker(
            target,
            "changespec",
            digest,
            preimage,
            "ChangeSpec identities changed during structured rewrite",
        )
    return ReferenceRewritePlan(
        target,
        "changespec",
        digest,
        postimage,
        ReferenceRewriteAction.REWRITE,
        dict(sorted(counts.items())),
    )


def apply_changespec_reference_rewrite(plan: ReferenceRewritePlan) -> bool:
    """Digest-revalidate and atomically apply one ChangeSpec rewrite plan."""

    if plan.target_kind != "changespec":
        raise ValueError("reference rewrite plan does not target a ChangeSpec")
    if plan.action is ReferenceRewriteAction.BLOCKER:
        raise ValueError(plan.reason or "blocked ChangeSpec reference rewrite")
    if plan.action is ReferenceRewriteAction.SKIP:
        return False

    from sase.ace.changespec import changespec_lock, write_changespec_atomic

    project_file = str(plan.path)
    with changespec_lock(project_file):
        current = plan.path.read_bytes()
        if _digest(current) != plan.preimage_digest:
            raise RuntimeError(f"ChangeSpec preimage changed: {plan.path}")
        write_changespec_atomic(
            project_file,
            plan.rewritten_bytes.decode("utf-8"),
            "Rewrite migrated bead references",
        )
    return True


def _decode(
    path: Path,
    preimage: bytes,
    kind: str,
    digest: str,
) -> str | ReferenceRewritePlan:
    try:
        return preimage.decode("utf-8")
    except UnicodeDecodeError as exc:
        return _blocker(
            path,
            kind,
            digest,
            preimage,
            f"file is not valid UTF-8 at byte {exc.start}",
        )


def _digest(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _skip(
    path: Path,
    kind: str,
    digest: str,
    preimage: bytes,
    reason: str,
) -> ReferenceRewritePlan:
    return ReferenceRewritePlan(
        path,
        kind,
        digest,
        preimage,
        ReferenceRewriteAction.SKIP,
        {},
        reason,
    )


def _blocker(
    path: Path,
    kind: str,
    digest: str,
    preimage: bytes,
    reason: str,
) -> ReferenceRewritePlan:
    return ReferenceRewritePlan(
        path,
        kind,
        digest,
        preimage,
        ReferenceRewriteAction.BLOCKER,
        {},
        reason,
    )


def _merge_counts(target: dict[str, int], source: Mapping[str, int]) -> None:
    for bead_id, count in source.items():
        target[bead_id] = target.get(bead_id, 0) + count


def _line_parts(line: str) -> tuple[str, str]:
    bare = line.rstrip("\r\n")
    return bare, line[len(bare) :]


def _is_changespec_header(line: str) -> bool:
    if line.startswith(("NAME: ", "DESCRIPTION:", "PARENT: ", "PR: ", "CL: ")):
        return True
    return line.startswith(
        (
            "BUG: ",
            "STATUS: ",
            "COMMITS:",
            "DELTAS:",
            "HOOKS:",
            "COMMENTS:",
            "MENTORS:",
            "TIMESTAMPS:",
        )
    )


__all__ = [
    "ReferenceRewriteAction",
    "ReferenceRewritePlan",
    "apply_changespec_reference_rewrite",
    "plan_changespec_reference_rewrite",
    "plan_plan_reference_rewrite",
]
