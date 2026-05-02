"""Tests for SDD file writing and frontmatter utilities."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.sdd.files import (
    update_prompt_with_qa,
    update_spec_with_qa,
    write_sdd_files,
)
from sase.sdd.frontmatter import parse_frontmatter, set_frontmatter_fields

# ---------------------------------------------------------------------------
# write_sdd_files
# ---------------------------------------------------------------------------


def test_write_sdd_files() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        plan_file = sdd_dir / "source_plan.yaml"
        plan_file.write_text("steps:\n  - do stuff\n", encoding="utf-8")

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            prompt_path, plan_path = write_sdd_files(
                sdd_dir, "my_plan", "# My Spec\nDetails here", str(plan_file)
            )

        assert prompt_path.exists()
        assert plan_path.exists()
        assert prompt_path.parent.name == "202603"
        assert plan_path.parent.name == "202603"
        prompt_fm, prompt_body, _ = parse_frontmatter(
            prompt_path.read_text(encoding="utf-8")
        )
        assert prompt_fm["plan"] == "tales/202603/my_plan.md"
        assert prompt_body == "# My Spec\nDetails here"
        plan_text = plan_path.read_text(encoding="utf-8")
        assert plan_text.startswith("---\ncreate_time:")
        plan_fm, _, _ = parse_frontmatter(plan_text)
        assert plan_fm["prompt"] == "prompts/202603/my_plan.md"
        assert "steps:" in plan_text


def test_write_sdd_files_missing_plan() -> None:
    """If source plan file doesn't exist, plan_path is not written."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            prompt_path, plan_path = write_sdd_files(
                sdd_dir, "my_plan", "spec content", "/nonexistent/plan.yaml"
            )
        assert prompt_path.exists()
        assert not plan_path.exists()
        prompt_fm, prompt_body, _ = parse_frontmatter(
            prompt_path.read_text(encoding="utf-8")
        )
        assert prompt_fm["plan"] == "tales/202603/my_plan.md"
        assert prompt_body == "spec content"


def test_write_sdd_files_creates_dirs() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / "nested" / "sdd"
        plan_file = Path(tmpdir) / "plan.yaml"
        plan_file.write_text("plan", encoding="utf-8")

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            write_sdd_files(sdd_dir, "test", "spec", str(plan_file))
        assert (sdd_dir / "prompts" / "202603").is_dir()
        assert (sdd_dir / "tales" / "202603").is_dir()


def test_write_sdd_files_epic_kind() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        plan_file = sdd_dir / "source_plan.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            prompt_path, plan_path = write_sdd_files(
                sdd_dir,
                "my_epic",
                "spec",
                str(plan_file),
                plan_kind="epics",
            )

        assert prompt_path == sdd_dir / "prompts" / "202603" / "my_epic.md"
        assert plan_path == sdd_dir / "epics" / "202603" / "my_epic.md"
        assert plan_path.exists()
        prompt_fm, _, _ = parse_frontmatter(prompt_path.read_text(encoding="utf-8"))
        plan_fm, _, _ = parse_frontmatter(plan_path.read_text(encoding="utf-8"))
        assert prompt_fm["plan"] == "epics/202603/my_epic.md"
        assert plan_fm["prompt"] == "prompts/202603/my_epic.md"


def test_write_sdd_files_uses_canonical_sdd_kinds_only() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / "sdd"
        plan_file = Path(tmpdir) / "source_plan.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            for plan_kind in ("tales", "epics", "legends"):
                write_sdd_files(
                    sdd_dir,
                    f"my_{plan_kind}",
                    "spec",
                    str(plan_file),
                    plan_kind=plan_kind,
                )
            write_sdd_files(
                sdd_dir,
                "my_legacy_plans",
                "spec",
                str(plan_file),
                plan_kind="plans",
            )

        assert (sdd_dir / "prompts" / "202603").is_dir()
        assert (sdd_dir / "tales" / "202603" / "my_tales.md").exists()
        assert (sdd_dir / "tales" / "202603" / "my_legacy_plans.md").exists()
        assert (sdd_dir / "epics" / "202603" / "my_epics.md").exists()
        assert (sdd_dir / "legends" / "202603" / "my_legends.md").exists()
        assert not (Path(tmpdir) / "plans").exists()
        assert not (sdd_dir / "plans").exists()
        assert not (Path(tmpdir) / "prompts").exists()
        assert not (Path(tmpdir) / "specs").exists()


