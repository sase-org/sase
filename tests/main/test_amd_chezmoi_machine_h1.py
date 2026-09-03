"""Unit coverage for chezmoi machine-overlay H1 title resolution."""

from __future__ import annotations

from pathlib import Path

from sase.amd._config import resolve_chezmoi_machine_h1_titles
from tests.main.init_memory_handler_helpers import write


def _ignore_text() -> str:
    return (
        "tags\n"
        '{{ if ne .chezmoi.fqdnHostname "bbugyi.c.googlers.com" }}\n'
        ".config/sase/sase_work.yml\n"
        "{{ end }}\n"
        '{{ if ne .chezmoi.hostname "athena" }}\n'
        ".config/sase/sase_athena.yml\n"
        "{{ end }}\n"
        '{{ if ne .chezmoi.hostname "Kellys-MBP" }}\n'
        ".config/sase/sase_kellys_mbp.yml\n"
        "{{ end }}\n"
        '{{ if ne .chezmoi.hostname "apollo" }}\n'
        ".config/sase/sase_apollo.yml\n"
        "{{ end }}\n"
    )


def _write_overlay(
    root: Path,
    machine_name: str,
    *,
    title: str | None = None,
) -> None:
    body = f"id:\n  username: bbugyi200\n  machine_name: {machine_name}\n"
    if title is not None:
        body += f'\nmemory:\n  h1_title: "{title}"\n'
    write(root / "dot_config" / "sase" / f"sase_{machine_name}.yml", body)


def test_resolve_chezmoi_machine_h1_titles_maps_guards(tmp_path: Path) -> None:
    root = tmp_path / "home"
    write(root / "dot_config" / "sase" / "sase.yml", "use_chezmoi: true\n")
    _write_overlay(root, "apollo", title="apollo title")
    _write_overlay(root, "athena", title="athena title")
    _write_overlay(root, "kellys_mbp")
    write(root / ".chezmoiignore", _ignore_text())

    result = resolve_chezmoi_machine_h1_titles(root, chezmoi_home_roots=(root,))

    assert result.blockers == ()
    assert result.titles == (
        ("apollo", "apollo title"),
        ("athena", "athena title"),
    )
    assert result.fallback_title == "athena title"


def test_resolve_chezmoi_machine_h1_titles_untriggered_without_overlay_titles(
    tmp_path: Path,
) -> None:
    root = tmp_path / "home"
    write(root / "dot_config" / "sase" / "sase.yml", "use_chezmoi: true\n")
    _write_overlay(root, "apollo")
    write(root / ".chezmoiignore", _ignore_text())

    result = resolve_chezmoi_machine_h1_titles(root, chezmoi_home_roots=(root,))

    assert result.blockers == ()
    assert result.titles == ()


def test_resolve_chezmoi_machine_h1_titles_missing_guard_blocks(
    tmp_path: Path,
) -> None:
    root = tmp_path / "home"
    write(root / "dot_config" / "sase" / "sase.yml", "use_chezmoi: true\n")
    _write_overlay(root, "apollo", title="apollo title")
    write(root / ".chezmoiignore", "tags\n")

    result = resolve_chezmoi_machine_h1_titles(root, chezmoi_home_roots=(root,))

    assert any("hostname guard" in blocker for blocker in result.blockers)
    assert any("sase config init" in blocker for blocker in result.blockers)


def test_resolve_chezmoi_machine_h1_titles_duplicate_hostname_blocks(
    tmp_path: Path,
) -> None:
    root = tmp_path / "home"
    write(root / "dot_config" / "sase" / "sase.yml", "use_chezmoi: true\n")
    _write_overlay(root, "apollo", title="apollo title")
    _write_overlay(root, "athena", title="athena title")
    write(
        root / ".chezmoiignore",
        '{{ if ne .chezmoi.hostname "apollo" }}\n'
        ".config/sase/sase_apollo.yml\n"
        "{{ end }}\n"
        '{{ if ne .chezmoi.hostname "apollo" }}\n'
        ".config/sase/sase_athena.yml\n"
        "{{ end }}\n",
    )

    result = resolve_chezmoi_machine_h1_titles(root, chezmoi_home_roots=(root,))

    assert any("already used" in blocker for blocker in result.blockers)


def test_resolve_chezmoi_machine_h1_titles_skips_non_chezmoi_roots(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    _write_overlay(root, "apollo", title="apollo title")

    result = resolve_chezmoi_machine_h1_titles(root)

    assert result.titles == ()
    assert result.blockers == ()
