"""Ref-uses manifest coverage: one immutable row per ref occurrence."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.artifact_ref_uses import (
    ARTIFACT_REF_USE_MANIFEST_NAME,
    record_artifact_ref_use,
    read_artifact_ref_uses,
)


def test_record_and_read_round_trip(tmp_path: Path) -> None:
    record = record_artifact_ref_use(
        agent_name="bbugyi200.athena.sase-js.4",
        raw_ref="@stitch:abc1234",
        canonical_ref="stitch:sase@" + "a" * 40,
        ref_kind="stitch",
        prompt_text="stitch " + "a" * 40 + " in sase (checkout: /tmp/x)",
        stable_id="stitch:sase@" + "a" * 40,
        agent_artifacts_dir=tmp_path,
    )

    assert record is not None
    manifest = tmp_path / ARTIFACT_REF_USE_MANIFEST_NAME
    rows = read_artifact_ref_uses(manifest)
    assert rows == [record]


def test_one_row_per_occurrence_not_deduped(tmp_path: Path) -> None:
    for _ in range(3):
        record_artifact_ref_use(
            agent_name="a.b.c",
            raw_ref="@bead:sase-9z",
            canonical_ref="bead:sase-9z",
            ref_kind="bead",
            prompt_text="@/pages/sase-9z/README.md",
            stable_id="bead:sase-9z",
            agent_artifacts_dir=tmp_path,
        )

    rows = read_artifact_ref_uses(tmp_path / ARTIFACT_REF_USE_MANIFEST_NAME)
    assert len(rows) == 3
    assert all(row.raw_ref == "@bead:sase-9z" for row in rows)


def test_no_agent_artifacts_dir_skips_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    record = record_artifact_ref_use(
        agent_name="a.b.c",
        raw_ref="@bead:sase-9z",
        canonical_ref="bead:sase-9z",
        ref_kind="bead",
        prompt_text="@/pages/sase-9z/README.md",
    )

    assert record is None


def test_write_failure_does_not_raise(tmp_path: Path) -> None:
    unwritable = tmp_path / "not-a-directory"
    unwritable.write_text("i am a file, not a directory")

    record = record_artifact_ref_use(
        agent_name="a.b.c",
        raw_ref="@bead:sase-9z",
        canonical_ref="bead:sase-9z",
        ref_kind="bead",
        prompt_text="@/pages/sase-9z/README.md",
        agent_artifacts_dir=unwritable,
    )

    assert record is None


def test_duplicate_prompt_refs_write_multiple_rows_while_consumption_dedupes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The same ref cited 3x writes 3 ref-uses rows but one consumption event."""

    import sase.agent.identity as agent_identity
    from sase.artifact_ref_models import ArtifactRefContext, ArtifactRefDocumentRoot
    from sase.artifact_refs import process_artifact_references

    monkeypatch.setattr(agent_identity, "resolve_local_agent_name", lambda: "a.b.c")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    consumption_events: list[object] = []
    import sase.artifact_ref_prompt as artifact_ref_prompt

    monkeypatch.setattr(
        artifact_ref_prompt,
        "append_artifact_consumption_events",
        lambda events: consumption_events.extend(events),
    )

    plan = tmp_path / "plans" / "report.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Report\n")
    context = ArtifactRefContext(
        document_roots=(ArtifactRefDocumentRoot("plan", tmp_path / "plans"),),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifacts" / "index.jsonl",
        repositories=(),
        projects=(),
    )

    process_artifact_references(
        "@plan:report.md and @plan:report.md again", context=context
    )

    use_rows = read_artifact_ref_uses(tmp_path / ARTIFACT_REF_USE_MANIFEST_NAME)
    assert len(use_rows) == 2
    assert all(row.ref_kind == "plan" for row in use_rows)
    assert len(consumption_events) == 1
