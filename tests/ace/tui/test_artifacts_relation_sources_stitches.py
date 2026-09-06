"""Focused coverage for the stitches Artifacts relation source."""

from __future__ import annotations

from sase.ace.tui._artifact_tab_contract import compile_builtin_contract
from sase.ace.tui.relations import build_stitches_relation_index
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.vcs_log_wire import AggregatedCommitWire, VcsCommitWire


def test_stitches_source_emits_parents_and_patch_tag() -> None:
    child = AggregatedCommitWire(
        "sase",
        VcsCommitWire(
            full_id="ccc",
            short_id="ccc",
            author_name="Ada",
            author_email="ada@example.com",
            timestamp=1,
            parent_ids=("ppp",),
            subject="feat",
            body="body\n\nSASE_PATCH=feat-x",
        ),
    )
    parent = AggregatedCommitWire(
        "sase",
        VcsCommitWire(
            full_id="ppp",
            short_id="ppp",
            author_name="Ada",
            author_email="ada@example.com",
            timestamp=0,
            subject="base",
            body="",
        ),
    )
    contract = compile_builtin_contract("stitches", label="S", icon="x", accent="#0")
    index = build_stitches_relation_index(
        (child, parent),
        contract=contract,
        project_keys_by_repo={"sase": "sase_key"},
    )
    child_t = ArtifactEntryTarget("stitches", ("sase", "ccc"))
    parent_t = ArtifactEntryTarget("stitches", ("sase", "ppp"))
    assert index.edges_for_relation(child_t, "parents")[0].target == parent_t
    assert index.edges_for_relation(parent_t, "children")[0].target == child_t
    patch = index.edges_for_relation(child_t, "patches")[0]
    assert patch.target == ArtifactEntryTarget("patches", ("sase_key", "feat-x"))
    assert patch.dangling is False
