"""Snippet destination resolution and collision index."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from sase.xprompt import snippet_targets, write_targets
from sase.xprompt.snippet_targets import (
    SnippetConfigLocation,
    SnippetSaveTarget,
    load_snippet_template,
    resolve_snippet_save_target,
    snippet_collision,
)


def _set_dirs(monkeypatch, home: Path, *, use_chezmoi: bool) -> tuple[Path, Path]:
    config_dir = home / ".config" / "sase"
    chezmoi_home = home / ".local" / "share" / "chezmoi" / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(snippet_targets, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(snippet_targets, "CHEZMOI_HOME", chezmoi_home)
    monkeypatch.setattr(snippet_targets, "get_use_chezmoi", lambda: use_chezmoi)
    monkeypatch.setattr(write_targets, "CHEZMOI_HOME", chezmoi_home)
    monkeypatch.setattr(write_targets, "get_use_chezmoi", lambda: use_chezmoi)
    return config_dir, chezmoi_home


# --- resolve_snippet_save_target ------------------------------------------


def test_unset_configured_falls_back_to_default(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    config_dir, _ = _set_dirs(monkeypatch, home, use_chezmoi=False)

    target = resolve_snippet_save_target("")

    assert target.source == "default"
    assert target.fallback_reason is None
    assert target.read_path == config_dir / "sase.yml"
    assert target.write_path == config_dir / "sase.yml"
    assert target.via_chezmoi is False


def test_none_configured_falls_back_to_default(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    config_dir, _ = _set_dirs(monkeypatch, home, use_chezmoi=False)

    target = resolve_snippet_save_target(None)

    assert target.source == "default"
    assert target.write_path == config_dir / "sase.yml"


def test_absolute_configured_path_is_used_when_writable(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    _set_dirs(monkeypatch, home, use_chezmoi=False)
    custom = tmp_path / "custom" / "snippets.yml"
    custom.parent.mkdir(parents=True)

    target = resolve_snippet_save_target(str(custom))

    assert target.source == "configured"
    assert target.fallback_reason is None
    assert target.write_path == custom


def test_relative_configured_path_resolves_against_config_dir(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    config_dir, _ = _set_dirs(monkeypatch, home, use_chezmoi=False)
    config_dir.mkdir(parents=True)

    target = resolve_snippet_save_target("sase_snippets.yml")

    assert target.source == "configured"
    assert target.write_path == config_dir / "sase_snippets.yml"


def test_wrong_suffix_falls_back_to_default(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    config_dir, _ = _set_dirs(monkeypatch, home, use_chezmoi=False)

    target = resolve_snippet_save_target(str(tmp_path / "snippets.txt"))

    assert target.source == "default"
    assert target.fallback_reason == "must be a .yml or .yaml file"
    assert target.write_path == config_dir / "sase.yml"


def test_unwritable_parent_falls_back_to_default(tmp_path: Path, monkeypatch) -> None:
    if os.geteuid() == 0:
        pytest.skip("permission tests are not meaningful as root")
    home = tmp_path / "home"
    _set_dirs(monkeypatch, home, use_chezmoi=False)
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        target = resolve_snippet_save_target(str(locked / "snippets.yml"))
    finally:
        locked.chmod(0o700)

    assert target.source == "default"
    assert target.fallback_reason == "directory is not writable"


def test_configured_path_with_invalid_yaml_falls_back(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    _set_dirs(monkeypatch, home, use_chezmoi=False)
    bad = tmp_path / "bad.yml"
    bad.write_text("foo: [unterminated\n  - bar\n", encoding="utf-8")

    target = resolve_snippet_save_target(str(bad))

    assert target.source == "default"
    assert target.fallback_reason == "invalid YAML"


def test_configured_path_that_is_not_a_mapping_falls_back(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    _set_dirs(monkeypatch, home, use_chezmoi=False)
    not_mapping = tmp_path / "list.yml"
    not_mapping.write_text("- one\n- two\n", encoding="utf-8")

    target = resolve_snippet_save_target(str(not_mapping))

    assert target.source == "default"
    assert target.fallback_reason == "not a YAML mapping"


def test_chezmoi_off_uses_plain_config_dir_default(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    config_dir, _ = _set_dirs(monkeypatch, home, use_chezmoi=False)

    target = resolve_snippet_save_target("")

    assert target.write_path == config_dir / "sase.yml"
    assert target.via_chezmoi is False
    assert target.apply_target is None


def test_chezmoi_on_configured_home_path_remaps_when_source_present(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    config_dir, chezmoi_home = _set_dirs(monkeypatch, home, use_chezmoi=True)
    home_path = config_dir / "custom_snippets.yml"
    source_path = chezmoi_home / "dot_config" / "sase" / "custom_snippets.yml"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("ace:\n  snippets: {}\n", encoding="utf-8")

    target = resolve_snippet_save_target(str(home_path))

    assert target.source == "configured"
    assert target.read_path == home_path
    assert target.write_path == source_path
    assert target.apply_target == home_path
    assert target.via_chezmoi is True


def test_chezmoi_on_configured_home_path_stays_when_source_missing(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    config_dir, _ = _set_dirs(monkeypatch, home, use_chezmoi=True)
    home_path = config_dir / "custom_snippets.yml"

    target = resolve_snippet_save_target(str(home_path))

    assert target.source == "configured"
    assert target.write_path == home_path
    assert target.apply_target is None
    assert target.via_chezmoi is False


def test_configured_path_already_inside_chezmoi_source_is_not_remapped(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    _, chezmoi_home = _set_dirs(monkeypatch, home, use_chezmoi=True)
    source_dir = chezmoi_home / "dot_config" / "sase"
    source_dir.mkdir(parents=True)
    configured = source_dir / "custom.yml"

    target = resolve_snippet_save_target(str(configured))

    assert target.write_path == configured
    assert target.via_chezmoi is False
    assert target.apply_target is None


def test_default_matches_chezmoi_home_when_chezmoi_enabled(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    _, chezmoi_home = _set_dirs(monkeypatch, home, use_chezmoi=True)

    target = resolve_snippet_save_target("")

    assert target.source == "default"
    assert target.write_path == chezmoi_home / "dot_config" / "sase" / "sase.yml"


# --- snippet_collision ------------------------------------------------------


def _write_snippet_config(path: Path, snippets: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ace": {"snippets": snippets}}
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")


def _target_for(path: Path) -> SnippetSaveTarget:
    return SnippetSaveTarget(
        read_path=path,
        write_path=path,
        apply_target=None,
        via_chezmoi=False,
        display_path=str(path),
        source="configured",
        fallback_reason=None,
    )


def test_snippet_collision_reports_no_collision_for_new_trigger(
    tmp_path: Path,
) -> None:
    dest = tmp_path / "sase.yml"
    _write_snippet_config(dest, {})
    other = tmp_path / "sase_extra.yml"
    _write_snippet_config(other, {})
    locations = [
        SnippetConfigLocation("User sase.yml", str(dest), str(dest)),
        SnippetConfigLocation("User sase_extra.yml", str(other), str(other)),
    ]

    collision = snippet_collision(
        "todo", _target_for(dest), locations=locations, derived={}
    )

    assert collision.matches == ()
    assert collision.derived_from is None
    assert collision.winner_path == str(dest)
    assert collision.shadowed_by is None
    assert collision.shadows is None


def test_snippet_collision_in_destination(tmp_path: Path) -> None:
    dest = tmp_path / "sase.yml"
    _write_snippet_config(dest, {"todo": "TODO($1)"})
    locations = [SnippetConfigLocation("User sase.yml", str(dest), str(dest))]

    collision = snippet_collision(
        "todo", _target_for(dest), locations=locations, derived={}
    )

    assert len(collision.matches) == 1
    assert collision.matches[0].is_destination is True
    assert collision.winner_path == str(dest)
    assert collision.shadowed_by is None
    assert collision.shadows is None


def test_snippet_collision_shadowed_by_higher_precedence_file(
    tmp_path: Path,
) -> None:
    higher = tmp_path / "sase.yml"
    lower = tmp_path / "project_sase.yml"
    _write_snippet_config(higher, {"todo": "HIGH"})
    _write_snippet_config(lower, {})
    locations = [
        SnippetConfigLocation("User sase.yml", str(higher), str(higher)),
        SnippetConfigLocation("Project sase/sase.yml", str(lower), str(lower)),
    ]

    collision = snippet_collision(
        "todo", _target_for(lower), locations=locations, derived={}
    )

    assert collision.shadowed_by == str(higher)
    assert collision.winner_path == str(higher)
    assert collision.shadows is None
    assert len(collision.matches) == 1
    assert collision.matches[0].location_path == str(higher)
    assert collision.matches[0].is_destination is False


def test_snippet_collision_shadows_lower_precedence_file(tmp_path: Path) -> None:
    higher = tmp_path / "sase.yml"
    lower = tmp_path / "project_sase.yml"
    _write_snippet_config(higher, {})
    _write_snippet_config(lower, {"todo": "LOW"})
    locations = [
        SnippetConfigLocation("User sase.yml", str(higher), str(higher)),
        SnippetConfigLocation("Project sase/sase.yml", str(lower), str(lower)),
    ]

    collision = snippet_collision(
        "todo", _target_for(higher), locations=locations, derived={}
    )

    assert collision.shadows == str(lower)
    assert collision.shadowed_by is None
    assert collision.winner_path == str(higher)
    assert len(collision.matches) == 1
    assert collision.matches[0].location_path == str(lower)
    assert collision.matches[0].is_destination is False


def test_snippet_collision_reports_derived_from(tmp_path: Path) -> None:
    dest = tmp_path / "sase.yml"
    _write_snippet_config(dest, {})
    locations = [SnippetConfigLocation("User sase.yml", str(dest), str(dest))]

    collision = snippet_collision(
        "todo",
        _target_for(dest),
        locations=locations,
        derived={"todo": "#todo_template"},
    )

    assert collision.derived_from == "#todo_template"
    assert collision.matches == ()


def test_snippet_collision_reports_derived_and_explicit(tmp_path: Path) -> None:
    dest = tmp_path / "sase.yml"
    _write_snippet_config(dest, {"todo": "explicit"})
    locations = [SnippetConfigLocation("User sase.yml", str(dest), str(dest))]

    collision = snippet_collision(
        "todo",
        _target_for(dest),
        locations=locations,
        derived={"todo": "#todo_template"},
    )

    assert collision.derived_from == "#todo_template"
    assert len(collision.matches) == 1
    assert collision.matches[0].is_destination is True


def test_snippet_collision_treats_out_of_discovery_destination_as_highest_precedence(
    tmp_path: Path,
) -> None:
    other = tmp_path / "sase.yml"
    _write_snippet_config(other, {"todo": "OTHER"})
    custom = tmp_path / "custom.yml"
    _write_snippet_config(custom, {})
    locations = [SnippetConfigLocation("User sase.yml", str(other), str(other))]

    collision = snippet_collision(
        "todo", _target_for(custom), locations=locations, derived={}
    )

    assert collision.shadowed_by is None
    assert collision.shadows == str(other)
    assert collision.winner_path == str(custom)


def test_load_snippet_template_returns_plain_template(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {"todo": "TODO($1): $0"})

    assert load_snippet_template(config, "todo") == "TODO($1): $0"