def test_write_sdd_files_rejects_unknown_plan_kind() -> None:
    with pytest.raises(ValueError, match="invalid SDD plan kind"):
        write_sdd_files(Path("/tmp/sdd"), "bad", "spec", "/tmp/plan.md", plan_kind="x")


def test_write_sdd_files_uses_sdd_relative_links() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / "sdd"
        plan_file = Path(tmpdir) / "source_plan.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            prompt_path, plan_path = write_sdd_files(
                sdd_dir, "linked", "prompt", str(plan_file)
            )

        prompt_fm, _, _ = parse_frontmatter(prompt_path.read_text(encoding="utf-8"))
        plan_fm, _, _ = parse_frontmatter(plan_path.read_text(encoding="utf-8"))
        assert prompt_fm["plan"] == "sdd/tales/202603/linked.md"
        assert plan_fm["prompt"] == "sdd/prompts/202603/linked.md"


def test_write_sdd_files_uses_local_sase_sdd_relative_links() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / ".sase" / "sdd"
        plan_file = Path(tmpdir) / "source_plan.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            prompt_path, plan_path = write_sdd_files(
                sdd_dir, "linked", "prompt", str(plan_file)
            )

        prompt_fm, _, _ = parse_frontmatter(prompt_path.read_text(encoding="utf-8"))
        plan_fm, _, _ = parse_frontmatter(plan_path.read_text(encoding="utf-8"))
        assert prompt_fm["plan"] == ".sase/sdd/tales/202603/linked.md"
        assert plan_fm["prompt"] == ".sase/sdd/prompts/202603/linked.md"


def test_write_sdd_files_preserves_existing_plan_frontmatter() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / "sdd"
        plan_file = Path(tmpdir) / "source_plan.md"
        plan_file.write_text(
            "---\n"
            "bead_id: sase-1y\n"
            "legend_bead_id: sase-legend\n"
            "tier: epic\n"
            "status: ready\n"
            "---\n"
            "# Plan\n",
            encoding="utf-8",
        )

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            _, plan_path = write_sdd_files(
                sdd_dir,
                "preserve",
                "prompt",
                str(plan_file),
                plan_kind="epics",
            )

        plan_fm, body, _ = parse_frontmatter(plan_path.read_text(encoding="utf-8"))
        assert plan_fm["bead_id"] == "sase-1y"
        assert plan_fm["legend_bead_id"] == "sase-legend"
        assert plan_fm["tier"] == "epic"
        assert plan_fm["status"] == "ready"
        assert plan_fm["prompt"] == "sdd/prompts/202603/preserve.md"
        assert body.lstrip("\n") == "# Plan\n"


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


# ---------------------------------------------------------------------------
# update_prompt_with_qa
# ---------------------------------------------------------------------------


def test_update_prompt_with_qa() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        prompt_path = Path(tmpdir) / "prompt.md"
        prompt_path.write_text("# Prompt\nOriginal content", encoding="utf-8")

        update_prompt_with_qa(prompt_path, "## Q&A\nQ: Why?\nA: Because.")

        content = prompt_path.read_text(encoding="utf-8")
        assert "Original content" in content
        assert "## Q&A" in content
        assert "Q: Why?" in content


def test_update_prompt_with_qa_missing_file() -> None:
    """No-op if prompt file doesn't exist."""
    update_prompt_with_qa(Path("/nonexistent/prompt.md"), "qa content")
    # Should not raise


def test_update_spec_with_qa_legacy_wrapper() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        prompt_path = Path(tmpdir) / "prompt.md"
        prompt_path.write_text("# Prompt\nOriginal content", encoding="utf-8")

        update_spec_with_qa(prompt_path, "## Q&A\nQ: Why?\nA: Because.")

        assert "## Q&A" in prompt_path.read_text(encoding="utf-8")
