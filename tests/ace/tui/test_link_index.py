"""Tests for the app-owned O(1) link-graph index (bead:sase-ug.5)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from sase.ace.tui._artifact_tab_model import ARTIFACTS_ACCENTS, ARTIFACTS_ICONS
from sase.ace.tui.artifact_tabs import reset_artifacts_subtabs_cache
from sase.ace.tui.relations.artifact_links import ArtifactLinksSnapshot
from sase.ace.tui.relations.link_index import _build_link_index
from sase.ace.tui.relations.link_subject import _CHOP_ACCENT, _CHOP_ICON
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.core.artifact_entry_target import ArtifactEntryTarget


def _snapshot(rows: tuple[Mapping[str, Any], ...]) -> ArtifactLinksSnapshot:
    return ArtifactLinksSnapshot(rows=rows, source_key=("test",))


def test_empty_snapshot_yields_empty_index() -> None:
    index = _build_link_index(_snapshot(()))
    assert index.chips_for("bead:sase-1") == ()
    assert index.target_for("bead:sase-1") is None
    assert "bead:sase-1" not in index.by_ref
    assert "bead:sase-1" not in index.targets_by_ref


def test_directed_relation_has_perspective_corrected_labels() -> None:
    index = _build_link_index(
        _snapshot(
            (
                {
                    "source_ref": "plan:202608/a.md",
                    "relation": "implements",
                    "target_ref": "bead:sase-1",
                    "description": "lands the design",
                    "origin": "manual",
                    "uses": 1,
                },
            )
        )
    )
    source_chips = index.chips_for("plan:202608/a.md")
    target_chips = index.chips_for("bead:sase-1")
    assert len(source_chips) == 1
    assert len(target_chips) == 1
    assert source_chips[0].label == "implements"
    assert source_chips[0].this_is_source is True
    assert source_chips[0].neighbor_ref == "bead:sase-1"
    assert source_chips[0].why == "lands the design"
    assert target_chips[0].label == "implemented-by"
    assert target_chips[0].this_is_source is False
    assert target_chips[0].neighbor_ref == "plan:202608/a.md"
    assert target_chips[0].directed is True


def test_awaits_rows_index_with_perspective_labels_and_no_write() -> None:
    index = _build_link_index(
        _snapshot(
            (
                {
                    "source_ref": "agent:alice.athena.9w",
                    "relation": "awaits",
                    "target_ref": "bead:sase-1",
                    "description": "wait_for_beads names bead sase-1",
                    "origin": "projected",
                    "created_by": "projection:agent-wait-bead",
                    "uses": 1,
                },
            )
        )
    )
    source_chips = index.chips_for("agent:alice.athena.9w")
    target_chips = index.chips_for("bead:sase-1")
    assert len(source_chips) == 1
    assert len(target_chips) == 1
    assert source_chips[0].label == "awaits"
    assert source_chips[0].this_is_source is True
    assert source_chips[0].writable is False
    assert target_chips[0].label == "awaited-by"
    assert target_chips[0].this_is_source is False
    assert target_chips[0].writable is False


def test_symmetric_related_labels_both_directions_the_same() -> None:
    index = _build_link_index(
        _snapshot(
            (
                {
                    "source_ref": "bead:sase-1",
                    "relation": "related",
                    "target_ref": "bead:sase-2",
                    "uses": 1,
                },
            )
        )
    )
    assert index.chips_for("bead:sase-1")[0].label == "related"
    assert index.chips_for("bead:sase-2")[0].label == "related"
    assert index.chips_for("bead:sase-1")[0].directed is False


@pytest.mark.parametrize(
    ("ref", "pane_id", "expected_parts"),
    [
        (
            "stitch:sase@0123456789abcdef0123456789abcdef01234567",
            "stitches",
            ("sase", "0123456789abcdef0123456789abcdef01234567"),
        ),
        ("patch:42", "patches", ("", "42")),
        ("bead:sase-1", "beads", ("", "task", "sase-1")),
        ("file:doc", "files", ("doc",)),
        ("agent:alice.athena.foo", "agents", ("alice.athena.foo",)),
        ("plan:202608/x.md", "ref:plan", ("", "archive", "202608/x.md")),
    ],
)
def test_every_ref_kind_resolves_a_neighbor_target_in_both_positions(
    ref: str, pane_id: str, expected_parts: tuple[str, ...]
) -> None:
    forward = _build_link_index(
        _snapshot(
            (
                {
                    "source_ref": ref,
                    "relation": "related",
                    "target_ref": "bead:anchor",
                    "uses": 1,
                },
            )
        )
    )
    backward = _build_link_index(
        _snapshot(
            (
                {
                    "source_ref": "bead:anchor",
                    "relation": "related",
                    "target_ref": ref,
                    "uses": 1,
                },
            )
        )
    )
    for index in (forward, backward):
        anchor_chip = index.chips_for("bead:anchor")[0]
        assert anchor_chip.neighbor_ref == ref
        assert anchor_chip.neighbor_target == ArtifactEntryTarget(
            pane_id, expected_parts
        )
        other_chip = index.chips_for(ref)[0]
        assert other_chip.neighbor_ref == "bead:anchor"


def test_fixed_pane_kinds_paint_their_pane_accent_and_icon() -> None:
    reset_artifacts_subtabs_cache()
    index = _build_link_index(
        _snapshot(
            (
                {
                    "source_ref": "bead:anchor",
                    "relation": "related",
                    "target_ref": "bead:sase-1",
                    "uses": 1,
                },
            )
        )
    )
    chip = index.chips_for("bead:anchor")[0]
    assert chip.accent == ARTIFACTS_ACCENTS["beads"]
    assert chip.icon == ARTIFACTS_ICONS["beads"]


def test_accent_lookup_count_does_not_scale_with_row_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guards the fix for the mount-time startup regression (105s -> <1s).

    ``_build_link_index`` used to resolve an accent/icon pair per chip via a
    call chain that bottoms out in ``provider_source_token()``. That chain is
    cheap per call, but at thousands of chips it dominated startup. The fix
    memoizes the lookup per distinct ``(neighbor_kind, pane_id)`` pair for the
    duration of one build, so the call count must stay flat as row count
    grows instead of scaling with it.
    """
    from sase.ace.tui import artifact_tabs

    reset_artifacts_subtabs_cache()
    calls = 0
    original = artifact_tabs.provider_source_token

    def counting() -> tuple[object, ...] | None:
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(artifact_tabs, "provider_source_token", counting)

    rows = tuple(
        {
            "source_ref": "bead:anchor",
            "relation": "related",
            "target_ref": f"bead:sase-{i}",
            "uses": 1,
        }
        for i in range(300)
    )
    index = _build_link_index(_snapshot(rows))

    assert len(index.chips_for("bead:anchor")) == 300
    assert calls <= 3


