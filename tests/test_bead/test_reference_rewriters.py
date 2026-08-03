"""Focused coverage for host-owned bead prefix reference planners."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from sase.bead.reference_rewriters import (
    ReferenceRewriteAction,
    apply_changespec_reference_rewrite,
    plan_changespec_reference_rewrite,
    plan_plan_reference_rewrite,
)

OLD_ROOT = "gh_bobs-org__bob-cli-1"
OLD_CHILD = f"{OLD_ROOT}.2"
NEW_ROOT = "bob-cli-1"
NEW_CHILD = f"{NEW_ROOT}.2"
ID_MAP = {OLD_ROOT: NEW_ROOT, OLD_CHILD: NEW_CHILD}


def test_plan_rewriter_uses_frontmatter_and_generated_header_codecs() -> None:
    original = (
        "---\n"
        "tier: epic\n"
        "title: Rewrite references\n"
        "goal: Keep exact identities safe.\n"
        f"bead_id: {OLD_ROOT}\n"
        f"bead: {OLD_ROOT}\n"
        f"parent_bead: {OLD_CHILD}\n"
        "phases: []\n"
        "---\n\n"
        f"- **BEAD:** [{OLD_ROOT}]"
        f"(https://github.com/bobs/bob--beads/blob/main/pages/{OLD_ROOT}/README.md)\n\n"
        f"# Plan\n\nFree-form audit evidence keeps {OLD_ROOT}.\n"
    ).encode()

    planned = plan_plan_reference_rewrite("plan.md", original, ID_MAP)
    rendered = planned.rewritten_bytes.decode()

    assert planned.action is ReferenceRewriteAction.REWRITE
    assert planned.preimage_digest == sha256(original).hexdigest()
    assert f"bead_id: {NEW_ROOT}\n" in rendered
    assert f"bead: {NEW_ROOT}\n" in rendered
    assert f"parent_bead: {NEW_CHILD}\n" in rendered
    assert f"- **BEAD:** [{NEW_ROOT}]" in rendered
    assert f"pages/{NEW_ROOT}/README.md" in rendered
    assert f"Free-form audit evidence keeps {OLD_ROOT}." in rendered


@pytest.mark.parametrize("field", ["bead_id", "bead", "parent_bead"])
def test_plan_rewriter_handles_each_canonical_and_legacy_field(field: str) -> None:
    original = f"---\n{field}: {OLD_CHILD}\n---\n# Plan\n".encode()

    planned = plan_plan_reference_rewrite("plan.md", original, ID_MAP)

    assert planned.action is ReferenceRewriteAction.REWRITE
    assert f"{field}: {NEW_CHILD}\n" in planned.rewritten_bytes.decode()


def test_plan_rewriter_blocks_malformed_or_ambiguous_owned_input() -> None:
    malformed = f"---\nbead_id: {OLD_ROOT}\n# missing close\n".encode()
    ambiguous = f"---\nbead_id: prefix/{OLD_ROOT}\n---\n# Plan\n".encode()
    wrong_type = f"---\nbead_id: [{OLD_ROOT}]\n---\n# Plan\n".encode()
    orphan_header = f"- **BEAD:** {OLD_ROOT}\n\n# Plan\n".encode()

    assert (
        plan_plan_reference_rewrite("bad.md", malformed, ID_MAP).action
        is ReferenceRewriteAction.BLOCKER
    )
    assert (
        plan_plan_reference_rewrite("ambiguous.md", ambiguous, ID_MAP).action
        is ReferenceRewriteAction.BLOCKER
    )
    assert (
        plan_plan_reference_rewrite("wrong-type.md", wrong_type, ID_MAP).action
        is ReferenceRewriteAction.BLOCKER
    )
    assert (
        plan_plan_reference_rewrite("orphan.md", orphan_header, ID_MAP).action
        is ReferenceRewriteAction.BLOCKER
    )


def test_plan_rewriter_is_exact_noop_for_unowned_or_near_match_text() -> None:
    original = (
        f"---\ntitle: {OLD_ROOT}-suffix\n---\n"
        f"# Quoted historical evidence\n\n{OLD_ROOT}\n"
    ).encode()

    planned = plan_plan_reference_rewrite("audit.md", original, ID_MAP)

    assert planned.action is ReferenceRewriteAction.SKIP
    assert planned.rewritten_bytes == original


@pytest.mark.parametrize("filename", ["bob-cli.sase", "bob-cli-archive.sase"])
def test_changespec_rewriter_limits_changes_to_bug_and_refs(filename: str) -> None:
    original = (
        "PROJECT_NAME: bob-cli\n\n"
        f"NAME: {OLD_ROOT}-feature\n"
        "DESCRIPTION:\n"
        f"  Historical evidence mentions {OLD_ROOT}.\n"
        f"BUG: https://host/pages/{OLD_ROOT}/README.md\n"
        "STATUS: WIP\n"
        "REFS:\n"
        f"  bead:{OLD_CHILD}\n"
        "COMMITS:\n"
        f"  (1) Immutable footer {OLD_ROOT}\n"
        "TIMESTAMPS:\n"
        f"  [2026-01-01 00:00:00] REWORD {OLD_ROOT}\n"
    ).encode()

    planned = plan_changespec_reference_rewrite(filename, original, ID_MAP)
    rendered = planned.rewritten_bytes.decode()

    assert planned.action is ReferenceRewriteAction.REWRITE
    assert f"NAME: {OLD_ROOT}-feature" in rendered
    assert f"mentions {OLD_ROOT}" in rendered
    assert f"BUG: https://host/pages/{NEW_ROOT}/README.md" in rendered
    assert f"  bead:{NEW_CHILD}" in rendered
    assert f"Immutable footer {OLD_ROOT}" in rendered
    assert f"REWORD {OLD_ROOT}" in rendered


def test_changespec_rewriter_blocks_malformed_owned_fields() -> None:
    malformed_bug = f"NAME: x\nBUG:{OLD_ROOT}\nSTATUS: WIP\n".encode()
    malformed_ref = f"NAME: x\nSTATUS: WIP\nREFS: bead:{OLD_ROOT}\n".encode()

    assert (
        plan_changespec_reference_rewrite("x.sase", malformed_bug, ID_MAP).action
        is ReferenceRewriteAction.BLOCKER
    )
    assert (
        plan_changespec_reference_rewrite("x.sase", malformed_ref, ID_MAP).action
        is ReferenceRewriteAction.BLOCKER
    )


def test_changespec_apply_revalidates_digest_and_uses_atomic_writer(
    tmp_path: Path,
) -> None:
    project_file = tmp_path / "bob-cli.sase"
    original = f"NAME: x\nBUG: bead:{OLD_ROOT}\nSTATUS: WIP\n".encode()
    project_file.write_bytes(original)
    planned = plan_changespec_reference_rewrite(project_file, original, ID_MAP)

    assert apply_changespec_reference_rewrite(planned)
    assert f"BUG: bead:{NEW_ROOT}" in project_file.read_text()

    project_file.write_bytes(original + b"# raced\n")
    with pytest.raises(RuntimeError, match="preimage changed"):
        apply_changespec_reference_rewrite(planned)


def test_changespec_unowned_match_is_byte_exact_skip() -> None:
    original = (f"NAME: {OLD_ROOT}\nDESCRIPTION:\n  {OLD_ROOT}\nSTATUS: WIP\n").encode()

    planned = plan_changespec_reference_rewrite("x.sase", original, ID_MAP)

    assert planned.action is ReferenceRewriteAction.SKIP
    assert planned.rewritten_bytes == original
