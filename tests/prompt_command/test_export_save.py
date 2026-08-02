"""Export and xprompt-save coverage for ``sase prompt``."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.prompt.cli_export import handle_prompt_export, handle_prompt_save

from ._helpers import _entry, _export_ns, _prompt_id, _save_ns, _seed


def test_export_stdout_raw_is_byte_exact(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "export this exact prompt body"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_export(_export_ns(_prompt_id(text)))

    # Default stdout export is a full-text escape hatch: no frontmatter, no
    # added or stripped newline.
    assert capsys.readouterr().out == text


def test_export_stdout_metadata_wraps_in_frontmatter(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "export with provenance metadata"
    _seed(_entry(text, "260603_091500"))

    handle_prompt_export(_export_ns(_prompt_id(text), metadata=True))

    out = capsys.readouterr().out
    assert out.startswith("---\n")
    assert f"id: {_prompt_id(text)}" in out
    assert "sha256:" in out
    assert "last_used:" in out
    assert "cancelled: false" in out
    assert "source: sase prompt history" in out
    assert text in out


def test_export_out_writes_file_and_guards_overwrite(
    history_file: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "export prompt to a chosen file path"
    _seed(_entry(text, "260603_000000"))
    dest = tmp_path / "exported.md"

    handle_prompt_export(_export_ns(_prompt_id(text), out=str(dest)))
    assert dest.read_text(encoding="utf-8") == text + "\n"
    assert _prompt_id(text) in capsys.readouterr().out

    # A second export to the same path fails without --force and never clobbers.
    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_export(_export_ns(_prompt_id(text), out=str(dest)))
    assert exc_info.value.code == 1
    assert "--force" in capsys.readouterr().err

    # --force replaces the file.
    handle_prompt_export(_export_ns(_prompt_id(text), out=str(dest), force=True))
    assert dest.read_text(encoding="utf-8") == text + "\n"


def test_export_sdd_is_retired_and_cannot_write_into_plans(
    history_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    text = "do not forge an archived prompt"
    _seed(_entry(text, "260603_000000"))

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_export(_export_ns(_prompt_id(text), sdd=True))

    assert exc_info.value.code == 2
    error = capsys.readouterr().err
    assert "--sdd is retired" in error
    assert "--out PATH" in error
    assert "sase agent prompts" in error
    assert not list(tmp_path.glob("**/plans/*/prompts/*.md"))
    assert not (tmp_path / "sdd").exists()
    assert not (tmp_path / ".sase" / "sdd").exists()


def test_export_unknown_selector_exits_two(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("a stored prompt to export", "260603_000000"))

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_export(_export_ns("ph_ffffffffffff"))

    assert exc_info.value.code == 2
    assert "No prompt matches selector" in capsys.readouterr().err


def test_save_local_creates_loadable_xprompt(
    history_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.xprompt.loader import load_xprompt_from_file

    monkeypatch.chdir(tmp_path)
    text = "do the important refactor across the parser"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_save(_save_ns(_prompt_id(text), name="fix-parser"))

    dest = tmp_path / "sase" / "xprompts" / "fix-parser.md"
    xprompt = load_xprompt_from_file(dest)
    assert xprompt is not None
    assert xprompt.name == "fix-parser"
    assert text in xprompt.content
    # Default description is the cleaned one-line preview.
    assert xprompt.description == text


def test_save_tag_persists_prompt_tags_and_stays_loadable(
    history_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.xprompt.loader import load_xprompt_from_file

    monkeypatch.chdir(tmp_path)
    text = "review the authentication changes carefully"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_save(
        _save_ns(_prompt_id(text), name="fix-auth-review", tag=["review"])
    )

    dest = tmp_path / "sase" / "xprompts" / "fix-auth-review.md"
    raw = dest.read_text(encoding="utf-8")
    # User tags live under prompt_tags, not the reserved semantic ``tags`` key,
    # so the loader does not raise on free-form labels.
    assert "prompt_tags:" in raw
    assert "review" in raw
    assert "\ntags:" not in raw

    xprompt = load_xprompt_from_file(dest)
    assert xprompt is not None
    assert xprompt.name == "fix-auth-review"
    # Free-form tags must not leak into the semantic tag set.
    assert xprompt.tags == frozenset()


def test_save_global_writes_home_xprompts(
    history_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    text = "save this prompt globally for reuse"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_save(_save_ns(_prompt_id(text), name="global-prompt", global_=True))

    assert (tmp_path / "sase" / "xprompts" / "global-prompt.md").is_file()


def test_save_project_writes_config_dir(
    history_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    text = "save this prompt under a project namespace"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_save(_save_ns(_prompt_id(text), name="proj-prompt", project="bob"))

    dest = tmp_path / "sase" / "xprompts" / "bob" / "proj-prompt.md"
    assert dest.is_file()


def test_save_auto_name_derives_slug(
    history_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    text = "Improve the launcher startup time"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_save(_save_ns(_prompt_id(text)))

    assert (
        tmp_path / "sase" / "xprompts" / "improve-the-launcher-startup-time.md"
    ).is_file()


def test_save_description_override(
    history_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.xprompt.loader import load_xprompt_from_file

    monkeypatch.chdir(tmp_path)
    text = "prompt whose description is overridden"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_save(
        _save_ns(_prompt_id(text), name="custom", description="My summary")
    )

    xprompt = load_xprompt_from_file(tmp_path / "sase" / "xprompts" / "custom.md")
    assert xprompt is not None
    assert xprompt.description == "My summary"


def test_save_guards_overwrite(
    history_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    text = "prompt saved twice to the same name"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_save(_save_ns(_prompt_id(text), name="dup"))

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_save(_save_ns(_prompt_id(text), name="dup"))
    assert exc_info.value.code == 1
    assert "--force" in capsys.readouterr().err

    # --force replaces the existing file.
    handle_prompt_save(_save_ns(_prompt_id(text), name="dup", force=True))
    assert (tmp_path / "sase" / "xprompts" / "dup.md").is_file()


def test_save_global_and_project_are_mutually_exclusive(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "prompt with conflicting destinations"
    _seed(_entry(text, "260603_000000"))

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_save(
            _save_ns(_prompt_id(text), name="x", global_=True, project="bob")
        )

    assert exc_info.value.code == 2
    assert "only one" in capsys.readouterr().err


def test_save_rejects_name_with_path_separator(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "prompt with an unsafe name argument"
    _seed(_entry(text, "260603_000000"))

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_save(_save_ns(_prompt_id(text), name="../escape"))

    assert exc_info.value.code == 2
    assert "invalid name" in capsys.readouterr().err


def test_save_unknown_selector_exits_two(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("a stored prompt to save", "260603_000000"))

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_save(_save_ns("ph_ffffffffffff"))

    assert exc_info.value.code == 2
    assert "No prompt matches selector" in capsys.readouterr().err
