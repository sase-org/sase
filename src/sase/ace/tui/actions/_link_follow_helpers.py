"""Shared helpers for host-owned ``$`` link-follow."""

from __future__ import annotations

from typing import Any

from sase.artifact_ref_entries import reference_for_agent_name
from sase.core.artifact_entry_target import ArtifactEntryTarget

from ..artifact_tabs import artifacts_pane_contract
from ..relations.artifact_links import parse_link_ref
from ..relations.link_index import LinkChip
from ..relations.link_keys import LinkRailItem
from ..tab_order import ARTIFACTS_TAB


def link_panel_reveal_flags(app: Any, chips: tuple[LinkChip, ...]) -> frozenset[int]:
    """Indices of *chips* whose target exists but is not selectable in place.

    Reuses the same pane ref resolution the follow path itself uses
    (:meth:`LinkFollowMixin._resolve_link_follow_target`), so the Links
    panel warns before a follow triggers the reveal ladder instead of
    only after. A chip already flagged dangling by ``_is_missing`` (no
    pane resolves it at all) is left alone -- that is a distinct,
    stronger warning -- and a still-loading destination pane is skipped,
    since "not yet in ``entry_targets()``" there is a loading artifact,
    not a real reveal need.
    """
    resolve = getattr(app, "_resolve_link_follow_target", None)
    navigator = getattr(app, "_artifacts_entry_navigator", None)
    if not callable(resolve) or not callable(navigator):
        return frozenset()
    flags: set[int] = set()
    for index, chip in enumerate(chips):
        if chip.neighbor_target is None:
            continue
        try:
            resolved = resolve(chip.neighbor_ref, chip.neighbor_target)
            pane = navigator(resolved.pane_id)
        except Exception:
            continue
        if pane is None or pane_is_loading(pane):
            continue
        entry_targets = getattr(pane, "entry_targets", None)
        if not callable(entry_targets) or resolved not in entry_targets():
            flags.add(index)
    return frozenset(flags)


def target_project_scope(target: ArtifactEntryTarget) -> str | None:
    contract = artifacts_pane_contract(target.pane_id)
    project_scoped = (
        contract.project_scoping
        if contract is not None
        else target.pane_id in {"patches", "beads"}
    )
    if project_scoped and target.parts:
        return target.parts[0] or None
    return None


def pane_is_loading(pane: Any) -> bool:
    if getattr(pane, "_loading", False) or getattr(pane, "_loading_full", False):
        return True
    # Stitches has no plain ``_loading`` flag: its collection worker and
    # asynchronous query-session evaluation are the equivalent in-flight
    # signals, so a follow into either counts as loading here too.
    worker = getattr(pane, "_collection_worker", None)
    if worker is not None and getattr(worker, "is_running", False):
        return True
    return bool(getattr(pane, "_query_result_pending", False))


def pane_label(target: ArtifactEntryTarget | None) -> str:
    if target is None:
        return "the destination pane"
    from ..artifact_tabs import descriptor_for_artifacts_pane_id

    descriptor = descriptor_for_artifacts_pane_id(target.pane_id)
    return descriptor.label if descriptor is not None else target.pane_id


def artifact_link_add_enabled(app: Any) -> bool:
    if getattr(app, "current_tab", None) != ARTIFACTS_TAB:
        return False
    return str(getattr(app, "current_artifacts_pane_key", "")) != "patches"


def cached_link_panel_staleness_notice(app: Any) -> str:
    notices: list[str] = []
    loading = bool(getattr(app, "_link_index_loading", False))
    if loading and getattr(app, "_link_index", None) is not None:
        notices.append("Link index refresh in progress; showing the previous index.")
    elif loading:
        notices.append("Link index refresh in progress.")
    errors = tuple(str(error) for error in getattr(app, "_link_index_errors", ()))
    if errors:
        joined = "; ".join(errors[:3])
        suffix = "" if len(errors) <= 3 else f"; +{len(errors) - 3} more"
        notices.append(f"Some project link indexes were skipped: {joined}{suffix}")
    return "\n".join(notices)


def artifact_link_index_drift_notice() -> str:
    try:
        from sase.artifact_cli.link_health import inspect_artifact_link_health
        from sase.sdd.artifact_link_drift import format_artifact_link_index_drift

        report = inspect_artifact_link_health(fix=False)
    except Exception as exc:  # noqa: BLE001 - panel notice, not modal failure
        return f"Index drift unavailable: {exc}"
    if report.skipped:
        return ""
    if report.errors:
        joined = "; ".join(report.errors[:3])
        suffix = "" if len(report.errors) <= 3 else f"; +{len(report.errors) - 3} more"
        return f"Index drift unavailable: {joined}{suffix}"
    if not report.aggregate_drift.has_drift:
        return ""
    return f"Index stale: {format_artifact_link_index_drift(report.aggregate_drift)}"


def combine_notices(*notices: str) -> str:
    return "\n".join(notice for notice in notices if notice)


def scope_label(item: LinkRailItem | None) -> str:
    if item is None:
        return ""
    if item.projected_group:
        return f"{item.count} {_plural_kind(item.neighbor_kind)}"
    return item.chip.label


def _plural_kind(kind: str) -> str:
    if kind == "stitch":
        return "stitches"
    if kind.endswith("s"):
        return kind
    return f"{kind}s" if kind else "links"


def readonly_link_source(chip: LinkChip) -> str:
    if chip.origin == "projected" and chip.created_by.startswith("projection:"):
        return chip.created_by
    return chip.origin or "read-only"


def link_chip_endpoints(subject_ref: str, chip: LinkChip) -> tuple[str, str]:
    if chip.this_is_source:
        return subject_ref, chip.neighbor_ref
    return chip.neighbor_ref, subject_ref


def remove_artifact_link(
    source_ref: str,
    target_ref: str,
    relation: str,
) -> dict[str, Any]:
    from sase.artifact_cli.link_ops import remove_artifact_link as remove_store_link

    return remove_store_link(
        source_ref=source_ref,
        target_ref=target_ref,
        relation=relation,
    )


def agent_matches_ref(agent: Any, payload: str) -> bool:
    payload_key = payload.casefold()
    for name in _agent_candidate_names(agent):
        if name.casefold() == payload_key:
            return True
        ref = reference_for_agent_name(name)
        parsed = parse_link_ref("" if ref is None else ref)
        if parsed is not None and parsed == ("agent", payload):
            return True
    return False


def _agent_candidate_names(agent: Any) -> tuple[str, ...]:
    names: list[str] = []
    for attr in (
        "name",
        "agent_name",
        "presented_agent_name",
        "presented_identity_name",
        "display_name",
        "cl_name",
    ):
        value = getattr(agent, attr, None)
        if isinstance(value, str) and value:
            names.append(value)
    for method_name in (
        "family_reference_name",
        "presented_family_reference_name",
        "presented_clan_reference_name",
    ):
        method = getattr(agent, method_name, None)
        if not callable(method):
            continue
        value = method()
        if isinstance(value, str) and value:
            names.append(value)
    return tuple(dict.fromkeys(names))


def chop_matches(
    item: Any,
    snapshots: Any,
    lumberjack: str,
    base_chop: str,
) -> bool:
    from ..widgets.bgcmd_list import ChopItem

    if not isinstance(item, ChopItem) or item.lumberjack_name != lumberjack:
        return False
    if item.chop_name == base_chop:
        return True
    snapshot = snapshots.get((item.lumberjack_name, item.chop_name))
    return bool(
        snapshot is not None and snapshot.base_identity == (lumberjack, base_chop)
    )
