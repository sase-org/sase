"""Agent-metadata association tests for ``sase plan propose``."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.conftest import redirect_sase_home
from tests.plan_command_handler_helpers import (
    VALID_EPIC,
    VALID_TALE,
    assert_archived_associations as _assert_archived_associations,
    clear_bead_work_association_env,
    invoke_plan as _invoke_plan,
    make_artifacts_dir as _make_artifacts_dir,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from sase.sdd.frontmatter import parse_frontmatter
from sase.sdd.store import SddStore


@pytest.fixture(autouse=True)
def _clear_bead_work_association_env(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_bead_work_association_env(monkeypatch)


@pytest.mark.parametrize(
    ("content", "metadata", "expected_fields"),
    [
        pytest.param(
            VALID_TALE,
            {
                "phase_bead_id": "sase-meta.1",
                "epic_bead_id": "sase-meta",
                "epic_plan_ref": "sase/repos/plans/202607/parent.md",
            },
            {
                "bead": "sase-meta.1",
                "parent": "sase/repos/plans/202607/parent.md",
            },
            id="tale-phase-agent",
        ),
        pytest.param(
            VALID_TALE,
            {
                "epic_bead_id": "sase-meta",
                "epic_plan_ref": "sase/repos/plans/202607/parent.md",
            },
            {
                "bead": "sase-meta",
                "parent": "sase/repos/plans/202607/parent.md",
            },
            id="tale-land-agent",
        ),
        pytest.param(
            VALID_EPIC,
            {
                "phase_bead_id": "sase-meta.1",
                "epic_bead_id": "sase-meta",
                "epic_plan_ref": "sase/repos/plans/202607/parent.md",
            },
            {
                "parent_bead": "sase-meta.1",
                "parent": "sase/repos/plans/202607/parent.md",
            },
            id="child-epic",
        ),
        pytest.param(
            VALID_TALE,
            {"phase_bead_id": "sase-meta.1"},
            {"bead": "sase-meta.1"},
            id="missing-plan-ref",
        ),
        pytest.param(
            VALID_TALE,
            {"bead_id": "sase-iq"},
            {"bead": "sase-iq"},
            id="task-agent-bead",
        ),
    ],
)
def test_plan_command_stamps_associations_from_agent_metadata(
    content: str,
    metadata: dict[str, str],
    expected_fields: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production proposals inherit associations from ``agent_meta.json``."""
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    artifacts_dir = _make_artifacts_dir(sase_home)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    plan_file = tmp_path / "associated.md"
    plan_file.write_text(content, encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    with (
        patch(
            "sase.main.plan_propose_handler.kill_agent_runner_group",
            side_effect=SystemExit(0),
        ),
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda raw: raw,
        ),
    ):
        assert _invoke_plan(plan_file) == 0

    _assert_archived_associations(artifacts_dir, content, expected_fields)


def test_plan_command_association_env_overrides_agent_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-empty env associations override the same metadata fields."""
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    artifacts_dir = _make_artifacts_dir(sase_home)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "phase_bead_id": "sase-meta.1",
                "epic_bead_id": "sase-meta",
                "epic_plan_ref": "sase/repos/plans/202607/meta-parent.md",
            }
        ),
        encoding="utf-8",
    )
    plan_file = tmp_path / "associated.md"
    plan_file.write_text(VALID_TALE, encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setenv("SASE_PHASE_BEAD_ID", "sase-env.1")
    monkeypatch.setenv("SASE_EPIC_BEAD_ID", "sase-env")
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", "sase/repos/plans/202607/env-parent.md")

    with (
        patch(
            "sase.main.plan_propose_handler.kill_agent_runner_group",
            side_effect=SystemExit(0),
        ),
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda raw: raw,
        ),
    ):
        assert _invoke_plan(plan_file) == 0

    _assert_archived_associations(
        artifacts_dir,
        VALID_TALE,
        {
            "bead": "sase-env.1",
            "parent": "sase/repos/plans/202607/env-parent.md",
        },
    )


@pytest.mark.parametrize("agent_meta_contents", [None, "{not-json"])
def test_plan_command_ignores_missing_or_malformed_agent_metadata(
    agent_meta_contents: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unreadable agent metadata leaves otherwise valid proposals unstamped."""
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    artifacts_dir = _make_artifacts_dir(sase_home)
    if agent_meta_contents is not None:
        (artifacts_dir / "agent_meta.json").write_text(
            agent_meta_contents, encoding="utf-8"
        )
    plan_file = tmp_path / "unassociated.md"
    plan_file.write_text(VALID_TALE, encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    with (
        patch(
            "sase.main.plan_propose_handler.kill_agent_runner_group",
            side_effect=SystemExit(0),
        ),
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda raw: raw,
        ),
    ):
        assert _invoke_plan(plan_file) == 0

    _assert_archived_associations(artifacts_dir, VALID_TALE, {})


