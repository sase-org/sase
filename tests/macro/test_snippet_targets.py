"""Snippet destination resolution and collision index."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from sase.macro import snippet_targets, write_targets
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.macro.snippet_targets import (
    SnippetConfigLocation,
    load_snippet_config_locations,
    load_snippet_template,
    resolve_snippet_save_target,
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


def _write_snippet_config(path: Path, snippets: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ace": {"snippets": snippets}}
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")


def test_load_snippet_template_returns_plain_template(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {"todo": "TODO($1): $0"})

    assert load_snippet_template(config, "todo") == "TODO($1): $0"


def test_load_snippet_config_locations_uses_named_project_not_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    _set_dirs(monkeypatch, home, use_chezmoi=False)
    cwd_root = tmp_path / "cwd_project"
    named_root = tmp_path / "named_project"
    cwd_root.mkdir()
    named_root.mkdir()
    (cwd_root / ".git").mkdir()
    (named_root / ".git").mkdir()
    record = ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name="gh_named__app",
        project_dir="/tmp/projects/gh_named__app",
        project_file="/tmp/projects/gh_named__app/gh_named__app.sase",
        archive_file=None,
        workspace_dir=str(named_root),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=["named"],
        warnings=[],
        parse_warnings=[],
        display_name="named",
    )
    monkeypatch.setattr(
        "sase.macro.glossary_catalog.list_project_records",
        lambda *_a, **_k: [record],
    )
    monkeypatch.chdir(cwd_root)

    locations = load_snippet_config_locations("named")

    project_path = locations[-1].path
    assert project_path.endswith("named_project/sase/sase.yml")
    assert "cwd_project" not in project_path
