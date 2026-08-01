"""Tests for SDD plan/prompt file writing and frontmatter utilities."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.sdd.committed_plan_validation import _CommittedPlanValidationError
from sase.sdd.files import (
    write_sdd_files,
    write_sdd_spec,
)
from sase.sdd.artifact_links import parse_sdd_artifact_link
from sase.sdd.frontmatter import parse_frontmatter, set_frontmatter_fields
from sase.sdd.store import SddStore


@pytest.fixture(autouse=True)
def _hosted_prompt_links(monkeypatch: pytest.MonkeyPatch) -> None:
    class Resolver:
        def prompt_url(self, prompt_ref: str) -> str:
            return f"https://example.test/agents/{prompt_ref}"

        def plan_url(self, _plan_ref: str) -> None:
            return None

        def bead_url(self, _bead_id: str) -> None:
            return None

    monkeypatch.setattr(
        "sase.sdd.hosted_links.hosted_link_resolver",
        lambda *_args, **_kwargs: Resolver(),
    )


def _prompt_path(root: Path, month: str, name: str) -> Path:
    return root / "repo--agents" / "prompts" / month / f"{name}.md"


def test_write_sdd_files() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        plan_file = sdd_dir / "source_plan.yaml"
        plan_file.write_text("steps:\n  - do stuff\n", encoding="utf-8")
        prompt_archive = _prompt_path(sdd_dir, "202603", "my_plan")
        store = SddStore("sidecar_repos", sdd_dir / "plans", sdd_dir / "plans")

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            prompt_path, plan_path = write_sdd_files(
                sdd_dir,
                "my_plan",
                "# My Spec\nDetails here",
                str(plan_file),
                prompt_path=prompt_archive,
                store=store,
            )

        assert prompt_path == prompt_archive
        assert not prompt_path.exists()
        assert plan_path.exists()
        assert plan_path.parent.name == "202603"
        plan_text = plan_path.read_text(encoding="utf-8")
        assert plan_text.startswith("---\ncreate_time:")
        plan_fm, _, _ = parse_frontmatter(plan_text)
        plan_link = parse_sdd_artifact_link(plan_text)
        assert "prompt" not in plan_fm
        assert plan_link.reference == "prompts/202603/my_plan.md"
        assert plan_link.target == (
            "https://example.test/agents/prompts/202603/my_plan.md"
        )
        assert plan_fm["tier"] == "tale"
        assert "steps:" in plan_text


def test_write_sdd_files_supports_flat_sidecar_plans_root(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text(
        "---\n"
        "tier: tale\n"
        "title: Flat sidecar plan\n"
        "goal: Preserve canonical links in a flat plans sidecar\n"
        "---\n"
        "# Plan\n",
        encoding="utf-8",
    )
    plans_root = tmp_path / "repo--plans"
    prompt_archive = _prompt_path(tmp_path, "202608", "flat_plan")
    store = SddStore("sidecar_repos", plans_root, plans_root)

    with patch("sase.sdd.files.get_yyyymm", return_value="202608"):
        prompt, plan = write_sdd_files(
            plans_root,
            "flat_plan",
            "# Prompt\n",
            str(source),
            plans_root=plans_root,
            prompt_path=prompt_archive,
            store=store,
        )

    assert prompt == prompt_archive
    assert not prompt.exists()
    assert plan == plans_root / "202608" / "flat_plan.md"
    plan_text = plan.read_text(encoding="utf-8")
    plan_fm, _, _ = parse_frontmatter(plan_text)
    assert "prompt" not in plan_fm
    assert plan_fm["title"] == "Flat sidecar plan"
    assert plan_fm["goal"] == "Preserve canonical links in a flat plans sidecar"
    assert (
        "- **PROMPT:** [prompts/202608/flat_plan.md]"
        "(https://example.test/agents/prompts/202608/flat_plan.md)" in plan_text
    )


def test_write_sdd_files_rebases_seeded_parent_section(tmp_path: Path) -> None:
    from sase.sdd.plan_header_block import (
        PlanHeaderSectionKind,
        parse_plan_header_block,
    )
    from sase.sdd.plan_header_writes import upsert_parent_plan_section

    plans_root = tmp_path / "plans"
    parent = plans_root / "202608" / "parent.md"
    parent.parent.mkdir(parents=True)
    parent.write_text("# Parent\n", encoding="utf-8")
    source = tmp_path / "source.md"
    source.write_text(
        upsert_parent_plan_section(
            "---\n"
            "tier: tale\n"
            "title: Child plan\n"
            "goal: Preserve and rebase the parent plan link\n"
            "---\n"
            "# Child\n",
            "plans:202608/parent.md",
        ),
        encoding="utf-8",
    )
    prompt_archive = _prompt_path(tmp_path, "202608", "child")
    store = SddStore("sidecar_repos", plans_root, plans_root)

    with patch("sase.sdd.files.get_yyyymm", return_value="202608"):
        _prompt, plan = write_sdd_files(
            tmp_path,
            "child",
            "# Prompt\n",
            str(source),
            plans_root=plans_root,
            prompt_path=prompt_archive,
            store=store,
        )

    plan_text = plan.read_text(encoding="utf-8")
    plan_fm, _, _ = parse_frontmatter(plan_text)
    assert plan_fm["title"] == "Child plan"
    assert plan_fm["goal"] == "Preserve and rebase the parent plan link"
    parsed = parse_plan_header_block(plan_text)
    assert [section.kind for section in parsed.sections] == [
        PlanHeaderSectionKind.PROMPT,
        PlanHeaderSectionKind.PARENT,
    ]
    parent_section = parsed.sections[1]
    assert parent_section.label == "202608/parent.md"
    assert parent_section.target == "parent.md"


def test_write_sdd_spec_does_not_write_plan(tmp_path: Path) -> None:
    sdd_dir = tmp_path / "sdd"
    prompt_archive = _prompt_path(tmp_path, "202607", "host_owned_epic")

    with patch("sase.sdd.files.get_yyyymm", return_value="202607"):
        prompt_path, plan_path = write_sdd_spec(
            sdd_dir,
            "host_owned_epic",
            "# Planner prompt\n",
            prompt_path=prompt_archive,
        )

    assert prompt_path == prompt_archive
    assert not prompt_path.exists()
    assert not plan_path.exists()
    assert not (sdd_dir / "plans" / "202607" / "prompts").exists()


def test_write_sdd_files_missing_plan() -> None:
    """If source plan file doesn't exist, plan_path is not written."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            prompt_path, plan_path = write_sdd_files(
                sdd_dir, "my_plan", "spec content", "/nonexistent/plan.yaml"
            )
        assert prompt_path is None
        assert not plan_path.exists()
        assert not (sdd_dir / "plans" / "202603" / "prompts").exists()