def test_plan_command_stamps_after_runner_consumes_bead_work_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The production env-to-marker transition preserves proposal stamps."""
    from sase.axe.run_agent_directive_metadata import epic_work_metadata_from_env

    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    artifacts_dir = _make_artifacts_dir(sase_home)
    plan_file = tmp_path / "associated.md"
    plan_file.write_text(VALID_TALE, encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setenv("SASE_PHASE_BEAD_ID", "sase-prod.1")
    monkeypatch.setenv("SASE_EPIC_BEAD_ID", "sase-prod")
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", "sase/repos/plans/202607/prod-parent.md")

    metadata = epic_work_metadata_from_env()
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    assert "SASE_PHASE_BEAD_ID" not in os.environ
    assert "SASE_EPIC_BEAD_ID" not in os.environ
    assert "SASE_EPIC_PLAN_REF" not in os.environ

    with (
        patch(
            "sase.main.plan_propose_handler.kill_agent_runner_group",
            side_effect=SystemExit(0),
        ),
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda raw: raw,
        ),
    ):
        assert _invoke_plan(plan_file) == 0

    _assert_archived_associations(
        artifacts_dir,
        VALID_TALE,
        {
            "bead": "sase-prod.1",
            "parent": "sase/repos/plans/202607/prod-parent.md",
        },
    )


def test_plan_command_consumes_links_frontmatter_into_artifact_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proposal archives consume transient ``links:`` into durable rows."""
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    artifacts_dir = _make_artifacts_dir(sase_home)
    sidecar_root = tmp_path / "plans-sidecar"
    sidecar_root.mkdir()
    sdd_store = SddStore("sidecar_repos", sidecar_root, sidecar_root)
    link_store = ArtifactLinkStore.from_sdd_store(sdd_store, "demo")
    plan_file = tmp_path / "linked.md"
    plan_file.write_text(
        VALID_TALE.replace(
            "size: small\n",
            "size: small\n"
            "links:\n"
            "  - ref: research:202608/source.md\n"
            "    relation: derives-from\n"
            "    description: uses source report\n",
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setenv("USER", "tester")
    monkeypatch.setattr(
        "sase.sdd.artifact_link_inlet.resolve_artifact_link_store",
        lambda: link_store,
    )
    persisted: list[dict[str, object]] = []
    monkeypatch.setattr(
        "sase.sdd._artifact_link_commit.persist_artifact_link_graph_mutation",
        lambda _store, **kwargs: persisted.append(kwargs),
    )

    with (
        patch(
            "sase.main.plan_propose_handler.kill_agent_runner_group",
            side_effect=SystemExit(0),
        ),
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda raw: raw,
        ),
    ):
        assert _invoke_plan(plan_file) == 0

    marker = json.loads(
        (artifacts_dir / ".sase_plan_pending").read_text(encoding="utf-8")
    )
    archived = Path(marker["plan_file"])
    archived_content = archived.read_text(encoding="utf-8")
    frontmatter, _body, _had_frontmatter = parse_frontmatter(archived_content)
    archive_relpath = archived.relative_to(sase_home / "plans").as_posix()
    source_ref = f"plan:{archive_relpath}"

    assert "links" not in frontmatter
    assert "<!-- sase:links:start -->" in archived_content
    assert (
        "| derives-from | research:202608/source.md | uses source report |"
        in archived_content
    )
    index = json.loads(
        (sidecar_root / "links" / f"{archive_relpath}.json").read_text(encoding="utf-8")
    )
    row = index["rows"][0]
    assert index["artifact_ref"] == source_ref
    assert row["source_ref"] == source_ref
    assert row["relation"] == "derives-from"
    assert row["target_ref"] == "research:202608/source.md"
    assert row["origin"] == "manual"
    assert row["created_by"] == "tester"
    assert persisted


def test_plan_command_rejects_unknown_links_relation_without_consuming(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Invalid inlet entries fail before the scratch plan is mutated."""
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    artifacts_dir = _make_artifacts_dir(sase_home)
    content = VALID_TALE.replace(
        "size: small\n",
        "size: small\n"
        "links:\n"
        "  - ref: research:202608/source.md\n"
        "    relation: invented\n"
        "    description: uses source report\n",
    )
    plan_file = tmp_path / "unknown-link.md"
    plan_file.write_text(content, encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    with patch("sase.main.plan_propose_handler.kill_agent_runner_group") as kill:
        assert _invoke_plan(plan_file) == 1

    assert plan_file.read_text(encoding="utf-8") == content
    assert not (artifacts_dir / ".sase_plan_pending").exists()
    assert not kill.called
    error = capsys.readouterr().err
    assert "links[0].relation" in error
    assert "unknown relation `invented`" in error
