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

from ._artifact_tab_contract import (
    ContractCompileResult,
    attach_contract,
    compile_builtin_contract,
    compile_provider_contract,
    contract_with_digit,
)
from ._artifact_tab_model import (
    ARTIFACTS_ACCENTS,
    ARTIFACTS_ICONS,
    FIXED_ARTIFACTS_PANE_IDS,
    ArtifactsSubTab,
    ArtifactsTabDescriptor,
    ProjectProviderRecord,
    ProviderDiscoveryIssue,
)


# Nine colors spaced around the OKLCH hue wheel at a shared lightness/chroma
# band chosen so every entry clears, against both the app's dark
# (#121212/#1E1E1E) and light (#E0E0E0/#D8D8D8) shell surfaces plus the
# identity chip's #1A1A1A text: a WCAG contrast ratio of at least 3.3, and a
# pairwise perceptual (OKLab Euclidean) distance of at least 0.09 from every
# other entry and from every reserved ``ARTIFACTS_ACCENTS`` color. Values are
# pinned hex so runtime assignment stays dependency-free and deterministic;
# see ``tests/ace/tui/test_artifacts_provider_palette.py`` for the checks
# that keep these properties true.
_PROVIDER_ACCENTS: tuple[str, ...] = (
    "#058D1D",
    "#198A76",
    "#1883B8",
    "#7268F2",
    "#9E5ECC",
    "#CB45AA",
    "#CC4F6C",
    "#B66538",
    "#777F17",
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
    label = labels[subtab]
    icon = ARTIFACTS_ICONS[subtab]
    accent = ARTIFACTS_ACCENTS[subtab]
    contract = compile_builtin_contract(
        subtab,
        label=label,
        icon=icon,
        accent=accent,
    )
    return attach_contract(
        ArtifactsTabDescriptor(
            id=subtab,
            label=label,
            accent=accent,
            pane_id=FIXED_ARTIFACTS_PANE_IDS[subtab],
            icon=icon,
        ),
        contract,
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
    configured_pane_ids = (
        "stitches",
        "patches",
        "beads",
        *(f"ref:{kind}" for kind in kinds),
        "files",
    )
    descriptors: list[ArtifactsTabDescriptor] = []
    for kind in kinds:
        records = by_kind.get(kind, [])
        kind_issues = issues_by_kind.get(kind, [])
        descriptors.append(
            _descriptor_for_provider_kind(
                kind,
                records,
                kind_issues,
                configured_pane_ids=configured_pane_ids,
            )
        )
    return tuple(sorted(descriptors, key=_provider_descriptor_sort_key))


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
            _with_digit(
                descriptor,
                (
                    _ARTIFACTS_DIGIT_KEYS[index]
                    if index < len(_ARTIFACTS_DIGIT_KEYS)
                    else None
                ),
                order=index,
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
        result.append(_with_digit(descriptor, digit, order=index))
    return tuple(result)


def _with_digit(
    descriptor: ArtifactsTabDescriptor,
    digit: str | None,
    *,
    order: int,
) -> ArtifactsTabDescriptor:
    contract = descriptor.contract
    if contract is None:
        return replace(descriptor, digit_shortcut=digit)
    return attach_contract(
        replace(descriptor, digit_shortcut=digit),
        contract_with_digit(contract, digit=digit, order=order),
    )


def _descriptor_for_provider_kind(
    kind: str,
    records: Sequence[ProjectProviderRecord],
    issues: Sequence[ProviderDiscoveryIssue],
    *,
    configured_pane_ids: tuple[str, ...],
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
    compiled: ContractCompileResult = compile_provider_contract(
        kind=kind,
        label=_provider_label(kind, spec or {}),
        icon=icon,
        accent=_provider_accent_for_kind(kind),
        spec=spec,
        provider_spec_digest=digest or (policy.digest if policy is not None else None),
        is_degraded=error is not None,
        configured_pane_ids=configured_pane_ids,
    )
    if compiled.error is not None:
        error = compiled.error
        error_code = compiled.error_code
        error_source = error_source or "artifacts_pane_contract"
    return attach_contract(
        ArtifactsTabDescriptor(
            id=f"ref:{kind}",
            label=compiled.contract.label,
            accent=compiled.contract.accent,
            pane_id=(
                "artifacts-plans-pane"
                if kind == "plan"
                else f"artifacts-ref-{_slug(kind)}-pane"
            ),
            icon=compiled.contract.icon,
            provider_kind=kind,
            provider_spec_digest=digest
            or (policy.digest if policy is not None else None),
            provider_spec=spec,
            error=error,
            error_code=error_code,
            error_source=error_source,
        ),
        compiled.contract,
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


def _provider_descriptor_sort_key(
    descriptor: ArtifactsTabDescriptor,
) -> tuple[int, tuple[object, ...], tuple[object, ...]]:
    contract = descriptor.contract
    return (
        0 if contract is None else contract.order,
        _natural_label_key(descriptor.label),
        _natural_label_key(descriptor.provider_kind or descriptor.id),
    )


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", value.casefold()).strip("-_")
    return slug or "document"
