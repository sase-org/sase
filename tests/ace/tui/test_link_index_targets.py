"""Neighbor targets, pane style, aliases, and lazy mappings for the link-graph index."""

from __future__ import annotations

import pytest

from sase.ace.tui._artifact_tab_model import ARTIFACTS_ACCENTS, ARTIFACTS_ICONS
from sase.ace.tui.artifact_tabs import reset_artifacts_subtabs_cache
from sase.ace.tui.relations.link_index import _build_link_index
from sase.ace.tui.relations.link_subject import _CHOP_ACCENT, _CHOP_ICON
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.core.artifact_entry_target import ArtifactEntryTarget
from tests.ace.tui._link_index_helpers import snapshot

__all__ = [
    "test_a_canonical_ref_is_never_shadowed_by_another_edges_alias",
    "test_accent_lookup_count_does_not_scale_with_row_count",
    "test_agent_alias_spellings_resolve_to_the_same_chips",
    "test_chop_neighbor_has_no_target_but_gets_the_virtual_chop_style",
    "test_every_ref_kind_resolves_a_neighbor_target_in_both_positions",
    "test_fixed_pane_kinds_paint_their_pane_accent_and_icon",
    "test_lazy_chip_style_uses_worker_captured_provider_context",
    "test_lazy_mappings_refuse_graph_enumeration",
    "test_lazy_mappings_support_membership_without_enumeration",
    "test_plan_ref_plan_alias_resolves_to_the_same_chips",
    "test_stitch_short_sha_alias_resolves_to_the_same_chips",
]


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
        snapshot(
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
        snapshot(
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
        snapshot(
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
    index = _build_link_index(snapshot(rows))

    assert len(index.chips_for("bead:anchor")) == 300
    assert calls <= 3


def test_lazy_chip_style_uses_worker_captured_provider_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from sase.ace.tui import artifact_tabs

    descriptor = SimpleNamespace(accent="#123456", icon="D")
    monkeypatch.setattr(
        artifact_tabs,
        "resolve_artifacts_subtabs",
        lambda: (SimpleNamespace(id="ref:custom", **vars(descriptor)),),
    )
    index = _build_link_index(
        snapshot(
            (
                {
                    "source_ref": "bead:anchor",
                    "relation": "related",
                    "target_ref": "custom:document",
                    "uses": 1,
                },
            )
        )
    )

    def forbidden(_pane_id: str) -> object:
        raise AssertionError("lazy chip lookup performed descriptor resolution")

    monkeypatch.setattr(artifact_tabs, "descriptor_for_artifacts_pane_id", forbidden)
    chip = index.chips_for("bead:anchor")[0]
    assert chip.accent == "#123456"
    assert chip.icon == "D"


def test_chop_neighbor_has_no_target_but_gets_the_virtual_chop_style() -> None:
    index = _build_link_index(
        snapshot(
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


def test_agent_alias_spellings_resolve_to_the_same_chips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = AgentIdentitySnapshot(AgentOwnerIdentity("alice", "athena"), ("athena",))
    monkeypatch.setattr(
        AgentIdentitySnapshot, "current", classmethod(lambda _cls: identity)
    )
    index = _build_link_index(
        snapshot(
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
        snapshot(
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
        snapshot(
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
        snapshot(
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
        snapshot(
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
        snapshot(
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
