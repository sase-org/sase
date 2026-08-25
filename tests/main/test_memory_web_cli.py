"""Tests for the ``sase memory web`` command group."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from sase.content_layout import resolve_project_config_write_path
from sase.main.memory_handler import handle_memory_command
from sase.main.init_memory.glossary import load_project_glossary_terms
from sase.main.init_memory.root_rendering_notes import (
    generated_glossary_memory_content,
    render_generated_glossary_memory_body,
)
from sase.main.parser import create_parser
from sase.markdown_width import markdown_print_width
from sase.memory.web import (
    END_MARKER,
    START_MARKER,
    discover_memory_webs,
    validate_memory_webs,
)

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

    migrate_args = parser.parse_args(
        ["memory", "web", "migrate", "glossary", "-n", "-p", "demo"]
    )
    assert migrate_args.memory_web_subcommand == "migrate"
    assert migrate_args.web == "glossary"
    assert migrate_args.dry_run is True
    assert migrate_args.project == "demo"


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
                "rendering_type": "core",
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


def _seed_config_glossary(root: Path, body: str | None = None) -> Path:
    config_path = resolve_project_config_write_path(root)
    write(
        config_path,
        body
        or """# keep this comment
timezone: UTC
memory:
  h1_title: Demo
  glossary:
    Agent Clan:
      aliases:
        - agent clans
        - clan
      definition: >-
        A named, rootless container.
    Proc:
      aliases:
        - procs
        - background task
        - background tasks
      definition: >-
        A background task.
""",
    )
    return config_path


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _run_memory_command(argv: list[str]) -> int:
    with pytest.raises(SystemExit) as exc:
        handle_memory_command(create_parser().parse_args(argv))
    assert isinstance(exc.value.code, int)
    return exc.value.code


def _generated_glossary_body(config_path: Path, root: Path) -> str:
    terms, errors = load_project_glossary_terms(config_path, root)
    assert errors == ()
    assert terms is not None
    body, error = render_generated_glossary_memory_body(terms)
    assert error is None
    assert body is not None
    return body


def _generated_roster(config_path: Path, root: Path) -> str:
    body = _generated_glossary_body(config_path, root)
    return body[body.index("**GLOSSARY TERMS:**") :].strip()


def _managed_roster(descriptor: str) -> str:
    start = descriptor.index(START_MARKER) + len(START_MARKER)
    end = descriptor.index(END_MARKER, start)
    return descriptor[start:end].strip()


def test_web_migrate_writes_strands_descriptor_and_removes_config_glossary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = _seed_config_glossary(tmp_path)
    expected_roster = _generated_roster(config_path, tmp_path)
    body = _generated_glossary_body(config_path, tmp_path)
    write(
        tmp_path / "sase" / "memory" / "glossary.md",
        generated_glossary_memory_content(body),
    )
    monkeypatch.chdir(tmp_path)

    assert _run_memory_command(["memory", "web", "migrate", "glossary"]) == 0

    output = capsys.readouterr().out
    assert "migrate glossary: 2 strands" in output
    assert f"write: {tmp_path / 'sase' / 'memory' / 'glossary.md'}" in output
    assert f"config: {config_path} (remove memory.glossary)" in output
    assert "follow-up: run `sase memory init`" in output

    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert loaded["memory"] == {"h1_title": "Demo"}
    assert loaded["timezone"] == "UTC"

    descriptor = (tmp_path / "sase" / "memory" / "glossary.md").read_text(
        encoding="utf-8"
    )
    assert "web: true" in descriptor
    assert "strand_noun: term" in descriptor
    assert "closure: mentions" in descriptor
    assert "sase_generated:" not in descriptor
    assert "sase memory read glossary:<term>" in descriptor
    assert "sase glossary read" not in descriptor
    assert _managed_roster(descriptor) == expected_roster

    for line in descriptor.splitlines():
        assert len(line) <= markdown_print_width(), line

    agent_clan = tmp_path / "sase" / "memory" / "glossary" / "agent-clan.md"
    proc = tmp_path / "sase" / "memory" / "glossary" / "proc.md"
    assert agent_clan.read_text(encoding="utf-8").endswith(
        "\n\nA named, rootless container.\n"
    )
    assert (
        "aliases:\n  - procs\n  - background task\n  - background tasks\n"
    ) in proc.read_text(encoding="utf-8")

    discovery = discover_memory_webs(tmp_path)
    assert validate_memory_webs(discovery).blockers == ()
    (web,) = discovery.webs
    assert web.slug == "glossary"
    assert len(web.strands) == 2


def test_web_migrate_dry_run_reports_same_plan_and_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_config_glossary(tmp_path)
    monkeypatch.chdir(tmp_path)
    before = _snapshot_tree(tmp_path)

    assert _run_memory_command(["memory", "web", "migrate", "glossary", "-n"]) == 0

    dry_report = capsys.readouterr().out
    assert before == _snapshot_tree(tmp_path)

    assert _run_memory_command(["memory", "web", "migrate", "glossary"]) == 0

    assert capsys.readouterr().out == dry_report


def test_web_migrate_second_run_exits_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_config_glossary(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert _run_memory_command(["memory", "web", "migrate", "glossary"]) == 0
    capsys.readouterr()

    assert _run_memory_command(["memory", "web", "migrate", "glossary"]) == 1

    assert "nothing to migrate" in capsys.readouterr().err


def test_web_migrate_slug_collision_fails_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_config_glossary(
        tmp_path,
        """
memory:
  glossary:
    Agent Hood:
      definition: A group of agents.
    Agent-Hood:
      definition: Another group of agents.
""",
    )
    monkeypatch.chdir(tmp_path)
    before = _snapshot_tree(tmp_path)

    assert _run_memory_command(["memory", "web", "migrate", "glossary"]) == 1

    assert before == _snapshot_tree(tmp_path)
    assert "collide on strand slug 'agent-hood'" in capsys.readouterr().err


def test_web_migrate_only_supports_glossary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_config_glossary(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert _run_memory_command(["memory", "web", "migrate", "decisions"]) == 1

    assert "only the config glossary can be migrated" in capsys.readouterr().err
