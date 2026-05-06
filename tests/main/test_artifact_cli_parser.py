"""Tests for the ``sase artifact`` CLI parser and dispatch glue."""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

import pytest

from sase.main import artifact_handler, entry
from sase.main.parser import create_parser

from tests.main.artifact_cli_helpers import artifact_parser, subparser_action


def test_artifact_parser_registers_required_subcommands() -> None:
    parser = artifact_parser()

    assert set(subparser_action(parser).choices) == {
        "add",
        "remove",
        "list",
        "show",
        "graph",
        "rebuild",
        "sync",
        "doctor",
    }


def test_artifact_options_all_have_short_forms() -> None:
    parser = artifact_parser()

    for name, subcommand_parser in subparser_action(parser).choices.items():
        for action in subcommand_parser._actions:
            if not action.option_strings:
                continue
            if action.dest == "help":
                continue
            assert any(
                option.startswith("-") and not option.startswith("--")
                for option in action.option_strings
            ), f"sase artifact {name} {action.dest}"


@pytest.mark.parametrize(
    "argv",
    [
        ["artifact", "--help"],
        ["artifact", "add", "--help"],
        ["artifact", "remove", "--help"],
        ["artifact", "list", "--help"],
        ["artifact", "show", "--help"],
        ["artifact", "graph", "--help"],
        ["artifact", "rebuild", "--help"],
        ["artifact", "sync", "--help"],
        ["artifact", "doctor", "--help"],
    ],
)
def test_artifact_help_paths_are_parser_valid(argv: list[str]) -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(argv)

    assert exc_info.value.code == 0


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (
            [
                "artifact",
                "add",
                "-i",
                "/tmp/artifacts.sqlite",
                "-a",
                "note:1",
                "-k",
                "note",
                "-t",
                "Title",
                "-s",
                "Subtitle",
                "-q",
                "search text",
                "-m",
                "{}",
                "-p",
                "{}",
                "-P",
                "summary",
                "-j",
                "-l",
                "parent|note:1|/",
                "-L",
                '{"link_type": "related", "source_id": "note:1", "target_id": "/"}',
            ],
            {
                "artifact_subcommand": "add",
                "index": "/tmp/artifacts.sqlite",
                "artifact_id": "note:1",
                "kind": "note",
                "title": "Title",
                "subtitle": "Subtitle",
                "search_text": "search text",
                "metadata_json": "{}",
                "payload_json": "{}",
                "payload_type": "summary",
                "json": True,
                "link": ["parent|note:1|/"],
                "link_json": [
                    '{"link_type": "related", "source_id": "note:1", "target_id": "/"}'
                ],
            },
        ),
        (
            [
                "artifact",
                "remove",
                "-i",
                "/tmp/artifacts.sqlite",
                "-a",
                "note:1",
                "-l",
                "link-1",
                "-T",
                "parent",
                "-S",
                "note:1",
                "-D",
                "/",
                "-p",
                "manual",
                "-r",
                "obsolete",
                "-j",
            ],
            {
                "artifact_subcommand": "remove",
                "index": "/tmp/artifacts.sqlite",
                "artifact_id": "note:1",
                "link_id": "link-1",
                "link_type": "parent",
                "source_id": "note:1",
                "target_id": "/",
                "provenance": "manual",
                "reason": "obsolete",
                "json": True,
            },
        ),
        (
            [
                "artifact",
                "list",
                "-i",
                "/tmp/artifacts.sqlite",
                "-k",
                "file",
                "-F",
                "plan",
                "-F",
                "diff",
                "-L",
                "parent",
                "-P",
                "derived",
                "-s",
                "directory",
                "-S",
                "/tmp",
                "-q",
                "needle",
                "-r",
                "/",
                "-u",
                "-l",
                "10",
                "-o",
                "5",
                "-j",
            ],
            {
                "artifact_subcommand": "list",
                "index": "/tmp/artifacts.sqlite",
                "kind": ["file"],
                "file_type": ["plan", "diff"],
                "link_type": ["parent"],
                "provenance": "derived",
                "source_kind": ["directory"],
                "source_id": ["/tmp"],
                "text": "needle",
                "root_id": "/",
                "include_tombstoned": True,
                "limit": 10,
                "offset": 5,
                "json": True,
            },
        ),
        (
            ["artifact", "show", "-i", "/tmp/artifacts.sqlite", "-a", "note:1", "-j"],
            {
                "artifact_subcommand": "show",
                "index": "/tmp/artifacts.sqlite",
                "artifact_id": "note:1",
                "json": True,
            },
        ),
        (
            [
                "artifact",
                "graph",
                "-i",
                "/tmp/artifacts.sqlite",
                "-a",
                "note:1",
                "-d",
                "3",
                "-L",
                "parent",
                "-I",
                "-O",
                "-F",
                "-l",
                "20",
                "-f",
                "text",
                "-j",
            ],
            {
                "artifact_subcommand": "graph",
                "index": "/tmp/artifacts.sqlite",
                "artifact_id": "note:1",
                "depth": 3,
                "link_type": ["parent"],
                "include_inbound": True,
                "include_outbound": True,
                "full": True,
                "limit": 20,
                "format": "text",
                "json": True,
            },
        ),
        (
            [
                "artifact",
                "rebuild",
                "-i",
                "/tmp/artifacts.sqlite",
                "-p",
                "/projects",
                "-w",
                "/workspace",
                "-b",
                "/beads",
                "-S",
                "directory",
                "-X",
                "agent_artifact",
                "-t",
                "/workspace/file.py",
                "-a",
                "/artifacts/run",
                "-c",
                "mark",
                "-j",
            ],
            {
                "artifact_subcommand": "rebuild",
                "index": "/tmp/artifacts.sqlite",
                "projects_root": "/projects",
                "workspace_root": "/workspace",
                "beads_dir": "/beads",
                "include_source": ["directory"],
                "exclude_source": ["agent_artifact"],
                "target_path": "/workspace/file.py",
                "artifact_dir": "/artifacts/run",
                "stale_cleanup": "mark",
                "json": True,
            },
        ),
        (
            [
                "artifact",
                "sync",
                "-i",
                "/tmp/artifacts.sqlite",
                "-p",
                "/projects",
                "-w",
                "/workspace",
                "-b",
                "/beads",
                "-S",
                "directory",
                "-X",
                "agent_artifact",
                "-t",
                "/workspace/file.py",
                "-a",
                "/artifacts/run",
                "-c",
                "mark",
                "-j",
            ],
            {
                "artifact_subcommand": "sync",
                "index": "/tmp/artifacts.sqlite",
                "projects_root": "/projects",
                "workspace_root": "/workspace",
                "beads_dir": "/beads",
                "include_source": ["directory"],
                "exclude_source": ["agent_artifact"],
                "target_path": "/workspace/file.py",
                "artifact_dir": "/artifacts/run",
                "stale_cleanup": "mark",
                "json": True,
            },
        ),
        (
            ["artifact", "doctor", "-i", "/tmp/artifacts.sqlite", "-j"],
            {
                "artifact_subcommand": "doctor",
                "index": "/tmp/artifacts.sqlite",
                "json": True,
            },
        ),
    ],
)
def test_artifact_parser_accepts_every_short_option(
    argv: list[str],
    expected: dict[str, object],
) -> None:
    args = create_parser().parse_args(argv)

    for key, value in expected.items():
        assert getattr(args, key) == value