def test_write_sdd_files_creates_dirs() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / "nested" / "sdd"
        plan_file = Path(tmpdir) / "plan.yaml"
        plan_file.write_text("plan", encoding="utf-8")

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            write_sdd_files(sdd_dir, "test", "spec", str(plan_file))
        assert (sdd_dir / "plans" / "202603").is_dir()
        assert not (sdd_dir / "plans" / "202603" / "prompts").exists()


def test_write_sdd_files_epic_tier() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        plan_file = sdd_dir / "source_plan.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")
        prompt_archive = _prompt_path(sdd_dir, "202603", "my_epic")
        store = SddStore("sidecar_repos", sdd_dir / "plans", sdd_dir / "plans")

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            prompt_path, plan_path = write_sdd_files(
                sdd_dir,
                "my_epic",
                "spec",
                str(plan_file),
                plan_tier="epic",
                prompt_path=prompt_archive,
                store=store,
            )

        assert prompt_path == prompt_archive
        assert not prompt_path.exists()
        assert plan_path == sdd_dir / "plans" / "202603" / "my_epic.md"
        assert plan_path.exists()
        plan_text = plan_path.read_text(encoding="utf-8")
        plan_fm, _, _ = parse_frontmatter(plan_text)
        assert "prompt" not in plan_fm
        assert parse_sdd_artifact_link(plan_text).reference == (
            "prompts/202603/my_epic.md"
        )
        assert plan_fm["tier"] == "epic"


def test_write_sdd_files_uses_canonical_plan_directory_for_both_tiers() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / "sdd"
        plan_file = Path(tmpdir) / "source_plan.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            for plan_tier in ("tale", "epic"):
                write_sdd_files(
                    sdd_dir,
                    f"my_{plan_tier}",
                    "spec",
                    str(plan_file),
                    plan_tier=plan_tier,
                )

        assert not (sdd_dir / "plans" / "202603" / "prompts").exists()
        assert (sdd_dir / "plans" / "202603" / "my_tale.md").exists()
        assert (sdd_dir / "plans" / "202603" / "my_epic.md").exists()
        assert not (Path(tmpdir) / "plans").exists()
        assert not (sdd_dir / "tales").exists()
        assert not (sdd_dir / "epics").exists()
        assert not (Path(tmpdir) / "prompts").exists()
        assert not (Path(tmpdir) / "specs").exists()


