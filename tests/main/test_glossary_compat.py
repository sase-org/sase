"""Tests for `sase glossary`'s deprecation notices and glossary-web delegation."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from sase.main import glossary_handler
from sase.main.parser import create_parser


class _SentinelWeb:
    """A stand-in for a `MemoryWeb`; dispatch only checks presence, not shape."""


def _web(monkeypatch: pytest.MonkeyPatch) -> _SentinelWeb:
    web = _SentinelWeb()
    monkeypatch.setattr(glossary_handler, "find_glossary_web", lambda *_a, **_kw: web)
    return web


def _no_web(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(glossary_handler, "find_glossary_web", lambda *_a, **_kw: None)


# --- read -------------------------------------------------------------------


def test_read_delegates_to_memory_read_when_web_present(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _web(monkeypatch)
    calls: list[argparse.Namespace] = []
    monkeypatch.setattr(
        "sase.memory.cli_read.handle_memory_read_command",
        lambda ns, **_kw: calls.append(ns),
    )
    args = create_parser().parse_args(
        [
            "glossary",
            "read",
            "Agent Hood",
            "Stitch",
            "-d",
            "1",
            "-f",
            "json",
            "-r",
            "why",
        ]
    )

    with pytest.raises(SystemExit) as exc:
        glossary_handler.handle_glossary_command(args)

    assert exc.value.code == 0
    assert len(calls) == 1
    namespace = calls[0]
    assert namespace.selectors == ["glossary:Agent Hood", "glossary:Stitch"]
    assert namespace.depth == 1
    assert namespace.format == "json"
    assert namespace.reason == "why"
    err = capsys.readouterr().err
    assert "sase glossary read" in err
    assert "sase memory read glossary:<term>" in err


def test_read_runs_legacy_handler_and_still_prints_notice(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _no_web(monkeypatch)
    calls: list[argparse.Namespace] = []
    monkeypatch.setattr(
        "sase.glossary.cli_read.handle_glossary_read_command",
        lambda args, **_kw: calls.append(args),
    )
    args = create_parser().parse_args(["glossary", "read", "Stitch", "-r", "why"])

    with pytest.raises(SystemExit) as exc:
        glossary_handler.handle_glossary_command(args)

    assert exc.value.code == 0
    assert calls == [args]
    assert "sase memory read glossary:<term>" in capsys.readouterr().err


# --- show -------------------------------------------------------------------


def test_show_delegates_to_memory_show_when_web_present(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _web(monkeypatch)
    calls: list[argparse.Namespace] = []
    monkeypatch.setattr(
        "sase.memory.cli_show.handle_memory_show_command",
        lambda ns, **_kw: calls.append(ns),
    )
    args = create_parser().parse_args(["glossary", "show", "Stitch", "-d", "0"])

    with pytest.raises(SystemExit) as exc:
        glossary_handler.handle_glossary_command(args)

    assert exc.value.code == 0
    namespace = calls[0]
    assert namespace.selectors == ["glossary:Stitch"]
    assert namespace.depth == 0
    assert not hasattr(namespace, "reason")
    assert "sase memory show glossary:<term>" in capsys.readouterr().err


# --- all ----------------------------------------------------------------


def test_all_delegates_to_memory_show_whole_web(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _web(monkeypatch)
    calls: list[argparse.Namespace] = []
    monkeypatch.setattr(
        "sase.memory.cli_show.handle_memory_show_command",
        lambda ns, **_kw: calls.append(ns),
    )
    args = create_parser().parse_args(["glossary", "all", "-f", "markdown"])

    with pytest.raises(SystemExit) as exc:
        glossary_handler.handle_glossary_command(args)

    assert exc.value.code == 0
    namespace = calls[0]
    assert namespace.selectors == ["glossary"]
    assert namespace.depth is None
    assert namespace.format == "markdown"
    assert "sase memory show glossary" in capsys.readouterr().err


# --- list -----------------------------------------------------------------


def test_list_delegates_to_memory_web_show(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _web(monkeypatch)
    calls: list[argparse.Namespace] = []
    monkeypatch.setattr(
        "sase.memory.web.cli.handle_memory_web_show_command",
        lambda ns, **_kw: calls.append(ns),
    )
    args = create_parser().parse_args(["glossary", "list", "hood", "--definitions"])

    with pytest.raises(SystemExit) as exc:
        glossary_handler.handle_glossary_command(args)

    assert exc.value.code == 0
    namespace = calls[0]
    assert namespace.web == "glossary"
    assert namespace.pattern == "hood"
    assert namespace.bodies is True
    assert "sase memory web show glossary" in capsys.readouterr().err


# --- log --------------------------------------------------------------------


def test_log_delegates_to_memory_log(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _web(monkeypatch)
    calls: list[argparse.Namespace] = []
    monkeypatch.setattr(
        "sase.memory.cli_log.handle_memory_log_command",
        lambda ns, **_kw: calls.append(ns),
    )
    args = create_parser().parse_args(
        ["glossary", "log", "-a", "agent-a", "-f", "json"]
    )

    with pytest.raises(SystemExit) as exc:
        glossary_handler.handle_glossary_command(args)

    assert exc.value.code == 0
    namespace = calls[0]
    assert namespace.agent == "agent-a"
    assert namespace.include == ["glossary"]
    assert namespace.json is True
    assert "sase memory log --include glossary" in capsys.readouterr().err


def test_log_chdirs_into_the_requested_project_for_delegation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _web(monkeypatch)
    project_root = tmp_path / "other-project"
    project_root.mkdir()
    monkeypatch.setattr(
        "sase.glossary.compat._glossary_project_root", lambda _ref: project_root
    )
    seen_cwd: list[Path] = []
    monkeypatch.setattr(
        "sase.memory.cli_log.handle_memory_log_command",
        lambda ns, **_kw: seen_cwd.append(Path.cwd()),
    )
    original_cwd = Path.cwd()
    args = create_parser().parse_args(["glossary", "log", "-p", "other"])

    with pytest.raises(SystemExit):
        glossary_handler.handle_glossary_command(args)

    assert len(seen_cwd) == 1
    assert seen_cwd[0].samefile(project_root)
    assert Path.cwd() == original_cwd


# --- add/del ------------------------------------------------------------


def test_add_delegates_to_web_mutation_when_web_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web = _web(monkeypatch)
    calls: list[tuple[argparse.Namespace, object]] = []
    monkeypatch.setattr(
        "sase.glossary.web_mutation.handle_glossary_add_web_command",
        lambda args, web, **_kw: calls.append((args, web)),
    )
    args = create_parser().parse_args(["glossary", "add", "Term", "A definition."])

    with pytest.raises(SystemExit) as exc:
        glossary_handler.handle_glossary_command(args)

    assert exc.value.code == 0
    assert calls == [(args, web)]


def test_add_runs_legacy_handler_when_no_web(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_web(monkeypatch)
    calls: list[argparse.Namespace] = []
    monkeypatch.setattr(
        "sase.glossary.cli_add.handle_glossary_add_command",
        lambda args, **_kw: calls.append(args),
    )
    args = create_parser().parse_args(["glossary", "add", "Term", "A definition."])

    with pytest.raises(SystemExit) as exc:
        glossary_handler.handle_glossary_command(args)

    assert exc.value.code == 0
    assert calls == [args]


def test_del_delegates_to_web_mutation_when_web_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web = _web(monkeypatch)
    calls: list[tuple[argparse.Namespace, object]] = []
    monkeypatch.setattr(
        "sase.glossary.web_mutation.handle_glossary_del_web_command",
        lambda args, web, **_kw: calls.append((args, web)),
    )
    args = create_parser().parse_args(["glossary", "del", "Term", "-n"])

    with pytest.raises(SystemExit) as exc:
        glossary_handler.handle_glossary_command(args)

    assert exc.value.code == 0
    assert calls == [(args, web)]


def test_del_runs_legacy_handler_when_no_web(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_web(monkeypatch)
    calls: list[argparse.Namespace] = []
    monkeypatch.setattr(
        "sase.glossary.cli_del.handle_glossary_del_command",
        lambda args, **_kw: calls.append(args),
    )
    args = create_parser().parse_args(["glossary", "del", "Term"])

    with pytest.raises(SystemExit) as exc:
        glossary_handler.handle_glossary_command(args)

    assert exc.value.code == 0
    assert calls == [args]