def test_artifact_parser_rejects_unsupported_graph_format() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["artifact", "graph", "-f", "yaml"])

    assert exc_info.value.code == 2


def test_artifact_docs_cover_registered_subcommands() -> None:
    docs_path = Path(__file__).parents[2] / "docs" / "artifacts.md"
    docs = docs_path.read_text()
    subcommands = subparser_action(artifact_parser()).choices

    for subcommand in subcommands:
        assert f"sase artifact {subcommand}" in docs


@pytest.mark.parametrize(
    "doc_path",
    [
        Path(__file__).parents[2] / "docs" / "artifacts.md",
        Path(__file__).parents[2]
        / "src"
        / "sase"
        / "xprompts"
        / "skills"
        / "sase_artifact.md",
    ],
)
def test_artifact_docs_and_skill_examples_parse(doc_path: Path) -> None:
    parser = create_parser()
    examples = [
        line.strip()
        for line in doc_path.read_text().splitlines()
        if line.strip().startswith("sase artifact ")
    ]

    assert examples, f"expected artifact examples in {doc_path}"
    for example in examples:
        parser.parse_args(shlex.split(example)[1:])


def test_entry_dispatches_artifact_command(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def fake_handle(args: argparse.Namespace) -> None:
        seen["command"] = args.command
        raise SystemExit(0)

    monkeypatch.setattr(sys, "argv", ["sase", "artifact", "list", "-j"])
    monkeypatch.setattr(artifact_handler, "handle_artifact_command", fake_handle)

    with pytest.raises(SystemExit) as exc_info:
        entry.main()

    assert exc_info.value.code == 0
    assert seen == {"command": "artifact"}


def test_missing_artifact_subcommand_exits_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(["artifact"])

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 1
    assert "Usage: sase artifact" in capsys.readouterr().out
