"""Validation, deduplication, and presentation resolution for task-type specs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
import hashlib
from types import MappingProxyType
from typing import Any

from sase.core.rust import require_rust_binding

from ._discovery import TaskTypeCandidate
from ._models import TaskTypeDiagnostic, TaskTypeProvenance, TaskTypeRecord

#: Terminal-cell glyph used when a spec declares none.
DEFAULT_TASK_TYPE_GLYPH = "•"  # •

#: Accents already claimed by other bead-facing systems, so a hash-assigned
#: task-type color can never repaint them: the four issue-type accents
#: (`sase.bead_type_presentation`), the flag "soon" accent
#: (`sase.bead_flag_presentation`), and the six pinned builtin task-type
#: accents from the plan (bug/ci/feature/flake/memory/github).
_RESERVED_ACCENT_COLORS: frozenset[str] = frozenset(
    {
        "#FFD700",
        "#87D7FF",
        "#D787FF",
        "#FF875F",
        "#FFAF00",
        "#FF5F5F",
        "#D7D700",
        "#5FD75F",
        "#00D7D7",
        "#8787FF",
        "#B2B2B2",
    }
)

#: Curated palette a task type without a declared ``accent_color`` hashes
#: into. Disjoint from ``_RESERVED_ACCENT_COLORS`` by construction.
TASK_TYPE_ACCENT_PALETTE: tuple[str, ...] = (
    "#5FAFFF",
    "#FF87D7",
    "#AFFF5F",
    "#FFD787",
    "#87FFD7",
    "#D7AF87",
    "#AF87FF",
    "#FF5FAF",
)


def validate_task_type_spec(spec: Mapping[str, Any]) -> str:
    """Validate *spec* through Rust and return its stable digest."""

    plain = _plain_mapping(spec)
    require_rust_binding("validate_task_type_spec")(plain)
    return str(require_rust_binding("task_type_spec_digest")(plain))


def validate_task_type_candidates(
    candidates: Sequence[TaskTypeCandidate],
    diagnostics: list[TaskTypeDiagnostic],
) -> tuple[TaskTypeRecord, ...]:
    """Validate and deduplicate task-type candidates (D4 conflict policy)."""

    records: list[TaskTypeRecord] = []
    seen: dict[str, TaskTypeRecord] = {}

    for raw_spec, provenance in candidates:
        spec = _plain_mapping(raw_spec)
        slug = _spec_text(spec, "task_type")
        if not slug:
            diagnostics.append(
                _invalid_task_type_diagnostic(
                    provenance,
                    slug=None,
                    reason="'task_type' is required and must be a nonempty string",
                )
            )
            continue
        existing = seen.get(slug)
        if existing is not None:
            if (
                existing.provenance.source == "builtin"
                and provenance.source != "builtin"
            ):
                diagnostics.append(
                    TaskTypeDiagnostic(
                        code="builtin_task_type_shadowed",
                        message=(
                            f"Task type '{slug}' from {provenance.label} is a "
                            f"reserved builtin slug; ignoring the {provenance.label} "
                            "definition"
                        ),
                        severity="error",
                        task_type=slug,
                        source=provenance.label,
                        package=provenance.package,
                        version=provenance.version,
                    )
                )
            else:
                diagnostics.append(
                    TaskTypeDiagnostic(
                        code="duplicate_task_type",
                        message=(
                            f"Task type '{slug}' from {provenance.label} duplicates "
                            f"{existing.provenance.label}; keeping the first"
                        ),
                        severity="error",
                        task_type=slug,
                        source=provenance.label,
                        package=provenance.package,
                        version=provenance.version,
                    )
                )
            continue
        try:
            digest = validate_task_type_spec(spec)
        except Exception as exc:
            diagnostics.append(
                _invalid_task_type_diagnostic(
                    provenance,
                    slug=slug,
                    reason=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        record = TaskTypeRecord(
            task_type=slug,
            spec=MappingProxyType(spec),
            digest=digest,
            provenance=provenance,
        )
        records.append(record)
        seen[slug] = record

    return tuple(records)


def resolve_task_type_presentation(
    records: Sequence[TaskTypeRecord],
    diagnostics: list[TaskTypeDiagnostic],
) -> tuple[TaskTypeRecord, ...]:
    """Assign resolved glyph/accent per D9 and warn on accent collisions."""

    resolved: list[TaskTypeRecord] = []
    seen_colors: dict[str, TaskTypeRecord] = {}
    for record in records:
        glyph = record.spec.get("glyph")
        accent = record.spec.get("accent_color")
        resolved_glyph = (
            glyph if isinstance(glyph, str) and glyph else DEFAULT_TASK_TYPE_GLYPH
        )
        resolved_accent = (
            accent
            if isinstance(accent, str) and accent
            else _hash_accent_color(record.task_type)
        )
        colliding = seen_colors.get(resolved_accent)
        if colliding is not None:
            diagnostics.append(
                TaskTypeDiagnostic(
                    code="duplicate_task_type_color",
                    message=(
                        f"Task types '{colliding.task_type}' and '{record.task_type}' "
                        f"both resolve to accent {resolved_accent}; declare "
                        "accent_color on one to disambiguate"
                    ),
                    severity="warning",
                    task_type=record.task_type,
                    source=record.provenance.label,
                )
            )
        else:
            seen_colors[resolved_accent] = record
        resolved.append(
            replace(
                record,
                resolved_glyph=resolved_glyph,
                resolved_accent_color=resolved_accent,
            )
        )
    return tuple(resolved)


def _hash_accent_color(slug: str) -> str:
    palette = [
        color
        for color in TASK_TYPE_ACCENT_PALETTE
        if color not in _RESERVED_ACCENT_COLORS
    ] or list(TASK_TYPE_ACCENT_PALETTE)
    digest = hashlib.sha256(slug.encode("utf-8")).digest()
    index = int.from_bytes(digest[:8], "big") % len(palette)
    return palette[index]


def _invalid_task_type_diagnostic(
    provenance: TaskTypeProvenance,
    *,
    slug: str | None,
    reason: str,
) -> TaskTypeDiagnostic:
    return TaskTypeDiagnostic(
        code="invalid_task_type",
        message=(
            f"Skipping task type {slug or '<unknown>'} from {provenance.label}: "
            f"{reason}"
        ),
        severity="error",
        task_type=slug,
        source=provenance.label,
        package=provenance.package,
        version=provenance.version,
    )


def _spec_text(value: object, key: str) -> str:
    if not isinstance(value, Mapping):
        return ""
    raw = value.get(key)
    return raw.strip() if isinstance(raw, str) else ""


def plain_task_type_spec(value: Mapping[Any, Any]) -> dict[str, Any]:
    """Return a JSON-ready copy of a task-type spec mapping."""

    return _plain_mapping(value)


def _plain_mapping(value: Mapping[Any, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        text_key = str(key)
        if isinstance(item, Mapping):
            result[text_key] = _plain_mapping(item)
        elif isinstance(item, list):
            result[text_key] = [
                _plain_mapping(element) if isinstance(element, Mapping) else element
                for element in item
            ]
        else:
            result[text_key] = item
    return result


__all__ = [
    "DEFAULT_TASK_TYPE_GLYPH",
    "TASK_TYPE_ACCENT_PALETTE",
    "plain_task_type_spec",
    "resolve_task_type_presentation",
    "validate_task_type_candidates",
    "validate_task_type_spec",
]