def test_chop_neighbor_has_no_target_but_gets_the_virtual_chop_style() -> None:
    index = _build_link_index(
        _snapshot(
            (
                {
                    "source_ref": "chop:refresh_docs/refresh_docs",
                    "relation": "launched",
                    "target_ref": "agent:worker",
                    "uses": 1,
                },
            )
        )
    )
    chop_chip = index.chips_for("agent:worker")[0]
    assert chop_chip.neighbor_ref == "job:refresh_docs/refresh_docs"
    assert chop_chip.neighbor_target is None
    assert chop_chip.accent == _CHOP_ACCENT
    assert chop_chip.icon == _CHOP_ICON
    assert chop_chip.label == "launched-by"

    canonical = index.chips_for("chop:refresh_docs/refresh_docs")
    assert canonical
    assert index.chips_for("job:refresh_docs/refresh_docs") == canonical


def test_duplicate_rows_across_projects_converge_to_max_uses() -> None:
    index = _build_link_index(
        _snapshot(
            (
                {
                    "source_ref": "agent:worker",
                    "relation": "cites",
                    "target_ref": "plan:202608/x.md",
                    "uses": 2,
                    "_project": "alpha",
                },
                {
                    "source_ref": "agent:worker",
                    "relation": "cites",
                    "target_ref": "plan:202608/x.md",
                    "uses": 5,
                    "_project": "beta",
                },
            )
        )
    )
    chips = index.chips_for("agent:worker")
    assert len(chips) == 1
    assert chips[0].uses == 5


def test_ordering_puts_semantic_relations_before_observational() -> None:
    index = _build_link_index(
        _snapshot(
            (
                {
                    "source_ref": "bead:anchor",
                    "relation": "cites",
                    "target_ref": "plan:202608/z.md",
                    "uses": 1,
                },
                {
                    "source_ref": "bead:anchor",
                    "relation": "implements",
                    "target_ref": "plan:202608/a.md",
                    "uses": 1,
                },
            )
        )
    )
    chips = index.chips_for("bead:anchor")
    assert [chip.relation for chip in chips] == ["implements", "cites"]


