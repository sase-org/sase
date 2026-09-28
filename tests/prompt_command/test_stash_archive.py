"""CLI coverage for ``sase prompt stash-archive`` (tmp stores only)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.core import prompt_stash_facade as facade
from sase.core.prompt_stash_wire import PromptStashEntryWire
from sase.core.rust import RUST_EXTENSION_MODULE_NAME
from sase.main.parser import create_parser
from sase.prompt.cli_stash_archive import (
    _handle_stash_archive_list,
    _handle_stash_archive_restore,
    _handle_stash_archive_show,
)


def _skip_without_archive_bindings() -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    for name in ("read_prompt_stash_archive", "recover_prompt_stash_archive"):
        if not hasattr(rust_module, name):
            pytest.skip(f"sase_core_rs is too old (no {name} binding).")


def _point_store_at(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(
        "sase.prompt.cli_stash_archive.prompt_stash_path",
        lambda: path,
        raising=True,
    )
    monkeypatch.setattr("sase.core.paths.prompt_stash_path", lambda: path, raising=True)


def _entry(
    entry_id: str, text: str, *, frontmatter: str = "", project: str | None = None
) -> PromptStashEntryWire:
    return PromptStashEntryWire(
        id=entry_id,
        created_at="2026-09-26T13:00:00+00:00",
        text=text,
        frontmatter=frontmatter,
        project=project,
        source="test",
    )


def _seed(path: Path, entries: list[PromptStashEntryWire]) -> None:
    for entry in entries:
        facade.append_prompt_stash(path, entry)


def _list_ns(
    *,
    json_: bool = False,
    limit: int = 20,
    query: str | None = None,
    reason: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(json=json_, limit=limit, query=query, reason=reason)


def test_parser_stash_archive_subcommands() -> None:
    parser = create_parser()

    list_args = parser.parse_args(
        [
            "prompt",
            "stash-archive",
            "list",
            "-j",
            "-n",
            "5",
            "-q",
            "auth",
            "-r",
            "popped",
        ]
    )
    assert list_args.prompt_subcommand == "stash-archive"
    assert list_args.stash_archive_subcommand == "list"
    assert list_args.json is True
    assert list_args.limit == 5
    assert list_args.query == "auth"
    assert list_args.reason == "popped"

    restore_args = parser.parse_args(
        ["prompt", "stash-archive", "restore", "abc", "def"]
    )
    assert restore_args.stash_archive_subcommand == "restore"
    assert restore_args.ids == ["abc", "def"]

    show_args = parser.parse_args(["prompt", "stash-archive", "show", "abc123", "-j"])
    assert show_args.stash_archive_subcommand == "show"
    assert show_args.id == "abc123"
    assert show_args.json is True


def test_parser_stash_archive_bare_defaults_to_list() -> None:
    parser = create_parser()
    args = parser.parse_args(["prompt", "stash-archive"])
    assert args.stash_archive_subcommand == "list"


def test_list_empty_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _skip_without_archive_bindings()
    _point_store_at(monkeypatch, tmp_path / "prompt_stash.jsonl")

    _handle_stash_archive_list(_list_ns())
    assert "empty" in capsys.readouterr().out

    _handle_stash_archive_list(_list_ns(json_=True))
    assert json.loads(capsys.readouterr().out) == []


def test_list_shows_popped_rows_with_json_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _skip_without_archive_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            _entry("gone-id", "doomed draft text", project="proj-a"),
            _entry("kept-id", "stays stashed"),
        ],
    )
    facade.pop_prompt_stash(path, ["gone-id"])

    _handle_stash_archive_list(_list_ns(json_=True))
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    record = payload[0]
    assert record["reason"] == "popped"
    assert record["entry"]["id"] == "gone-id"
    assert record["entry"]["text"] == "doomed draft text"
    assert record["entry"]["project"] == "proj-a"
    assert record["archived_at"]
    assert record["kind"] == "archived"

    _handle_stash_archive_list(_list_ns())
    out = capsys.readouterr().out
    assert "popped" in out
    assert "gone-id"[:8] in out
    assert "doomed draft text" in out


def test_list_limit_query_and_reason_filters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _skip_without_archive_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            _entry("aaa", "alpha deploy draft", frontmatter="model: x"),
            _entry("bbb", "beta review draft"),
            _entry("ccc", "gamma deploy draft"),
        ],
    )
    facade.pop_prompt_stash(path, ["aaa", "bbb", "ccc"])
    facade.purge_prompt_stash(path, [])  # no-op; keeps the trash path honest

    _handle_stash_archive_list(_list_ns(json_=True, query="deploy"))
    payload = json.loads(capsys.readouterr().out)
    assert {record["entry"]["id"] for record in payload} == {"aaa", "ccc"}

    _handle_stash_archive_list(_list_ns(json_=True, reason="popped"))
    assert len(json.loads(capsys.readouterr().out)) == 3

    _handle_stash_archive_list(_list_ns(json_=True, reason="purged"))
    assert json.loads(capsys.readouterr().out) == []

    _handle_stash_archive_list(_list_ns(json_=True, limit=1))
    assert len(json.loads(capsys.readouterr().out)) == 1


def test_purge_archives_with_purged_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _skip_without_archive_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(path, [_entry("doomed", "trash me")])
    facade.trash_prompt_stash(path, ["doomed"], 100, "2026-09-26T14:00:00+00:00")
    facade.purge_prompt_stash(path, ["doomed"])

    _handle_stash_archive_list(_list_ns(json_=True, reason="purged"))
    payload = json.loads(capsys.readouterr().out)
    assert [record["entry"]["id"] for record in payload] == ["doomed"]
    assert payload[0]["trashed_at"] == "2026-09-26T14:00:00+00:00"


def test_show_full_and_prefix_and_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _skip_without_archive_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(path, [_entry("abcdef123456", "show me\nsecond line")])
    facade.pop_prompt_stash(path, ["abcdef123456"])

    _handle_stash_archive_show(argparse.Namespace(id="abcdef123456", json=False))
    out = capsys.readouterr().out
    assert "show me" in out
    assert "second line" in out

    _handle_stash_archive_show(argparse.Namespace(id="abcdef12", json=True))
    payload = json.loads(capsys.readouterr().out)
    assert payload["entry"]["id"] == "abcdef123456"

    with pytest.raises(SystemExit) as exc_info:
        _handle_stash_archive_show(argparse.Namespace(id="missing", json=False))
    assert exc_info.value.code == 1


def test_restore_round_trip_by_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _skip_without_archive_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(path, [_entry("restore-me-1", "bring me back")])
    facade.pop_prompt_stash(path, ["restore-me-1"])
    assert facade.read_prompt_stash_snapshot(path).entries == []

    code = _handle_stash_archive_restore(argparse.Namespace(ids=["restore-me"]))
    assert code == 0
    assert "Restored restore-me-1" in capsys.readouterr().out
    assert [e.id for e in facade.read_prompt_stash_snapshot(path).entries] == [
        "restore-me-1"
    ]


def test_restore_ambiguous_unknown_and_active_ids_are_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _skip_without_archive_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            _entry("shared-aaa", "first"),
            _entry("shared-bbb", "second"),
            _entry("live-row", "still stashed"),
        ],
    )
    facade.pop_prompt_stash(path, ["shared-aaa", "shared-bbb"])

    # Restore one row first so it is both archived and active.
    assert _handle_stash_archive_restore(argparse.Namespace(ids=["shared-aaa"])) == 0
    capsys.readouterr()

    code = _handle_stash_archive_restore(
        argparse.Namespace(ids=["shared-", "nope", "shared-aaa"])
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "ambiguous" in out
    assert "unknown" in out
    assert "already in Stash" in out
    # Nothing new recovered: the stash holds the live row plus the earlier restore.
    assert [e.id for e in facade.read_prompt_stash_snapshot(path).entries] == [
        "live-row",
        "shared-aaa",
    ]
