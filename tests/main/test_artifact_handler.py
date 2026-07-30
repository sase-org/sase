"""Parser and create-command tests for ``sase artifact``."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pytest

from sase.artifact_cli.create import handle_create
from sase.core.artifact_file_facade import read_artifact_file_index
from sase.main.parser import create_parser, default_list_delegation_notice


def _create_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "path": "artifact.md",
        "label": None,
        "kind": None,
        "move": False,
        "bead": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_parser_registers_canonical_group_alias_and_all_subcommands() -> None:
    parser = create_parser()

    canonical = parser.parse_args(["artifact", "create", "-p", "report.md"])
    alias = parser.parse_args(["artifact-file", "create", "-p", "report.md"])
    move = parser.parse_args(["artifact", "create", "-m", "-p", "report.md"])
    help_text = _artifact_parser(parser).format_help()

    assert canonical.command == "artifact"
    assert alias.command == "artifact-file"
    assert canonical.artifact_subcommand == alias.artifact_subcommand == "create"
    assert canonical.move is False
    assert move.move is True
    assert "{create,doctor,list,open,path,prune,show,stats,trash}" in help_text
    assert "Bare `sase artifact` defaults to `sase artifact list`." in help_text


def test_parser_defaults_bare_group_to_list_with_notice() -> None:
    args = create_parser().parse_args(["artifact"])

    assert args.artifact_subcommand == "list"
    assert args.agent is None
    assert args.explicit is False
    assert args.json is False
    assert args.kind is None
    assert args.limit == 50
    assert args.project is None
    assert args.query is None
    assert args.since is None
    assert default_list_delegation_notice(args) == (
        "No subcommand provided for 'sase artifact'; delegating to "
        "'sase artifact list'."
    )


def test_parser_list_filters_and_repeated_kinds() -> None:
    args = create_parser().parse_args(
        [
            "artifact",
            "list",
            "--agent",
            "agent.one",
            "--explicit",
            "--json",
            "--kind",
            "image",
            "-k",
            "pdf",
            "--limit",
            "5",
            "--project",
            "SASE",
            "--query",
            "diagram",
            "--since",
            "2026-07",
        ]
    )

    assert vars(args) | {} == {
        "command": "artifact",
        "artifact_subcommand": "list",
        "agent": "agent.one",
        "explicit": True,
        "json": True,
        "kind": ["image", "pdf"],
        "limit": 5,
        "project": "SASE",
        "query": "diagram",
        "since": "2026-07",
        "unused": False,
        "_default_list_group": None,
    }


@pytest.mark.parametrize(
    "argv",
    [
        ["artifact", "list", "--limit", "-1"],
        ["artifact", "list", "--limit", "nope"],
        ["artifact", "list", "--since", "yesterday"],
    ],
)
def test_parser_rejects_malformed_list_values(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        create_parser().parse_args(argv)

    assert exc.value.code == 2


def test_public_long_options_are_alphabetical_and_have_short_aliases() -> None:
    parser = create_parser()
    artifact = _artifact_parser(parser)
    subcommands = _subparser_action(artifact)

    assert _long_options(subcommands.choices["create"]) == [
        "--bead",
        "--kind",
        "--label",
        "--move",
        "--path",
    ]
    assert _long_options(subcommands.choices["doctor"]) == ["--fix", "--verify"]
    assert _long_options(subcommands.choices["list"]) == [
        "--agent",
        "--explicit",
        "--json",
        "--kind",
        "--limit",
        "--project",
        "--query",
        "--since",
        "--unused",
    ]
    assert _long_options(subcommands.choices["prune"]) == [
        "--apply",
        "--before",
        "--keep-generations",
        "--json",
        "--kind",
        "--limit",
        "--min-size",
        "--project",
    ]
    assert _long_options(subcommands.choices["show"]) == ["--json"]
    assert _long_options(subcommands.choices["stats"]) == [
        "--json",
        "--project",
        "--top",
    ]
    trash_subcommands = _subparser_action(subcommands.choices["trash"])
    assert _long_options(trash_subcommands.choices["list"]) == [
        "--json",
        "--limit",
    ]
    assert _long_options(trash_subcommands.choices["purge"]) == [
        "--all",
        "--json",
    ]
    assert _long_options(trash_subcommands.choices["restore"]) == ["--json"]
    for child in subcommands.choices.values():
        for action in child._actions:
            long_options = [
                option for option in action.option_strings if option.startswith("--")
            ]
            if not long_options or long_options == ["--help"]:
                continue
            assert any(
                option.startswith("-") and not option.startswith("--")
                for option in action.option_strings
            )


def test_create_requires_agent_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "artifact.md"
    source.write_text("content", encoding="utf-8")
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    assert handle_create(_create_args(path=str(source))) == 1
    assert "SASE_AGENT=1 is required" in capsys.readouterr().err


def test_create_copies_file_records_association_and_prints_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home, artifacts_dir = _configure_artifact_environment(tmp_path, monkeypatch)
    source = tmp_path / "report.md"
    source.write_text("# Report\n", encoding="utf-8")

    assert (
        handle_create(
            _create_args(
                path=str(source),
                label="Release report",
                kind="markdown",
            )
        )
        == 0
    )

    assert source.read_text(encoding="utf-8") == "# Report\n"
    output = capsys.readouterr().out.splitlines()
    assert output[0].startswith("id: explicit:")
    assert output[1] == f"source: {source.resolve()}"
    assert output[2].startswith("path: ")
    assert output[3] == f"ref: file:{output[0].removeprefix('id: ')}"
    stored_path = Path(output[2].removeprefix("path: "))
    assert stored_path.read_text(encoding="utf-8") == "# Report\n"

    rows = read_artifact_file_index(home / ".sase" / "artifacts" / "index.jsonl")
    assert len(rows) == 1
    artifact_file = rows[0]
    assert artifact_file.label == "Release report"
    assert artifact_file.kind == "markdown"
    assert artifact_file.project == "proj"
    assert artifact_file.agent_name == "agent-one"
    assert artifact_file.explicit is True


def test_create_move_removes_source_and_prints_source_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _home, _artifacts_dir = _configure_artifact_environment(tmp_path, monkeypatch)
    source = tmp_path / "scratch.txt"
    source.write_text("scratch\n", encoding="utf-8")

    assert handle_create(_create_args(path=str(source), move=True)) == 0

    assert not source.exists()
    output = capsys.readouterr().out.splitlines()
    assert output[0].startswith("id: explicit:")
    assert output[1] == f"source: {source.resolve()}"
    assert Path(output[2].removeprefix("path: ")).read_text(encoding="utf-8") == (
        "scratch\n"
    )
    assert output[3] == f"ref: file:{output[0].removeprefix('id: ')}"


def test_create_stored_copy_is_independent_of_later_source_edits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home, _artifacts_dir = _configure_artifact_environment(tmp_path, monkeypatch)
    source = tmp_path / "report.md"
    source.write_text("original\n", encoding="utf-8")

    assert handle_create(_create_args(path=str(source))) == 0
    capsys.readouterr()
    [artifact_file] = read_artifact_file_index(
        home / ".sase" / "artifacts" / "index.jsonl"
    )

    source.write_text("updated\n", encoding="utf-8")

    assert Path(artifact_file.path or "").read_text(encoding="utf-8") == "original\n"
    assert artifact_file.sha256 == hashlib.sha256(b"original\n").hexdigest()


def _configure_artifact_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    home = tmp_path / "home"
    artifacts_dir = (
        home
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / "20260507120000"
    )
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"name": "agent-one"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    return home, artifacts_dir


def _artifact_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    return _subparser_action(parser).choices["artifact"]


def _subparser_action(
    parser: argparse.ArgumentParser,
) -> argparse._SubParsersAction:
    return next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )


def _long_options(parser: argparse.ArgumentParser) -> list[str]:
    return [
        option
        for action in parser._actions
        for option in action.option_strings
        if option.startswith("--") and option != "--help"
    ]