def test_projected_row_is_not_writable() -> None:
    index = _build_link_index(
        _snapshot(
            (
                {
                    "source_ref": "chop:refresh_docs/refresh_docs",
                    "relation": "launched",
                    "target_ref": "agent:worker",
                    "origin": "projected",
                    "uses": 1,
                },
                {
                    "source_ref": "bead:anchor",
                    "relation": "related",
                    "target_ref": "bead:sase-1",
                    "origin": "manual",
                    "uses": 1,
                },
            )
        )
    )
    assert index.chips_for("agent:worker")[0].writable is False
    assert index.chips_for("bead:anchor")[0].writable is True


def test_agent_alias_spellings_resolve_to_the_same_chips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = AgentIdentitySnapshot(AgentOwnerIdentity("alice", "athena"), ("athena",))
    monkeypatch.setattr(
        AgentIdentitySnapshot, "current", classmethod(lambda _cls: identity)
    )
    index = _build_link_index(
        _snapshot(
            (
                {
                    "source_ref": "agent:foo",
                    "relation": "cites",
                    "target_ref": "plan:202608/a.md",
                    "uses": 1,
                },
            )
        )
    )
    canonical = index.chips_for("agent:foo")
    assert canonical
    assert index.chips_for("agent:athena.foo") == canonical
    assert index.chips_for("agent:alice.athena.foo") == canonical


def test_stitch_short_sha_alias_resolves_to_the_same_chips() -> None:
    full = "stitch:sase@0123456789abcdef0123456789abcdef01234567"
    index = _build_link_index(
        _snapshot(
            (
                {
                    "source_ref": full,
                    "relation": "related",
                    "target_ref": "bead:anchor",
                    "uses": 1,
                },
            )
        )
    )
    canonical = index.chips_for(full)
    assert canonical
    assert index.chips_for("stitch:sase@0123456") == canonical


def test_plan_ref_plan_alias_resolves_to_the_same_chips() -> None:
    index = _build_link_index(
        _snapshot(
            (
                {
                    "source_ref": "plan:202608/a.md",
                    "relation": "related",
                    "target_ref": "bead:anchor",
                    "uses": 1,
                },
            )
        )
    )
    canonical = index.chips_for("plan:202608/a.md")
    assert canonical
    assert index.chips_for("ref:plan:202608/a.md") == canonical


def test_a_canonical_ref_is_never_shadowed_by_another_edges_alias() -> None:
    # ``ref:plan:x`` is a synthetic pass-2 alias for the plan edge below; a
    # *real* store-backed edge keyed directly on that literal string must win.
    index = _build_link_index(
        _snapshot(
            (
                {
                    "source_ref": "plan:202608/x.md",
                    "relation": "related",
                    "target_ref": "bead:anchor",
                    "uses": 1,
                },
                {
                    "source_ref": "ref:plan:202608/x.md",
                    "relation": "cites",
                    "target_ref": "bead:other",
                    "uses": 1,
                },
            )
        )
    )
    assert index.chips_for("ref:plan:202608/x.md")[0].relation == "cites"


def test_lazy_mappings_support_membership_without_enumeration() -> None:
    index = _build_link_index(
        _snapshot(
            (
                {
                    "source_ref": "bead:sase-1",
                    "relation": "related",
                    "target_ref": "bead:sase-2",
                    "uses": 1,
                },
                {
                    "source_ref": "agent:ghost",
                    "relation": "cites",
                    "target_ref": "bug:1",
                    "uses": 1,
                },
            )
        )
    )
    assert "bead:sase-1" in index.by_ref
    assert "bead:sase-9" not in index.by_ref
    assert "bug:1" in index.targets_by_ref
    assert index.target_for("bug:1") is None
    assert "bead:sase-9" not in index.targets_by_ref
    assert index.target_for("bead:sase-9") is None


def test_lazy_mappings_refuse_graph_enumeration() -> None:
    index = _build_link_index(
        _snapshot(
            (
                {
                    "source_ref": "bead:sase-1",
                    "relation": "related",
                    "target_ref": "bead:sase-2",
                    "uses": 1,
                },
            )
        )
    )
    with pytest.raises(TypeError):
        list(index.by_ref)
    with pytest.raises(TypeError):
        len(index.by_ref)
    with pytest.raises(TypeError):
        list(index.targets_by_ref)
    with pytest.raises(TypeError):
        len(index.targets_by_ref)


