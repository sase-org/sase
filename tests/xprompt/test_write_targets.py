"""XPrompt write-target resolution."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sase.xprompt import write_targets


def _set_home_and_chezmoi(
    monkeypatch,
    home: Path,
    source_root: Path,
    *,
    use_chezmoi: bool,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(write_targets, "CHEZMOI_HOME", source_root)
    monkeypatch.setattr(write_targets, "get_use_chezmoi", lambda: use_chezmoi)


def test_resolver_defaults_to_read_path_when_chezmoi_disabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    source_root = home / ".local" / "share" / "chezmoi" / "home"
    read_path = home / "sase" / "xprompts" / "review.md"
    source_path = source_root / "sase" / "xprompts" / "review.md"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("source\n", encoding="utf-8")
    _set_home_and_chezmoi(monkeypatch, home, source_root, use_chezmoi=False)

    target = write_targets.resolve_xprompt_write_target(read_path)

    assert target.read_path == read_path
    assert target.write_path == read_path
    assert target.apply_target is None
    assert target.via_chezmoi is False


def test_resolver_keeps_home_path_when_chezmoi_source_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    source_root = home / ".local" / "share" / "chezmoi" / "home"
    read_path = home / "sase" / "xprompts" / "review.md"
    _set_home_and_chezmoi(monkeypatch, home, source_root, use_chezmoi=True)

    target = write_targets.resolve_xprompt_write_target(read_path)

    assert target.write_path == read_path
    assert target.apply_target is None
    assert target.via_chezmoi is False


def test_resolver_remaps_home_path_to_existing_chezmoi_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    source_root = home / ".local" / "share" / "chezmoi" / "home"
    read_path = home / "sase" / "xprompts" / "review.md"
    source_path = source_root / "sase" / "xprompts" / "review.md"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("source\n", encoding="utf-8")
    _set_home_and_chezmoi(monkeypatch, home, source_root, use_chezmoi=True)

    target = write_targets.resolve_xprompt_write_target(read_path)

    assert target.read_path == read_path
    assert target.write_path == source_path
    assert target.apply_target == read_path
    assert target.via_chezmoi is True


def test_resolver_does_not_remap_existing_chezmoi_source_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    source_root = home / ".local" / "share" / "chezmoi" / "home"
    source_path = source_root / "sase" / "xprompts" / "review.md"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("source\n", encoding="utf-8")
    _set_home_and_chezmoi(monkeypatch, home, source_root, use_chezmoi=True)

    target = write_targets.resolve_xprompt_write_target(source_path)

    assert target.write_path == source_path
    assert target.apply_target is None
    assert target.via_chezmoi is False


def test_resolver_does_not_remap_paths_outside_home(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    source_root = home / ".local" / "share" / "chezmoi" / "home"
    read_path = tmp_path / "repo" / "sase" / "xprompts" / "review.md"
    _set_home_and_chezmoi(monkeypatch, home, source_root, use_chezmoi=True)

    target = write_targets.resolve_xprompt_write_target(read_path)

    assert target.write_path == read_path
    assert target.via_chezmoi is False


def test_canonical_reference_uses_user_facing_memory_and_skill_forms(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    source_root = home / ".local" / "share" / "chezmoi" / "home"
    _set_home_and_chezmoi(monkeypatch, home, source_root, use_chezmoi=False)

    assert (
        write_targets.canonical_reference_for_path(
            home / "sase" / "memory" / "obsidian.md",
            reference="#obsidian",
        )
        == "#memory/obsidian"
    )
    assert (
        write_targets.canonical_reference_for_path(
            home / "sase" / "skills" / "review.md",
            reference="#skill/review",
        )
        == "/review"
    )
    assert (
        write_targets.canonical_reference_for_path(
            tmp_path / "repo" / "sase" / "xprompts" / "review.md",
            reference="#app/review",
        )
        == "#app/review"
    )


def test_written_path_reverse_maps_chezmoi_source_to_apply_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    source_root = home / ".local" / "share" / "chezmoi" / "home"
    source_path = source_root / "dot_config" / "sase" / "sase.yml"
    _set_home_and_chezmoi(monkeypatch, home, source_root, use_chezmoi=True)

    target = write_targets.write_target_for_written_path(source_path)

    assert target.read_path == home / ".config" / "sase" / "sase.yml"
    assert target.write_path == source_path
    assert target.apply_target == home / ".config" / "sase" / "sase.yml"
    assert target.via_chezmoi is True


def test_classifier_covers_skill_memory_config_and_plain_xprompt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    memory_root = tmp_path / "home" / "sase" / "memory"
    skill_root = tmp_path / "home" / "sase" / "skills"
    monkeypatch.setattr(
        write_targets,
        "resolve_memory_file_sources",
        lambda: (SimpleNamespace(paths=SimpleNamespace(write_path=memory_root)),),
    )
    monkeypatch.setattr(
        write_targets,
        "is_canonical_skill_directory",
        lambda directory: Path(directory) == skill_root,
    )

    assert (
        write_targets.classify_written_file(memory_root / "obsidian.md")
        is write_targets.WrittenFileKind.MEMORY_NOTE
    )
    assert (
        write_targets.classify_written_file(skill_root / "review.md")
        is write_targets.WrittenFileKind.SKILL_SOURCE
    )
    assert (
        write_targets.classify_written_file(tmp_path / "sase.yml")
        is write_targets.WrittenFileKind.CONFIG_ENTRY
    )
    assert (
        write_targets.classify_written_file(tmp_path / "xprompts" / "review.md")
        is write_targets.WrittenFileKind.XPROMPT
    )


def test_classifier_prefers_read_path_for_chezmoi_memory_note(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    memory_root = home / "sase" / "memory"
    source_path = (
        home
        / ".local"
        / "share"
        / "chezmoi"
        / "home"
        / "sase"
        / "memory"
        / "obsidian.md"
    )
    monkeypatch.setattr(
        write_targets,
        "resolve_memory_file_sources",
        lambda: (SimpleNamespace(paths=SimpleNamespace(write_path=memory_root)),),
    )

    kind = write_targets.classify_written_file(
        source_path,
        read_path=memory_root / "obsidian.md",
    )

    assert kind is write_targets.WrittenFileKind.MEMORY_NOTE


def test_followup_offers_commit_and_scoped_apply_for_plain_chezmoi_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    write_path = tmp_path / "repo" / "home" / "sase" / "xprompts" / "review.md"
    target = write_targets.XPromptWriteTarget(
        read_path=tmp_path / "home" / "sase" / "xprompts" / "review.md",
        write_path=write_path,
        apply_target=tmp_path / "home" / "sase" / "xprompts" / "review.md",
        via_chezmoi=True,
    )
    monkeypatch.setattr(write_targets, "get_git_root", lambda _path: str(tmp_path))
    monkeypatch.setattr(
        write_targets,
        "has_git_changes",
        lambda _root, _path: True,
    )

    offers = write_targets.build_post_write_action_offers(
        target,
        kind=write_targets.WrittenFileKind.XPROMPT,
        is_new=False,
        xprompt_name="review",
    )

    assert [offer.kind for offer in offers] == [
        write_targets.PostWriteActionKind.COMMIT_PUSH,
        write_targets.PostWriteActionKind.APPLY_CHEZMOI,
    ]
    assert offers[1].apply_target == str(target.apply_target)


def test_followup_commit_offer_stamps_sase_type_xprompt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    write_path = tmp_path / "repo" / "home" / "sase" / "xprompts" / "review.md"
    target = write_targets.XPromptWriteTarget(
        read_path=tmp_path / "home" / "sase" / "xprompts" / "review.md",
        write_path=write_path,
        apply_target=None,
        via_chezmoi=False,
    )
    monkeypatch.setattr(write_targets, "get_git_root", lambda _path: str(tmp_path))
    monkeypatch.setattr(
        write_targets,
        "has_git_changes",
        lambda _root, _path: True,
    )

    offers = write_targets.build_post_write_action_offers(
        target,
        kind=write_targets.WrittenFileKind.XPROMPT,
        is_new=False,
        xprompt_name="review",
    )

    assert offers[0].kind is write_targets.PostWriteActionKind.COMMIT_PUSH
    assert offers[0].commit_message is not None
    assert "SASE_TYPE=xprompt" in offers[0].commit_message


def test_followup_memory_init_has_message_and_cwd(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = write_targets.XPromptWriteTarget(
        read_path=tmp_path / "home" / "sase" / "memory" / "obsidian.md",
        write_path=tmp_path / "repo" / "home" / "sase" / "memory" / "obsidian.md",
        apply_target=tmp_path / "home" / "sase" / "memory" / "obsidian.md",
        via_chezmoi=True,
    )
    monkeypatch.setattr(write_targets, "get_git_root", lambda _path: str(tmp_path))
    monkeypatch.setattr(
        write_targets,
        "has_git_changes",
        lambda _root, _path: True,
    )

    offers = write_targets.build_post_write_action_offers(
        target,
        kind=write_targets.WrittenFileKind.MEMORY_NOTE,
        is_new=False,
        xprompt_name="obsidian",
    )

    assert [offer.kind for offer in offers] == [
        write_targets.PostWriteActionKind.MEMORY_INIT
    ]
    assert offers[0].cwd == str(tmp_path)
    assert offers[0].command == (
        "sase",
        "memory",
        "init",
        "--message",
        "Update memory note obsidian",
    )

    new_offers = write_targets.build_post_write_action_offers(
        target,
        kind=write_targets.WrittenFileKind.MEMORY_NOTE,
        is_new=True,
        xprompt_name="obsidian",
    )

    assert new_offers[0].command == (
        "sase",
        "memory",
        "init",
        "--message",
        "Add memory note obsidian",
    )


def test_followup_skill_init_commits_dirty_source_before_deploy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = write_targets.XPromptWriteTarget(
        read_path=tmp_path / "repo" / "sase" / "skills" / "foo.md",
        write_path=tmp_path / "repo" / "sase" / "skills" / "foo.md",
        apply_target=None,
        via_chezmoi=False,
    )
    monkeypatch.setattr(write_targets, "get_git_root", lambda _path: str(tmp_path))
    monkeypatch.setattr(
        write_targets,
        "has_git_changes",
        lambda _root, _path: True,
    )

    offers = write_targets.build_post_write_action_offers(
        target,
        kind=write_targets.WrittenFileKind.SKILL_SOURCE,
        is_new=False,
        xprompt_name="foo",
    )

    assert [offer.kind for offer in offers] == [
        write_targets.PostWriteActionKind.COMMIT_PUSH,
        write_targets.PostWriteActionKind.SKILL_INIT,
    ]
    assert offers[1].cwd == str(tmp_path)
    assert offers[1].command == ("sase", "skill", "init", "--yes")
    # generated_skills.md: --force and --allow-dirty can revert another deployment.
    assert "--force" not in offers[1].command
    assert "--allow-dirty" not in offers[1].command


def test_followup_skill_init_without_dirty_source_skips_commit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = write_targets.XPromptWriteTarget(
        read_path=tmp_path / "repo" / "sase" / "skills" / "foo.md",
        write_path=tmp_path / "repo" / "sase" / "skills" / "foo.md",
        apply_target=None,
        via_chezmoi=False,
    )
    monkeypatch.setattr(write_targets, "get_git_root", lambda _path: str(tmp_path))
    monkeypatch.setattr(
        write_targets,
        "has_git_changes",
        lambda _root, _path: False,
    )

    offers = write_targets.build_post_write_action_offers(
        target,
        kind=write_targets.WrittenFileKind.SKILL_SOURCE,
        is_new=False,
        xprompt_name="foo",
    )

    assert [offer.kind for offer in offers] == [
        write_targets.PostWriteActionKind.SKILL_INIT
    ]
    assert offers[0].cwd == str(tmp_path)
