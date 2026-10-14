"""Memoized Patch relation-index construction.

The full edge graph (ancestors/children/siblings plus artifact-link edges) is
expensive: it walks the artifact-links aggregate. Startup and hidden-tab
watcher reloads keep a cheap targets-only index so ``$`` link-follow still
resolves Patch identities. Real builds are counted for startup telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Lock
from typing import Any

from ....patch import Patch
from sase.ace.tui._artifact_tab_model import ARTIFACTS_LABELS
from sase.ace.tui.relations.artifact_links import ArtifactLinksSnapshot
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relations import RelationIndex, build_relation_index

#: Auto-refresh uses this same predicate for the Patches surface. Keep one.
_PATCHES_TAB = "artifacts"
_PATCHES_SUBTAB = "patches"


def patches_pane_is_visible(app: object) -> bool:
    """Return whether the Artifacts tab is showing the Patches pane.

    This is the auto-refresh tick's Patches predicate: Artifacts tab with
    the Patches subtab selected. Test doubles without a subtab attribute
    default to Patches, matching ``_auto_refresh_surfaces``.
    """
    return getattr(app, "current_tab", None) == _PATCHES_TAB and (
        getattr(app, "current_artifacts_subtab", _PATCHES_SUBTAB) == _PATCHES_SUBTAB
    )


@dataclass
class _PatchRelationMemo:
    """Single-entry process-local memo for the Patch relation index."""

    source_key: tuple[object, ...]
    patches: tuple[Patch, ...]
    index: RelationIndex | None
    deferred: bool
    full: bool


_MEMO_LOCK = Lock()
_MEMO: _PatchRelationMemo | None = None
_MEMO_PUBLISH_SEQ = 0
_REAL_BUILD_COUNT = 0


@dataclass
class _FullInflight:
    """One in-progress full Patch relation-index build."""

    event: Event = field(default_factory=Event)
    index: RelationIndex | None = None
    deferred: bool = False
    error: BaseException | None = None
    # Strong refs so patch ids cannot be recycled mid-build.
    patches: tuple[Patch, ...] = ()
    seq: int = 0
    epoch: int = 0


_FULL_INFLIGHT: dict[tuple[object, ...], _FullInflight] = {}
_FULL_SEQ = 0
_MEMO_EPOCH = 0


def patch_relation_index_real_build_count() -> int:
    """Return how many full Patch relation indexes this process has built."""
    return _REAL_BUILD_COUNT


def clear_patch_relation_index_memo() -> None:
    """Drop the process-local memo and real-build counter. Tests only."""
    global _MEMO, _MEMO_PUBLISH_SEQ, _REAL_BUILD_COUNT, _MEMO_EPOCH
    with _MEMO_LOCK:
        _MEMO_EPOCH += 1
        _MEMO = None
        _MEMO_PUBLISH_SEQ = 0
        _REAL_BUILD_COUNT = 0
        _FULL_INFLIGHT.clear()


def _identity_matches(cached: tuple[Patch, ...], patches: list[Patch]) -> bool:
    if len(cached) != len(patches):
        return False
    return all(left is right for left, right in zip(cached, patches, strict=True))


def _snapshot_source_key(
    artifact_links: ArtifactLinksSnapshot | None,
) -> tuple[object, ...]:
    if artifact_links is None:
        return ()
    return tuple(artifact_links.source_key)


def _load_links(artifact_links: Any | None) -> ArtifactLinksSnapshot:
    if isinstance(artifact_links, ArtifactLinksSnapshot):
        return artifact_links
    from sase.ace.tui.relations import load_artifact_links_snapshot

    return load_artifact_links_snapshot(None)


def _patch_target(patch: Patch) -> ArtifactEntryTarget:
    return ArtifactEntryTarget(
        pane_id="patches",
        parts=(patch.project_name, patch.name),
    )


def _build_full_patch_index(
    patches: list[Patch], links: ArtifactLinksSnapshot, contract: Any
) -> RelationIndex | None:
    """Build the full Patch relation index on a worker, not the UI pump."""

    from sase.ace.tui.models.patch_graph_index import build_patch_graph_index
    from sase.ace.tui.relations import build_patches_relation_index
    from sase.ace.tui.relations._support import relation_index_if_enabled

    return relation_index_if_enabled(
        contract,
        lambda compiled: build_patches_relation_index(
            patches,
            build_patch_graph_index(patches),
            contract=compiled,
            artifact_links=links,
        ),
    )


def _targets_only_index(patches: list[Patch], contract: Any) -> RelationIndex:
    return build_relation_index(
        pane_id=contract.id,
        relations=contract.relations,
        edges=(),
        known_targets=frozenset(_patch_target(patch) for patch in patches),
    )


def resolve_patch_relation_index(
    patches: list[Patch],
    *,
    artifact_links: Any | None = None,
    build_relations: bool,
) -> tuple[RelationIndex | None, bool]:
    """Return ``(index, deferred)`` for *patches*, using the process-local memo.

    A memo hit requires the artifact-links ``source_key`` and the Patch
    objects themselves (compared by identity, holding strong references so
    ids cannot be recycled). A cached full index satisfies a targets-only
    request. A cached targets-only index does not satisfy a full request.
    Concurrent full builds for one signature compile once: late callers
    wait on the in-flight build instead of rebuilding.
    """
    global _MEMO, _MEMO_PUBLISH_SEQ, _FULL_SEQ, _REAL_BUILD_COUNT

    from sase.ace.tui._artifact_tab_contract import compile_builtin_contract
    from sase.ace.tui._artifact_tab_model import PaneCapability

    links = _load_links(artifact_links)
    source_key = _snapshot_source_key(links)
    contract = compile_builtin_contract(
        "patches", label=ARTIFACTS_LABELS["patches"], icon="", accent=""
    )
    if contract is None or not contract.has(PaneCapability.RELATIONS):
        return None, False

    with _MEMO_LOCK:
        memo = _MEMO
        if (
            memo is not None
            and memo.source_key == source_key
            and _identity_matches(memo.patches, patches)
            and (memo.full or not build_relations)
        ):
            return memo.index, memo.deferred

    if build_relations:
        key = (source_key, tuple(id(patch) for patch in patches))
        with _MEMO_LOCK:
            memo = _MEMO
            if (
                memo is not None
                and memo.source_key == source_key
                and _identity_matches(memo.patches, patches)
                and memo.full
            ):
                return memo.index, memo.deferred
            inflight = _FULL_INFLIGHT.get(key)
            if inflight is None:
                _FULL_SEQ += 1
                inflight = _FullInflight(
                    patches=tuple(patches),
                    seq=_FULL_SEQ,
                    epoch=_MEMO_EPOCH,
                )
                _FULL_INFLIGHT[key] = inflight
                owner = True
            else:
                owner = False
        if not owner:
            # Wait outside the memo lock; a failed build raises here and a
            # later call retries.
            inflight.event.wait()
            with _MEMO_LOCK:
                memo = _MEMO
                if (
                    memo is not None
                    and memo.source_key == source_key
                    and _identity_matches(memo.patches, patches)
                    and memo.full
                ):
                    return memo.index, memo.deferred
                if inflight.error is not None:
                    raise inflight.error
                return inflight.index, inflight.deferred
        try:
            index = _build_full_patch_index(patches, links, contract)
        except BaseException as exc:
            with _MEMO_LOCK:
                if _FULL_INFLIGHT.get(key) is inflight:
                    del _FULL_INFLIGHT[key]
                inflight.error = exc
                inflight.event.set()
            raise
        with _MEMO_LOCK:
            if inflight.epoch == _MEMO_EPOCH:
                # Count every successful full build in this memo epoch,
                # including a result superseded by a newer publication.
                _REAL_BUILD_COUNT += 1
            # A slow older build must not replace a newer published memo.
            if inflight.epoch == _MEMO_EPOCH and inflight.seq >= _MEMO_PUBLISH_SEQ:
                _MEMO = _PatchRelationMemo(
                    source_key=source_key,
                    patches=tuple(patches),
                    index=index,
                    deferred=False,
                    full=True,
                )
                _MEMO_PUBLISH_SEQ = inflight.seq
            if _FULL_INFLIGHT.get(key) is inflight:
                del _FULL_INFLIGHT[key]
            inflight.index = index
            inflight.deferred = False
            inflight.event.set()
        return index, False

    index = _targets_only_index(patches, contract)
    deferred = True
    with _MEMO_LOCK:
        memo = _MEMO
        if (
            memo is not None
            and memo.source_key == source_key
            and _identity_matches(memo.patches, patches)
            and memo.full
        ):
            return memo.index, memo.deferred
        _MEMO = _PatchRelationMemo(
            source_key=source_key,
            patches=tuple(patches),
            index=index,
            deferred=deferred,
            full=False,
        )
    return index, deferred
