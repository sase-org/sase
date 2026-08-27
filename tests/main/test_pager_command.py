"""Tests for the top-level ``sase pager`` command."""

from __future__ import annotations

from argparse import Namespace
from io import StringIO

import pytest

from sase.main import pager_handler
from sase.main.parser import create_parser
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.resolve import LinkTarget, LinkTargetKind
from tests.main.parser_help_helpers import flat_help, parser_for


class _Stream(StringIO):
    def __init__(self, text: str = "", *, tty: bool) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _args(
    *,
    inputs: list[str] | None = None,
    links: str = "auto",
    plain: bool = False,
    title: str | None = None,
) -> Namespace:
    return Namespace(
        color="auto",
        inputs=[] if inputs is None else inputs,
        links=links,
        plain=plain,
        title=title,
        wrap=80,
    )


def test_parser_registers_pager_options_and_positionals() -> None:
    args = create_parser(only="pager").parse_args(
        [
            "pager",
            "-c",
            "always",
            "-l",
            "never",
            "-p",
            "-t",
            "Demo",
            "-w",
            "100",
            "bead:sase-1",
        ]
    )

    assert args.command == "pager"
    assert args.color == "always"
    assert args.links == "never"
    assert args.plain is True
    assert args.title == "Demo"
    assert args.wrap == 100
    assert args.inputs == ["bead:sase-1"]


def test_pager_help_documents_public_options() -> None:
    help_text = flat_help(parser_for(("sase", "pager")).format_help())

    assert "-c, --color {auto,always,never}" in help_text
    assert "-l, --links {auto,never}" in help_text
    assert "-p, --plain" in help_text
    assert "-t, --title TITLE" in help_text
    assert "-w, --wrap WIDTH" in help_text
    assert "REF|PATH" in help_text


def test_stdin_non_tty_writes_plain_without_launching_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdin = _Stream("hello bead:sase-1\n", tty=False)
    stdout = _Stream(tty=False)
    monkeypatch.setattr(pager_handler.sys, "stdin", stdin)
    monkeypatch.setattr(pager_handler.sys, "stdout", stdout)
    monkeypatch.setattr(pager_handler, "link_pager_enabled", lambda: True)

    def fail_run_app(_document: PagerDocument, *, links_enabled: bool) -> None:
        raise AssertionError("non-tty stdout should not launch the app")

    monkeypatch.setattr(pager_handler, "_run_pager_app", fail_run_app)

    assert pager_handler.handle_pager_command(_args(title="Demo")) == 0
    assert stdout.getvalue() == "hello bead:sase-1\n"


def test_enabled_tty_launches_app_with_links_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdin = _Stream("body\n", tty=True)
    stdout = _Stream(tty=True)
    launches: list[tuple[PagerDocument, bool]] = []
    monkeypatch.setattr(pager_handler.sys, "stdin", stdin)
    monkeypatch.setattr(pager_handler.sys, "stdout", stdout)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr(pager_handler, "link_pager_enabled", lambda: True)
    monkeypatch.setattr(
        pager_handler,
        "_run_pager_app",
        lambda document, *, links_enabled: launches.append((document, links_enabled)),
    )

    assert pager_handler.handle_pager_command(_args(links="never")) == 0

    assert stdout.getvalue() == ""
    assert launches[0][0].title == "stdin"
    assert launches[0][1] is False


def test_plain_positional_input_uses_pager_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = PagerDocument(
        sections=(
            PagerSection(
                identity="file:/tmp/demo.txt",
                title="demo.txt",
                kind="file",
                body="resolved\n",
            ),
        ),
        title="demo.txt",
        origin=PagerOrigin.FILE,
    )
    stdout = _Stream(tty=False)
    monkeypatch.setattr(pager_handler.sys, "stdout", stdout)
    monkeypatch.setattr(
        pager_handler,
        "resolve_ref",
        lambda value: LinkTarget(kind=LinkTargetKind.DOCUMENT, document=document),
    )

    assert (
        pager_handler.handle_pager_command(
            _args(inputs=["file:/tmp/demo.txt"], plain=True)
        )
        == 0
    )
    assert stdout.getvalue() == "resolved\n"


def test_stdin_dash_must_not_be_mixed_with_other_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stderr = _Stream(tty=False)
    monkeypatch.setattr(pager_handler.sys, "stderr", stderr)

    assert (
        pager_handler.handle_pager_command(
            _args(inputs=["-", "src/sase/main/parser.py"])
        )
        == 2
    )
    assert "'-' must be the only pager input" in stderr.getvalue()
