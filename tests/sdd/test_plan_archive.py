"""Tests for plans entering the canonical SDD archive."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.sdd.artifact_links import (
    SddArtifactLinkType,
    parse_sdd_artifact_link,
    update_source_aware_artifact_link,
)
from sase.sdd.links import validate_sdd_tree
from sase.sdd.plan_archive import archive_plan_file
from sase.sdd.plan_header_block import (
    PlanHeaderSectionKind,
    parse_plan_header_block,
)
from sase.sdd.plan_header_writes import upsert_parent_plan_section
from sase.sdd.store import SddStore

_MONTH = "202607"
_PROMPT_URL = (
    "https://github.com/sase-org/sase--agents/blob/main/prompts/202607/child.md"
)


@pytest.fixture(autouse=True)
def _hosted_prompt_links(monkeypatch: pytest.MonkeyPatch) -> None:
    class Resolver:
        def prompt_url(self, prompt_ref: str) -> str | None:
            assert prompt_ref == "prompts/202607/child.md"
            return _PROMPT_URL

        def plan_url(self, _plan_ref: str) -> None:
            return None

        def bead_url(self, _bead_id: str) -> None:
            return None

    monkeypatch.setattr(
        "sase.sdd.hosted_links.hosted_link_resolver",
        lambda *_args, **_kwargs: Resolver(),
    )


def _sidecar_store(tmp_path: Path) -> SddStore:
    plans_root = tmp_path / "repo--plans"
    plans_root.mkdir()
    return SddStore("sidecar_repos", plans_root, plans_root)


def _write_source(tmp_path: Path, content: str, *, name: str = "child.md") -> Path:
    source = tmp_path / "artifacts" / name
    source.parent.mkdir(exist_ok=True)
    source.write_text(content, encoding="utf-8")
    return source


def test_archive_installs_reciprocal_prompt_section_when_snapshot_exists(
    tmp_path: Path,
) -> None:
    store = _sidecar_store(tmp_path)
    prompt = store.sdd_dir / _MONTH / "prompts" / "child.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("# Prompt\n", encoding="utf-8")
    source = _write_source(tmp_path, "# Plan\n")

    result = archive_plan_file(
        source,
        store,
        tier="tale",
        yyyymm=_MONTH,
        primary_root=tmp_path,
    )

    link = parse_sdd_artifact_link(result.path.read_text(encoding="utf-8"))
    assert result.written
    assert link.reference == f"prompts/{_MONTH}/child.md"
    assert link.target == _PROMPT_URL


def test_archive_leaves_unpaired_plan_unlinked_without_prompt_snapshot(
    tmp_path: Path,
) -> None:
    store = _sidecar_store(tmp_path)
    source = _write_source(tmp_path, "# Plan\n")

    result = archive_plan_file(
        source,
        store,
        tier="tale",
        yyyymm=_MONTH,
        primary_root=tmp_path,
    )

    content = result.path.read_text(encoding="utf-8")
    validation = validate_sdd_tree(str(store.sdd_dir))
    assert parse_sdd_artifact_link(content).reference is None
    assert validation.errors == []
    assert any(issue.code == "unpaired-file" for issue in validation.warnings)
    assert not any(issue.code == "link-missing-target" for issue in validation.issues)


def test_archive_default_still_skips_prompt_section_without_snapshot(
    tmp_path: Path,
) -> None:
    store = _sidecar_store(tmp_path)
    source = _write_source(tmp_path, "# Plan\n")

    result = archive_plan_file(
        source,
        store,
        tier="tale",
        yyyymm=_MONTH,
        primary_root=tmp_path,
        expect_prompt_snapshot=False,
    )

    content = result.path.read_text(encoding="utf-8")
    assert parse_sdd_artifact_link(content).reference is None


def test_archive_installs_prompt_section_when_snapshot_is_expected_but_absent(
    tmp_path: Path,
) -> None:
    store = _sidecar_store(tmp_path)
    source = _write_source(tmp_path, "# Plan\n")

    result = archive_plan_file(
        source,
        store,
        tier="epic",
        yyyymm=_MONTH,
        primary_root=tmp_path,
        expect_prompt_snapshot=True,
    )

    link = parse_sdd_artifact_link(result.path.read_text(encoding="utf-8"))
    assert link.reference == f"prompts/{_MONTH}/child.md"
    assert link.target == _PROMPT_URL


def test_archive_with_expected_snapshot_produces_valid_bidirectional_pair(
    tmp_path: Path,
) -> None:
    store = _sidecar_store(tmp_path)
    source = _write_source(tmp_path, "# Plan\n")

    result = archive_plan_file(
        source,
        store,
        tier="epic",
        yyyymm=_MONTH,
        primary_root=tmp_path,
        expect_prompt_snapshot=True,
    )

    prompt = store.sdd_dir / _MONTH / "prompts" / "child.md"
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text(
        update_source_aware_artifact_link(
            "# Prompt\n",
            store.sdd_dir,
            prompt,
            result.path,
            SddArtifactLinkType.PLAN,
            label_prefix="../",
            remove_legacy=True,
        ),
        encoding="utf-8",
    )

    link = parse_sdd_artifact_link(result.path.read_text(encoding="utf-8"))
    assert link.target == _PROMPT_URL


def test_archive_preserves_existing_prompt_section_when_snapshot_is_absent(
    tmp_path: Path,
) -> None:
    store = _sidecar_store(tmp_path)
    original = "- **PROMPT:** [202607/prompts/stale.md](prompts/stale.md)\n\n# Plan\n"
    source = _write_source(tmp_path, original)

    result = archive_plan_file(
        source,
        store,
        tier="tale",
        yyyymm=_MONTH,
        primary_root=tmp_path,
    )

    link = parse_sdd_artifact_link(result.path.read_text(encoding="utf-8"))
    assert link.reference == "202607/prompts/stale.md"
    assert link.target == "prompts/stale.md"


def test_archive_rebases_authored_parent_for_destination(tmp_path: Path) -> None:
    store = _sidecar_store(tmp_path)
    parent = store.sdd_dir / _MONTH / "parent.md"
    parent.parent.mkdir(parents=True)
    parent.write_text("---\ntier: tale\n---\n# Parent\n", encoding="utf-8")
    source = _write_source(
        tmp_path,
        upsert_parent_plan_section("# Child\n", f"plans:{_MONTH}/parent.md"),
    )

    result = archive_plan_file(
        source,
        store,
        tier="tale",
        yyyymm=_MONTH,
        primary_root=tmp_path,
    )

    parent_section = next(
        section
        for section in parse_plan_header_block(
            result.path.read_text(encoding="utf-8")
        ).sections
        if section.kind is PlanHeaderSectionKind.PARENT
    )
    assert parent_section.label == f"{_MONTH}/parent.md"
    assert parent_section.target == "parent.md"


def test_archive_projects_prompt_parent_and_bead_in_canonical_order(
    tmp_path: Path,
) -> None:
    store = _sidecar_store(tmp_path)
    prompt = store.sdd_dir / _MONTH / "prompts" / "child.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("# Prompt\n", encoding="utf-8")
    parent = store.sdd_dir / _MONTH / "parent.md"
    parent.write_text("---\ntier: tale\n---\n# Parent\n", encoding="utf-8")
    document = upsert_parent_plan_section(
        "---\nbead_id: sase-ai.8\n---\n# Child\n",
        f"plans:{_MONTH}/parent.md",
    )
    source = _write_source(tmp_path, document)

    result = archive_plan_file(
        source,
        store,
        tier="tale",
        yyyymm=_MONTH,
        primary_root=tmp_path,
    )

    sections = parse_plan_header_block(result.path.read_text(encoding="utf-8")).sections
    assert [section.kind for section in sections] == [
        PlanHeaderSectionKind.PROMPT,
        PlanHeaderSectionKind.PARENT,
        PlanHeaderSectionKind.BEAD,
    ]
    assert sections[-1].label == "sase-ai.8"


def test_archive_produces_valid_bidirectional_pair(tmp_path: Path) -> None:
    store = _sidecar_store(tmp_path)
    destination = store.sdd_dir / _MONTH / "child.md"
    prompt = store.sdd_dir / _MONTH / "prompts" / "child.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        update_source_aware_artifact_link(
            "# Prompt\n",
            store.sdd_dir,
            prompt,
            destination,
            SddArtifactLinkType.PLAN,
            label_prefix="../",
            remove_legacy=True,
        ),
        encoding="utf-8",
    )
    source = _write_source(tmp_path, "# Plan\n")

    archive_plan_file(
        source,
        store,
        tier="tale",
        yyyymm=_MONTH,
        primary_root=tmp_path,
    )

    link = parse_sdd_artifact_link(
        (store.sdd_dir / _MONTH / "child.md").read_text(encoding="utf-8")
    )
    assert link.target == _PROMPT_URL


def test_archive_preserves_both_no_op_contracts(tmp_path: Path) -> None:
    store = _sidecar_store(tmp_path)
    archived = store.sdd_dir / _MONTH / "canonical.md"
    archived.parent.mkdir(parents=True)
    archived.write_text("canonical sentinel\n", encoding="utf-8")

    canonical_result = archive_plan_file(
        archived,
        store,
        tier="tale",
        primary_root=tmp_path,
    )

    source = _write_source(tmp_path, "# Replacement\n", name="existing.md")
    existing = store.sdd_dir / _MONTH / source.name
    existing.write_text("existing sentinel\n", encoding="utf-8")
    preserved_result = archive_plan_file(
        source,
        store,
        tier="tale",
        yyyymm=_MONTH,
        preserve_existing=True,
        primary_root=tmp_path,
    )

    assert canonical_result.path == archived.resolve()
    assert not canonical_result.written
    assert archived.read_text(encoding="utf-8") == "canonical sentinel\n"
    assert preserved_result.path == existing
    assert not preserved_result.written
    assert existing.read_text(encoding="utf-8") == "existing sentinel\n"
