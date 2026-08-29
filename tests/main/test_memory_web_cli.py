"""Tests for the ``sase memory web`` command group."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.main.memory_handler import handle_memory_command
from sase.main.parser import create_parser

from .memory_handler_helpers import write


def _seed_glossary_web(root: Path) -> None:
    write(
        root / "sase" / "memory" / "glossary.md",
        "---\ntype: core\nweb: true\nroster: inline\ndescription: Test web.\n---\n\nPre.\n",
    )
    write(
        root / "sase" / "memory" / "glossary" / "stitch.md",
        "---\naliases: [commit-ish]\nsummary: A change record.\n---\nStitch body.\n",
    )
    write(
        root / "sase" / "memory" / "glossary" / "patch.md",
        "---\nsummary: A proposed change.\n---\nPatch body.\n",
    )


def test_parser_registers_memory_web_namespace() -> None:
    parser = create_parser()

    list_args = parser.parse_args(["memory", "web", "list"])
    assert list_args.command == "memory"
    assert list_args.memory_subcommand == "web"
    assert list_args.memory_web_subcommand == "list"
    assert list_args.format == "table"

    show_args = parser.parse_args(
        ["memory", "web", "show", "glossary", "stitch", "-b", "-f", "json"]
    )
    assert show_args.memory_web_subcommand == "show"
    assert show_args.web == "glossary"
    assert show_args.pattern == "stitch"
    assert show_args.bodies is True
    assert show_args.format == "json"

    default_args = parser.parse_args(["memory", "web"])
    assert default_args.memory_subcommand == "web"
    assert default_args.memory_web_subcommand == "list"


def test_web_list_json_reports_discovered_webs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    _seed_glossary_web(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)

    with pytest.raises(SystemExit) as exc:
        handle_memory_command(
            create_parser().parse_args(["memory", "web", "list", "-f", "json"])
        )
    assert exc.value.code == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "webs": [
            {
                "web": "glossary",
                "scope": "project",
                "strand_count": 2,
                "description": "Test web.",
            }
        ]
    }


def test_web_show_json_lists_strand_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    _seed_glossary_web(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)

    with pytest.raises(SystemExit) as exc:
        handle_memory_command(
            create_parser().parse_args(
                ["memory", "web", "show", "glossary", "-f", "json"]
            )
        )
    assert exc.value.code == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["web"] == "glossary"
    slugs = {entry["slug"] for entry in payload["strands"]}
    assert slugs == {"stitch", "patch"}
    assert all("body" not in entry for entry in payload["strands"])
    assert all("reference_slugs" in entry for entry in payload["strands"])


def test_web_show_bodies_extends_pattern_matching_into_body_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    _seed_glossary_web(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)

    with pytest.raises(SystemExit) as exc:
        handle_memory_command(
            create_parser().parse_args(
                ["memory", "web", "show", "glossary", "Stitch body", "-f", "json"]
            )
        )
    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out)["strands"] == []

    with pytest.raises(SystemExit) as exc:
        handle_memory_command(
            create_parser().parse_args(
                ["memory", "web", "show", "glossary", "Stitch body", "-b", "-f", "json"]
            )
        )
    assert exc.value.code == 0

    payload = json.loads(capsys.readouterr().out)
    (entry,) = payload["strands"]
    assert entry["slug"] == "stitch"
    assert payload["pattern"] == "Stitch body"


def test_web_show_unknown_web_exits_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)

    with pytest.raises(SystemExit) as exc:
        handle_memory_command(
            create_parser().parse_args(["memory", "web", "show", "bogus"])
        )

    assert exc.value.code == 1
    assert "unknown memory web" in capsys.readouterr().err