def test_concurrent_requests_for_one_snapshot_compile_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import sase.ace.tui.relations._native_link_index as native_link_index
    from sase.ace.tui.relations.link_index import link_index_for_snapshot

    snapshot = _snapshot(
        (
            {
                "source_ref": "bead:sase-1",
                "relation": "related",
                "target_ref": "bead:sase-2",
                "uses": 1,
            },
        )
    )
    entered = 0
    entered_lock = threading.Lock()
    real_build = native_link_index.build_index
    builds = 0

    def gated_build(*args: object, **kwargs: object) -> object:
        nonlocal builds
        with entered_lock:
            builds += 1
        while True:
            with entered_lock:
                if entered >= 4:
                    break
            threading.Event().wait(0.001)
        return real_build(*args, **kwargs)

    def worker() -> object:
        nonlocal entered
        with entered_lock:
            entered += 1
        return link_index_for_snapshot(snapshot)

    monkeypatch.setattr(native_link_index, "build_index", gated_build)
    with ThreadPoolExecutor(max_workers=4) as pool:
        indexes = list(pool.map(lambda _: worker(), range(4)))
    assert builds == 1
    handles = {id(index.by_ref._handle) for index in indexes}  # type: ignore[union-attr]
    assert handles == {id(indexes[0].by_ref._handle)}  # type: ignore[union-attr]
    for index in indexes:
        assert index.chips_for("bead:sase-1")


def test_failed_build_unblocks_waiters_and_retry_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import sase.ace.tui.relations._native_link_index as native_link_index
    from sase.ace.tui.relations.link_index import link_index_for_snapshot

    snapshot = _snapshot(
        (
            {
                "source_ref": "bead:sase-1",
                "relation": "related",
                "target_ref": "bead:sase-2",
                "uses": 1,
            },
        )
    )
    release = threading.Event()
    build_lock = threading.Lock()
    real_build = native_link_index.build_index
    builds = 0
    fail_open = True

    def flaky_build(*args: object, **kwargs: object) -> object:
        nonlocal builds
        with build_lock:
            builds += 1
        assert release.wait(timeout=60)
        if fail_open:
            raise RuntimeError("boom")
        return real_build(*args, **kwargs)

    monkeypatch.setattr(native_link_index, "build_index", flaky_build)
    # The main thread joins as a guaranteed waiter: the owner is already
    # inside its build (or fails first and the main thread's own build
    # fails the same way), so every interleaving raises instead of hanging.
    with ThreadPoolExecutor(max_workers=1) as pool:
        owner = pool.submit(link_index_for_snapshot, snapshot)
        while True:
            with build_lock:
                if builds >= 1:
                    break
            threading.Event().wait(0.001)
        timer = threading.Timer(2.0, release.set)
        timer.start()
        try:
            with pytest.raises(RuntimeError, match="boom"):
                link_index_for_snapshot(snapshot)
            with pytest.raises(RuntimeError, match="boom"):
                owner.result(timeout=60)
        finally:
            timer.join(timeout=60)
    assert builds >= 1
    fail_open = False
    release.set()
    before = builds
    index = link_index_for_snapshot(snapshot)
    assert builds == before + 1
    assert index.chips_for("bead:sase-1")


def test_distinct_synthetic_snapshots_with_shared_keys_stay_separate() -> None:
    first = _build_link_index(
        _snapshot(
            (
                {
                    "source_ref": "bead:sase-1",
                    "relation": "related",
                    "target_ref": "bead:sase-2",
                    "uses": 1,
                },
            )
        )
    )
    second = _build_link_index(
        _snapshot(
            (
                {
                    "source_ref": "bead:sase-9",
                    "relation": "related",
                    "target_ref": "bead:sase-8",
                    "uses": 1,
                },
            )
        )
    )
    assert first.chips_for("bead:sase-1")
    assert first.chips_for("bead:sase-9") == ()
    assert second.chips_for("bead:sase-9")
    assert second.chips_for("bead:sase-1") == ()

    from sase.ace.tui.relations.link_index import link_index_for_snapshot

    shared_a = _snapshot(
        (
            {
                "source_ref": "bead:sase-1",
                "relation": "related",
                "target_ref": "bead:sase-2",
                "uses": 1,
            },
        )
    )
    shared_b = _snapshot(
        (
            {
                "source_ref": "bead:sase-9",
                "relation": "related",
                "target_ref": "bead:sase-8",
                "uses": 1,
            },
        )
    )
    cached_a = link_index_for_snapshot(shared_a)
    assert cached_a.chips_for("bead:sase-1")
    assert cached_a.chips_for("bead:sase-9") == ()
    cached_b = link_index_for_snapshot(shared_b)
    assert cached_b.chips_for("bead:sase-9")
    assert cached_b.chips_for("bead:sase-1") == ()
