"""Descriptor construction for fixed and provider-backed Artifacts panes.

Turns discovery output (:mod:`sase.ace.tui._artifact_tab_discovery`) into the
immutable :class:`ArtifactsTabDescriptor` rows the TUI renders, and assigns the
digit shortcuts that number those panes.  Callers go through
:mod:`sase.ace.tui.artifact_tabs`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
import hashlib
import re
from typing import Any

from rich.cells import cell_len

from sase.notification_gates.model_validation import GateError, validate_icon
from sase.sidecar_ref_config import DEFAULT_DOCUMENT_TAB_ICON, REF_ICON_CONFIG_KEY

from ._artifact_tab_model import (
    ARTIFACTS_ACCENTS,
    ARTIFACTS_ICONS,
    FIXED_ARTIFACTS_PANE_IDS,
    ArtifactsSubTab,
    ArtifactsTabDescriptor,
    ProjectProviderRecord,
    ProviderDiscoveryIssue,
)


_PROVIDER_ACCENTS: tuple[str, ...] = (
    "#AF87FF",
    "#5FAFFF",
    "#5FD7AF",
    "#FF87D7",
    "#87D7FF",
    "#D7AF5F",
)

_ARTIFACTS_DIGIT_KEYS: tuple[str, ...] = tuple(str(digit) for digit in range(1, 10))


def fixed_descriptor(subtab: ArtifactsSubTab) -> ArtifactsTabDescriptor:
    """Return the descriptor for one of the four built-in Artifacts panes."""

    labels = {
        "patches": "Patch",
        "stitches": "Stitch",
        "beads": "Bead",
        "files": "File",
    }
    return ArtifactsTabDescriptor(
        id=subtab,
        label=labels[subtab],
        accent=ARTIFACTS_ACCENTS[subtab],
        pane_id=FIXED_ARTIFACTS_PANE_IDS[subtab],
        icon=ARTIFACTS_ICONS[subtab],
    )


def provider_descriptors(
    provider_records: Iterable[ProjectProviderRecord],
    issues: Iterable[ProviderDiscoveryIssue] = (),
) -> tuple[ArtifactsTabDescriptor, ...]:
    """Return one descriptor per discovered ref kind, degraded kinds included."""

    by_kind: dict[str, list[ProjectProviderRecord]] = {}
    for record in provider_records:
        by_kind.setdefault(record.policy.ref_kind, []).append(record)

    issues_by_kind: dict[str, list[ProviderDiscoveryIssue]] = {}
    for issue in issues:
        kind = issue.kind or "plan"
        issues_by_kind.setdefault(kind, []).append(issue)

    kinds = set(by_kind) | set(issues_by_kind)
    descriptors: list[ArtifactsTabDescriptor] = []
    for kind in sorted(kinds, key=_natural_label_key):
        records = by_kind.get(kind, [])
        kind_issues = issues_by_kind.get(kind, [])
        descriptors.append(_descriptor_for_provider_kind(kind, records, kind_issues))
    return tuple(descriptors)


def assign_artifacts_digit_shortcuts(
    descriptors: Sequence[ArtifactsTabDescriptor],
) -> tuple[ArtifactsTabDescriptor, ...]:
    """Number Artifacts panes by visual position, Files highest.

    ``descriptors`` must arrive in visual (left-to-right) order, with the
    Files pane last. The Files descriptor (``id == "files"``) always
    receives a digit shortcut, and it is always the highest digit assigned:
    its 1-based position clamped to the last available digit. Every other
    descriptor receives its own 1-based positional digit as long as that
    digit is strictly lower than the Files digit; any pane beyond that
    (only reachable with more than nine panes) receives
    ``digit_shortcut=None``. If no descriptor has ``id == "files"``
    (defensive; not reachable from
    :func:`sase.ace.tui.artifact_tabs.resolve_artifacts_subtabs`), this falls
    back to plain positional numbering with ``None`` past the ninth pane.
    """

    files_index = next(
        (
            index
            for index, descriptor in enumerate(descriptors)
            if descriptor.id == "files"
        ),
        None,
    )
    if files_index is None:
        return tuple(
            replace(
                descriptor,
                digit_shortcut=(
                    _ARTIFACTS_DIGIT_KEYS[index]
                    if index < len(_ARTIFACTS_DIGIT_KEYS)
                    else None
                ),
            )
            for index, descriptor in enumerate(descriptors)
        )

    files_digit_index = min(len(descriptors), len(_ARTIFACTS_DIGIT_KEYS)) - 1
    result: list[ArtifactsTabDescriptor] = []
    for index, descriptor in enumerate(descriptors):
        if index == files_index:
            digit = _ARTIFACTS_DIGIT_KEYS[files_digit_index]
        elif index < files_digit_index:
            digit = _ARTIFACTS_DIGIT_KEYS[index]
        else:
            digit = None
        result.append(replace(descriptor, digit_shortcut=digit))
    return tuple(result)


def _descriptor_for_provider_kind(
    kind: str,
    records: Sequence[ProjectProviderRecord],
    issues: Sequence[ProviderDiscoveryIssue],
) -> ArtifactsTabDescriptor:
    healthy = [record for record in records if record.policy.spec is not None]
    policy = (healthy[0].policy if healthy else None) or (
        records[0].policy if records else None
    )
    spec = dict(policy.spec) if policy is not None and policy.spec is not None else None
    if spec is None and kind == "plan":
        from sase.artifact_providers import builtin_plan_ref_provider_spec

        spec = builtin_plan_ref_provider_spec()
    ref = spec.get("ref") if isinstance(spec, Mapping) else None
    icon = (
        _sanitize_tab_icon(ref.get(REF_ICON_CONFIG_KEY))
        if isinstance(ref, Mapping)
        else ""
    ) or DEFAULT_DOCUMENT_TAB_ICON
    digest = "|".join(
        sorted(
            {value for record in records if (value := record.policy.digest) is not None}
        )
    )
    error: str | None = None
    error_code: str | None = None
    error_source: str | None = None
    if not healthy and issues:
        issue = issues[0]
        error = issue.message
        error_code = issue.code
        error_source = issue.source
    return ArtifactsTabDescriptor(
        id=f"ref:{kind}",
        label=_provider_label(kind, spec or {}),
        accent=_provider_accent_for_kind(kind),
        pane_id=(
            "artifacts-plans-pane"
            if kind == "plan"
            else f"artifacts-ref-{_slug(kind)}-pane"
        ),
        icon=icon,
        provider_kind=kind,
        provider_spec_digest=digest or (policy.digest if policy is not None else None),
        provider_spec=spec,
        error=error,
        error_code=error_code,
        error_source=error_source,
    )


def _provider_accent_for_kind(kind: str) -> str:
    """Return a stable provider accent derived from ``ref_kind``.

    Pinned built-in kinds (``plan``) keep their ``ARTIFACTS_ACCENTS`` colour.
    Every other kind hashes onto the provider palette after reserved built-in
    colours are removed, so installing an unrelated sidecar cannot repaint an
    existing tab and a provider can never draw a built-in's colour.
    """

    tab_id = f"ref:{kind}"
    pinned = ARTIFACTS_ACCENTS.get(tab_id)
    if pinned is not None:
        return pinned
    reserved = frozenset(ARTIFACTS_ACCENTS.values())
    palette = [color for color in _PROVIDER_ACCENTS if color not in reserved]
    if not palette:
        palette = list(_PROVIDER_ACCENTS)
    digest = hashlib.sha256(kind.encode("utf-8")).digest()
    return palette[int.from_bytes(digest[:8], "big") % len(palette)]


def _provider_label(kind: str, spec: Mapping[str, Any]) -> str:
    for candidate in (
        spec.get("label"),
        (spec.get("ref") or {}).get("label")
        if isinstance(spec.get("ref"), Mapping)
        else None,
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    label = kind.replace("_", " ").replace("-", " ").strip().title()
    if not label:
        return "Document"
    return label


def _sanitize_tab_icon(raw: object) -> str:
    """Return a safe Artifacts tab icon, or ``""`` for stored junk."""
    try:
        icon = validate_icon(raw, "ref.icon")
    except GateError:
        return ""
    if icon is None or cell_len(icon) > 2:
        return ""
    return icon


def _natural_label_key(value: str) -> tuple[object, ...]:
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", value)
    )


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", value.casefold()).strip("-_")
    return slug or "document"
