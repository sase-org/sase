"""Tests for xprompt definition provenance resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase._repo_inventory_models import RepoInventory, RepoRecord
from sase.xprompt.models import XPrompt
from sase.xprompt.xprompt_sources import (
    collect_xprompt_sources,
    definition_line_for,
    _resolve_definition_repo,
)


def _repo(name: str, root: Path) -> RepoRecord:
    return RepoRecord(
        name=name,
        kind="primary",
        project=name,
        project_key=name,
        path=str(root),
        exists=True,
        auto_clone=False,
        description=None,
        source="test",
        env_name=None,
    )


def _patch_catalogs(
    monkeypatch: pytest.MonkeyPatch,
    parts: dict[str, XPrompt],
) -> None:
    import sase.xprompt.used_xprompts as used_xprompts

    monkeypatch.setattr(used_xprompts, "get_all_xprompts", lambda: parts)
    monkeypatch.setattr(used_xprompts, "get_all_workflows", lambda: {})
    monkeypatch.setattr(used_xprompts, "resolve_xprompt_aliases", lambda value: value)


def test_collects_project_definition_and_preserves_exact_vcs_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.xprompt.used_xprompts as used_xprompts
    import sase.xprompt.xprompt_sources as sources

    root = tmp_path / "project"
    definition = root / "sase" / "xprompts" / "deploy.md"
    definition.parent.mkdir(parents=True)
    definition.write_text("Deploy it.\n", encoding="utf-8")
    _patch_catalogs(
        monkeypatch,
        {"gh": XPrompt(name="gh", content="", source_path=str(definition))},
    )
    monkeypatch.setattr(
        used_xprompts,
        "normalize_vcs_underscore_refs",
        lambda value: value.replace("#gh_project", "#gh:project"),
    )
    monkeypatch.setattr(
        sources,
        "collect_repo_inventory",
        lambda: RepoInventory((_repo("project", root),)),
    )
    monkeypatch.setattr(sources, "get_use_chezmoi", lambda: True)

    records = collect_xprompt_sources("Run #gh_project now")

    assert records == [
        {
            "schema_version": 1,
            "raw_ref": "#gh_project",
            "name": "gh",
            "kind": "part",
            "source_kind": "markdown",
            "source_path": str(definition),
            "definition_line": None,
            "repo": "project",
            "repo_root": str(root),
            "repo_relpath": "sase/xprompts/deploy.md",
            "chezmoi": False,
            "skipped_reason": None,
        }
    ]


@pytest.mark.parametrize("use_chezmoi", [False, True])
def test_home_markdown_definition_respects_chezmoi_setting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    use_chezmoi: bool,
) -> None:
    import sase.xprompt.xprompt_sources as sources

    home_definition = tmp_path / "home" / "sase" / "xprompts" / "note.md"
    home_definition.parent.mkdir(parents=True)
    home_definition.write_text("Remember this.\n", encoding="utf-8")
    chezmoi_root = tmp_path / "chezmoi"
    mapped = chezmoi_root / "home" / "sase" / "xprompts" / "note.md"
    mapped.parent.mkdir(parents=True)
    mapped.write_text("Remember this.\n", encoding="utf-8")
    _patch_catalogs(
        monkeypatch,
        {"note": XPrompt(name="note", content="", source_path=str(home_definition))},
    )
    monkeypatch.setattr(sources, "get_use_chezmoi", lambda: use_chezmoi)
    monkeypatch.setattr(sources, "_is_relative_to", lambda path, root: True)
    monkeypatch.setattr(sources, "chezmoi_source_path", lambda path: mapped)
    monkeypatch.setattr(
        sources,
        "collect_repo_inventory",
        lambda: RepoInventory((_repo("chezmoi", chezmoi_root),)),
    )

    record = collect_xprompt_sources("#note")[0]

    assert record["chezmoi"] is use_chezmoi
    assert record["repo"] == ("chezmoi" if use_chezmoi else None)
    assert record["repo_relpath"] == (
        "home/sase/xprompts/note.md" if use_chezmoi else None
    )
    assert record["skipped_reason"] == (None if use_chezmoi else "repository-not-found")


def test_user_config_definition_gets_unique_line_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.xprompt.xprompt_sources as sources

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config = config_dir / "sase.yml"
    config.write_text(
        "models: {}\nxprompts:\n  review:\n    content: Review this.\n",
        encoding="utf-8",
    )
    _patch_catalogs(
        monkeypatch,
        {"review": XPrompt(name="review", content="", source_path="config")},
    )
    monkeypatch.setattr(sources, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(sources, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(
        sources,
        "collect_repo_inventory",
        lambda: RepoInventory((_repo("dotfiles", config_dir),)),
    )

    record = collect_xprompt_sources("Please #review")[0]

    assert record["source_path"] == str(config)
    assert record["source_kind"] == "yaml"
    assert record["definition_line"] == 3


def test_package_default_definition_is_owned_by_primary_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.xprompt.xprompt_sources as sources

    root = Path.cwd()
    _patch_catalogs(
        monkeypatch,
        {"plan": XPrompt(name="plan", content="", source_path="default_config")},
    )
    monkeypatch.setattr(sources, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(
        sources,
        "collect_repo_inventory",
        lambda: RepoInventory((_repo("sase", root),)),
    )

    record = collect_xprompt_sources("#plan")[0]

    assert record["repo"] == "sase"
    assert record["repo_relpath"] == "src/sase/default_config.yml"
    assert isinstance(record["definition_line"], int)
    assert record["definition_line"] > 0


def test_unknown_and_literal_zone_references_are_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_catalogs(monkeypatch, {"known": XPrompt(name="known", content="")})

    records = collect_xprompt_sources("```\n#known\n```\nRun #missing")

    assert [(record["raw_ref"], record["skipped_reason"]) for record in records] == [
        ("#missing", "unknown-reference")
    ]


def test_swarm_launch_records_definition_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.xprompt.xprompt_sources as sources

    definition = tmp_path / "repo" / "xprompts" / "research_swarm.md"
    definition.parent.mkdir(parents=True)
    definition.write_text("Research.\n", encoding="utf-8")
    _patch_catalogs(
        monkeypatch,
        {
            "research_swarm": XPrompt(
                name="research_swarm",
                content="",
                source_path=str(definition),
            )
        },
    )
    monkeypatch.setattr(sources, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(
        sources,
        "collect_repo_inventory",
        lambda: RepoInventory((_repo("research", tmp_path / "repo"),)),
    )

    records = collect_xprompt_sources(
        "Rendered swarm segment",
        swarm_xprompts=["research_swarm"],
    )

    assert [(record["raw_ref"], record["kind"]) for record in records] == [
        ("#research_swarm", "swarm")
    ]
    assert records[0]["repo_relpath"] == "xprompts/research_swarm.md"


def test_definition_line_does_not_guess_ambiguous_key(tmp_path: Path) -> None:
    source = tmp_path / "sase.yml"
    source.write_text(
        "xprompts:\n  review: first\nworkflows:\n  review: second\n",
        encoding="utf-8",
    )

    assert definition_line_for(source, "review") is None


def test_definition_repo_chooses_deepest_containing_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.xprompt.xprompt_sources as sources

    outer = tmp_path / "outer"
    inner = outer / "nested"
    definition = inner / "prompt.md"
    definition.parent.mkdir(parents=True)
    definition.write_text("Prompt.\n", encoding="utf-8")
    monkeypatch.setattr(sources, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(
        sources,
        "collect_repo_inventory",
        lambda: RepoInventory((_repo("outer", outer), _repo("inner", inner))),
    )

    resolved = _resolve_definition_repo(definition)

    assert resolved.repo == "inner"
    assert resolved.repo_relpath == "prompt.md"
