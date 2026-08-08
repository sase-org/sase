"""XPrompt write-target resolution."""

from __future__ import annotations

from pathlib import Path

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