def test_write_sdd_files_rejects_unknown_plan_tier() -> None:
    with pytest.raises(ValueError, match="invalid SDD plan tier"):
        write_sdd_files(Path("/tmp/sdd"), "bad", "spec", "/tmp/plan.md", plan_tier="x")


def test_write_sdd_files_rejects_invalid_cutover_plan_before_writing(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.md"
    source.write_text("---\ntier: tale\n---\n# Plan\n", encoding="utf-8")
    sdd_dir = tmp_path / "sdd"

    with (
        patch("sase.sdd.files.get_yyyymm", return_value="202608"),
        pytest.raises(_CommittedPlanValidationError, match="required-missing"),
    ):
        write_sdd_files(sdd_dir, "invalid", "# Prompt\n", str(source))

    assert not (sdd_dir / "plans" / "202608" / "invalid.md").exists()
    assert not (sdd_dir / "plans" / "202608" / "prompts" / "invalid.md").exists()


def test_write_sdd_files_uses_sdd_relative_links() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / "sdd"
        plan_file = Path(tmpdir) / "source_plan.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")
        prompt_archive = _prompt_path(sdd_dir, "202603", "linked")
        store = SddStore("sidecar_repos", sdd_dir / "plans", sdd_dir / "plans")

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            prompt_path, plan_path = write_sdd_files(
                sdd_dir,
                "linked",
                "prompt",
                str(plan_file),
                prompt_path=prompt_archive,
                store=store,
            )

        assert prompt_path == prompt_archive
        assert not prompt_path.exists()
        plan_text = plan_path.read_text(encoding="utf-8")
        plan_fm, _, _ = parse_frontmatter(plan_text)
        assert "prompt" not in plan_fm
        assert (
            "- **PROMPT:** [prompts/202603/linked.md]"
            "(https://example.test/agents/prompts/202603/linked.md)" in plan_text
        )


def test_write_sdd_files_uses_local_sase_sdd_relative_links() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / ".sase" / "sdd"
        plan_file = Path(tmpdir) / "source_plan.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")
        prompt_archive = _prompt_path(sdd_dir, "202603", "linked")
        store = SddStore("sidecar_repos", sdd_dir / "plans", sdd_dir / "plans")

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            prompt_path, plan_path = write_sdd_files(
                sdd_dir,
                "linked",
                "prompt",
                str(plan_file),
                prompt_path=prompt_archive,
                store=store,
            )

        assert prompt_path == prompt_archive
        assert not prompt_path.exists()
        plan_text = plan_path.read_text(encoding="utf-8")
        plan_fm, _, _ = parse_frontmatter(plan_text)
        assert "prompt" not in plan_fm
        assert (
            "- **PROMPT:** [prompts/202603/linked.md]"
            "(https://example.test/agents/prompts/202603/linked.md)" in plan_text
        )


def test_write_sdd_files_preserves_existing_plan_frontmatter() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / "sdd"
        plan_file = Path(tmpdir) / "source_plan.md"
        plan_file.write_text(
            "---\nbead_id: sase-1y\ntier: epic\nstatus: ready\n---\n# Plan\n",
            encoding="utf-8",
        )
        prompt_archive = _prompt_path(sdd_dir, "202603", "preserve")
        store = SddStore("sidecar_repos", sdd_dir / "plans", sdd_dir / "plans")

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            _, plan_path = write_sdd_files(
                sdd_dir,
                "preserve",
                "prompt",
                str(plan_file),
                plan_tier="epic",
                prompt_path=prompt_archive,
                store=store,
            )

        plan_text = plan_path.read_text(encoding="utf-8")
        plan_fm, _, _ = parse_frontmatter(plan_text)
        plan_link = parse_sdd_artifact_link(plan_text)
        assert plan_fm["bead_id"] == "sase-1y"
        assert plan_fm["tier"] == "epic"
        assert plan_fm["status"] == "ready"
        assert "prompt" not in plan_fm
        assert plan_link.reference == "prompts/202603/preserve.md"
        assert plan_link.body == "# Plan\n"


def test_set_frontmatter_fields_is_idempotent() -> None:
    content = "---\nplan: old.md\nkeep: yes\n---\n# Prompt\n"

    once = set_frontmatter_fields(content, {"plan": "new.md"})
    twice = set_frontmatter_fields(once, {"plan": "new.md"})

    assert twice == once
    fm, body, had_frontmatter = parse_frontmatter(twice)
    assert had_frontmatter is True
    assert fm["plan"] == "new.md"
    assert fm["keep"] is True
    assert body == "# Prompt\n"
