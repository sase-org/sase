"""List, show, and stats coverage for ``sase prompt``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

import sase.prompt.cli_list as cli_list
from sase.prompt.cli_list import handle_prompt_list
from sase.prompt.cli_show import handle_prompt_show
from sase.prompt.cli_stats import handle_prompt_stats

from ._helpers import _entry, _prompt_id, _seed


def test_list_json_has_stable_shape_and_excludes_cancelled(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(
        _entry("launched prompt one", "260603_000000"),
        _entry("cancelled prompt two", "260605_000000", cancelled=True),
    )

    handle_prompt_list(
        argparse.Namespace(all=False, cancelled=False, query=None, limit=20, json=True)
    )

    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert list(payload[0].keys()) == [
        "id",
        "timestamp",
        "last_used",
        "cancelled",
        "text_preview",
        "text_chars",
        "text_sha256",
    ]
    assert payload[0]["id"] == _prompt_id("launched prompt one")
    assert payload[0]["cancelled"] is False


def test_list_never_prints_full_long_prompt(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    long_text = "please " + "x" * 5000
    _seed(_entry(long_text, "260603_000000"))

    handle_prompt_list(
        argparse.Namespace(all=False, cancelled=False, query=None, limit=20, json=False)
    )

    out = capsys.readouterr().out
    assert "x" * 5000 not in out


def test_list_pretty_humanizes_project_refs(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "#gh:gh_acme__widgets Fix parser"
    _seed(_entry(text, "260603_000000"))
    monkeypatch.setattr(
        cli_list,
        "humanize_vcs_refs_in_text",
        lambda value: value.replace("gh_acme__widgets", "widgets"),
    )

    handle_prompt_list(
        argparse.Namespace(all=False, cancelled=False, query=None, limit=20, json=False)
    )

    out = capsys.readouterr().out
    assert "gh:widgets" in out
    assert "gh_acme__widgets" not in out


def test_show_raw_is_byte_exact(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "refactor the parser module to be cleaner"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_show(argparse.Namespace(id=_prompt_id(text), format="raw"))

    # Exact text, no added or stripped trailing newline.
    assert capsys.readouterr().out == text


def test_show_raw_preserves_existing_trailing_newline(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "prompt with trailing newline\n"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_show(argparse.Namespace(id=_prompt_id(text), format="raw"))

    assert capsys.readouterr().out == text


def test_show_markdown_has_metadata_header_and_body(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "do the important thing"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_show(argparse.Namespace(id=_prompt_id(text), format="markdown"))

    out = capsys.readouterr().out
    assert f"# Prompt {_prompt_id(text)}" in out
    assert "- cancelled: false" in out
    assert text in out


def test_show_json_includes_full_text(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "do the important thing"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_show(argparse.Namespace(id=_prompt_id(text), format="json"))

    payload = json.loads(capsys.readouterr().out)
    assert payload["text"] == text
    assert payload["id"] == _prompt_id(text)


def test_show_markdown_warms_tag_catalog_from_cold_cache(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``sase prompt show`` loads the tag catalog so bodies tagify.

    Fresh processes start with a cold catalog snapshot, which made CLI
    surfaces print ``#<workflow>:<key>`` instead of ``+<name>``.
    """
    import sase.project_tags.catalog as tag_catalog

    monkeypatch.setattr(tag_catalog, "_CATALOG_CACHE", None)
    text = "do the important thing"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_show(argparse.Namespace(id=_prompt_id(text), format="markdown"))

    assert tag_catalog._CATALOG_CACHE is not None
    assert text in capsys.readouterr().out


def _seed_demo_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Create a real ``demo`` project in the isolated SASE home.

    Only provider detection is stubbed (a plugin boundary): project
    listing, display names, and the tag catalog all read the real spec
    file, so the CLI warms them from a cold cache like a fresh process.
    """
    from sase.core.paths import sase_projects_dir
    import sase.workspace_provider as workspace_provider

    spec_dir = sase_projects_dir() / "demo"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "demo.sase").write_text(
        "PROJECT_NAME: demo\n"
        f"WORKSPACE_DIR: {tmp_path / 'demo-ws'}\n"
        "NAME: Demo\n"
        "STATUS: Ready\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        workspace_provider, "detect_workflow_type", lambda _project_file: "git"
    )


def test_show_markdown_tagifies_stored_ref_from_cold_cache(
    history_file: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end tagify from a cold catalog: stored ``#`` prints ``+``."""
    import sase.project_tags.catalog as tag_catalog

    _seed_demo_project(tmp_path, monkeypatch)
    monkeypatch.setattr(tag_catalog, "_CATALOG_CACHE", None)
    text = "#git:demo do the important thing"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_show(argparse.Namespace(id=_prompt_id(text), format="markdown"))

    out = capsys.readouterr().out
    assert "+demo" in out
    assert "#git:demo" not in out


def test_list_pretty_tagifies_stored_ref_from_cold_cache(
    history_file: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pretty list renderer tagifies from a cold catalog like show does."""
    import sase.project_tags.catalog as tag_catalog

    _seed_demo_project(tmp_path, monkeypatch)
    monkeypatch.setattr(tag_catalog, "_CATALOG_CACHE", None)
    text = "#git:demo Fix parser"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_list(
        argparse.Namespace(all=False, cancelled=False, query=None, limit=20, json=False)
    )

    out = capsys.readouterr().out
    assert "+demo" in out
    assert "#git:demo" not in out


def test_show_raw_and_json_skip_tag_catalog(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Raw and JSON output never tagify, so they skip the catalog load."""
    import sase.project_tags as project_tags_package

    def _boom() -> object:
        raise AssertionError("raw/json show must not warm the tag catalog")

    monkeypatch.setattr(project_tags_package, "ensure_project_tag_catalog", _boom)
    text = "#git:demo do the important thing"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_show(argparse.Namespace(id=_prompt_id(text), format="raw"))
    assert capsys.readouterr().out == text

    handle_prompt_show(argparse.Namespace(id=_prompt_id(text), format="json"))
    assert json.loads(capsys.readouterr().out)["text"] == text


def test_show_unknown_selector_exits_nonzero(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("a stored prompt here", "260603_000000"))

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_show(argparse.Namespace(id="ph_ffffffffffff", format="raw"))

    assert exc_info.value.code == 2
    assert "No prompt matches selector" in capsys.readouterr().err


def test_stats_json_has_stable_shape(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(
        _entry("aaaa bbbb", "260601_000000"),
        _entry("cccc dddd eeee", "260603_000000"),
    )

    handle_prompt_stats(argparse.Namespace(json=True))

    payload = json.loads(capsys.readouterr().out)
    assert set(payload.keys()) == {
        "path",
        "exists",
        "size_bytes",
        "shard_count",
        "total",
        "launched",
        "cancelled",
        "oldest_last_used",
        "newest_last_used",
        "length_percentiles",
        "largest",
        "top_chips",
    }
    assert payload["total"] == 2
    assert payload["shard_count"] == 1
    assert set(payload["length_percentiles"]) == {"p50", "p90", "p99", "max"}
