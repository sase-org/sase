"""Migration coverage for nesting SDD prompts below plan month directories."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
import subprocess

import pytest

from sase.main.sdd_handler import handle_sdd_command
from sase.sdd._prompt_migration import (
    migrate_legacy_prompt_directories,
    plan_legacy_prompt_migration,
)
from sase.sdd.files import commit_sdd_files
from sase.sdd.frontmatter import parse_frontmatter
from sase.sdd.links import list_sdd_files, repair_sdd_links, validate_sdd_tree
from sase.sdd.store import SddStore
from tests.main.sdd_handler_helpers import make_args


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _frontmatter(path: Path) -> dict[str, object]:
    fields, _, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
    return fields


def test_migration_moves_rewrites_deduplicates_and_is_idempotent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sdd"
    _write(
        root / "plans" / "202607" / "prompts" / "collision.md",
        "# Existing\n",
    )
    _write(root / "prompts" / "202607" / "bare.md", "# Bare\n")
    _write(root / "prompts" / "202607" / "prefixed.md", "# Prefixed\n")
    _write(root / "prompts" / "202607" / "collision.md", "# Collision\n")
    _write(root / "specs" / "202607" / "local.md", "# Local\n")
    _write(
        root / "plans" / "202607" / "bare.md",
        "---\nprompt: prompts/202607/bare.md\ntier: tale\n---\n# Bare plan\n",
    )
    _write(
        root / "plans" / "202607" / "prefixed.md",
        "---\nprompt: sdd/prompts/202607/prefixed.md\ntier: tale\n---\n# Plan\n",
    )
    _write(
        root / "plans" / "202607" / "local.md",
        "---\nprompt: .sase/sdd/specs/202607/local.md\ntier: tale\n---\n# Plan\n",
    )
    collision_plan = _write(
        root / "plans" / "202607" / "collision.md",
        "---\nprompt: sdd/prompts/202607/collision.md\ntier: tale\n---\n# Plan\n",
    )
    legend = _write(
        root / "legends" / "202607" / "linked.md",
        "---\nprompt: sdd/prompts/202607/prefixed.md\n---\n# Legend\n",
    )

    planned = plan_legacy_prompt_migration(root)
    assert len(planned) == 4

    result = migrate_legacy_prompt_directories(root)

    nested = root / "plans" / "202607" / "prompts"
    assert (nested / "bare.md").exists()
    assert (nested / "prefixed.md").exists()
    assert (nested / "local.md").exists()
    assert (nested / "collision_1.md").read_text(encoding="utf-8") == "# Collision\n"
    assert _frontmatter(root / "plans" / "202607" / "bare.md")["prompt"] == (
        "plans/202607/prompts/bare.md"
    )
    assert _frontmatter(root / "plans" / "202607" / "prefixed.md")["prompt"] == (
        "sdd/plans/202607/prompts/prefixed.md"
    )
    assert _frontmatter(root / "plans" / "202607" / "local.md")["prompt"] == (
        ".sase/sdd/plans/202607/prompts/local.md"
    )
    assert _frontmatter(collision_plan)["prompt"] == (
        "sdd/plans/202607/prompts/collision_1.md"
    )
    assert _frontmatter(legend)["prompt"] == ("sdd/plans/202607/prompts/prefixed.md")
    assert not (root / "prompts").exists()
    assert not (root / "specs").exists()
    assert len(result.moved) == 4

    rerun = migrate_legacy_prompt_directories(root)
    assert rerun.moved == ()
    assert rerun.changed == ()


def test_migration_shards_monthless_prompt_by_mtime(tmp_path: Path) -> None:
    root = tmp_path / "sdd"
    flat = _write(root / "prompts" / "flat.md", "# Flat\n")
    epoch = 1_767_225_600
    os.utime(flat, (epoch, epoch))

    migrate_legacy_prompt_directories(root)

    shard = datetime.fromtimestamp(epoch).strftime("%Y%m")
    assert (root / "plans" / shard / "prompts" / "flat.md").exists()


def test_nested_prompt_list_validate_and_repair_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "sdd"
    prompt = _write(
        root / "plans" / "202607" / "prompts" / "pair.md",
        "# Prompt\n",
    )
    plan = _write(
        root / "plans" / "202607" / "pair.md",
        "---\ntier: tale\n---\n# Plan\n",
    )

    assert [file.relpath for file in list_sdd_files(root, kind="prompts")] == [
        "plans/202607/prompts/pair.md"
    ]
    report = repair_sdd_links(str(root), write=True)
    assert set(report.changed_files) == {
        "plans/202607/pair.md",
        "plans/202607/prompts/pair.md",
    }
    assert _frontmatter(prompt)["plan"] == "sdd/plans/202607/pair.md"
    assert _frontmatter(plan)["prompt"] == "sdd/plans/202607/prompts/pair.md"
    assert validate_sdd_tree(str(root)).ok is True


def test_targeted_commit_includes_both_sides_of_prompt_renames(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sdd"
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    source = _write(root / "prompts" / "202607" / "move.md", "# Prompt\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=tmp_path, check=True)

    migration = migrate_legacy_prompt_directories(root)

    assert commit_sdd_files(
        tmp_path,
        "Migrate prompts",
        paths=[*migration.moved, *migration.changed],
    )
    status = subprocess.run(
        ["git", "status", "--short"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert status == ""
    assert source in migration.changed
    assert not source.exists()
    assert (root / "plans" / "202607" / "prompts" / "move.md").exists()


def test_init_commits_migration_for_external_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "sase.yml").write_text("is_sase_managed: true\n", encoding="utf-8")
    root = tmp_path / "sidecar"
    _write(root / "prompts" / "202607" / "move.md", "# Prompt\n")
    store = SddStore(storage="local", sdd_dir=root, repo_root=root)
    committed: list[tuple[str, list[Path]]] = []

    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store", lambda *_args, **_kwargs: store
    )

    def commit(_store: SddStore, message: str, *, paths: list[Path]) -> bool:
        committed.append((message, paths))
        return True

    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", commit)

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(make_args(sdd_subcommand="init", path=str(tmp_path)))

    assert excinfo.value.code == 0
    assert committed[0][0] == "Migrate SDD prompts into plan month directories"
    assert root / "plans" / "202607" / "prompts" / "move.md" in committed[0][1]
