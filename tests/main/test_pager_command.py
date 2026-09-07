"""Tests for the top-level ``sase pager`` command."""

from __future__ import annotations

from argparse import Namespace
from io import StringIO
from pathlib import Path

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
    color: str = "auto",
    syntax: str | None = None,
) -> Namespace:
    return Namespace(
        color=color,
        inputs=[] if inputs is None else inputs,
        links=links,
        plain=plain,
        syntax=syntax,
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
            "-s",
            "python",
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
    assert args.syntax == "python"
    assert args.title == "Demo"
    assert args.wrap == 100
    assert args.inputs == ["bead:sase-1"]


def test_pager_help_documents_public_options() -> None:
    help_text = flat_help(parser_for(("sase", "pager")).format_help())

    assert any(
        rendering in help_text
        for rendering in (
            "-c, --color {auto,always,never}",
            "-c {auto,always,never}, --color {auto,always,never}",
        )
    )
    assert any(
        rendering in help_text
        for rendering in (
            "-l, --links {auto,never}",
            "-l {auto,never}, --links {auto,never}",
        )
    )
    assert "-p, --plain" in help_text
    assert any(
        rendering in help_text
        for rendering in (
            "-s, --syntax ALIAS",
            "-s ALIAS, --syntax ALIAS",
        )
    )
    assert any(
        rendering in help_text
        for rendering in (
            "-t, --title TITLE",
            "-t TITLE, --title TITLE",
        )
    )
    assert any(
        rendering in help_text
        for rendering in (
            "-w, --wrap WIDTH",
            "-w WIDTH, --wrap WIDTH",
        )
    )
    assert "REF|PATH" in help_text


def test_stdin_non_tty_writes_plain_without_launching_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdin = _Stream("hello bead:sase-1\n", tty=False)
    stdout = _Stream(tty=False)
    monkeypatch.setattr(pager_handler.sys, "stdin", stdin)
    monkeypatch.setattr(pager_handler.sys, "stdout", stdout)

    def fail_run_app(
        _document: PagerDocument,
        *,
        links_enabled: bool,
        syntax_session: object = None,
    ) -> None:
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
    monkeypatch.setattr(
        pager_handler,
        "_run_pager_app",
        lambda document, *, links_enabled, syntax_session=None: launches.append(
            (document, links_enabled, syntax_session)
        ),
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
    contexts: list[object] = []

    def fake_resolve(value: str, *, context: object = None) -> LinkTarget:
        contexts.append(context)
        return LinkTarget(kind=LinkTargetKind.DOCUMENT, document=document)

    monkeypatch.setattr(pager_handler.sys, "stdout", stdout)
    monkeypatch.setattr(
        pager_handler,
        "resolve_ref",
        fake_resolve,
    )

    assert (
        pager_handler.handle_pager_command(
            _args(inputs=["file:/tmp/demo.txt"], plain=True)
        )
        == 0
    )
    assert stdout.getvalue() == "resolved\n"
    assert contexts and contexts[0] is not None


def test_combined_inputs_preserve_each_section_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bead_document = PagerDocument(
        sections=(
            PagerSection(
                identity="bead:sase-1",
                title="sase-1",
                kind="bead",
                body="bead body\n",
                subject_ref="bead:sase-1",
            ),
        ),
        title="sase-1",
        origin=PagerOrigin.BEAD,
    )
    file_document = PagerDocument(
        sections=(
            PagerSection(
                identity="file:/tmp/demo.txt",
                title="demo.txt",
                kind="file",
                body="file body\n",
                subject_ref="file:/tmp/demo.txt",
            ),
        ),
        title="demo.txt",
        origin=PagerOrigin.FILE,
    )

    def fake_resolve(value: str, *, context: object = None) -> LinkTarget:
        del context
        if value.startswith("bead:"):
            return LinkTarget(kind=LinkTargetKind.DOCUMENT, document=bead_document)
        return LinkTarget(kind=LinkTargetKind.DOCUMENT, document=file_document)

    monkeypatch.setattr(pager_handler, "resolve_ref", fake_resolve)

    document = pager_handler._build_pager_document(["bead:sase-1", "demo.txt"])

    assert [section.origin for section in document.sections] == [
        PagerOrigin.BEAD,
        PagerOrigin.FILE,
    ]
    assert [section.identity for section in document.sections] == [
        "bead:sase-1",
        "file:/tmp/demo.txt",
    ]


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


class _CountingStream(_Stream):
    def __init__(self, text: str = "", *, tty: bool) -> None:
        super().__init__(text, tty=tty)
        self.reads = 0

    def read(self, *args: object, **kwargs: object) -> str:
        self.reads += 1
        return super().read(*args, **kwargs)


def test_invalid_syntax_alias_fails_before_reading_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdin = _CountingStream("secret-stdin\n", tty=True)
    stderr = _Stream(tty=False)
    monkeypatch.setattr(pager_handler.sys, "stdin", stdin)
    monkeypatch.setattr(pager_handler.sys, "stderr", stderr)

    def fail_run_app(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("invalid syntax must not launch the app")

    monkeypatch.setattr(pager_handler, "_run_pager_app", fail_run_app)

    assert (
        pager_handler.handle_pager_command(_args(syntax="definitely-not-a-lexer")) == 2
    )
    assert stdin.reads == 0
    assert "unknown syntax alias" in stderr.getvalue()


def test_explicit_syntax_overrides_stdin_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdin = _Stream("key: value\n", tty=True)
    stdout = _Stream(tty=True)
    launches: list[tuple[PagerDocument, object]] = []
    monkeypatch.setattr(pager_handler.sys, "stdin", stdin)
    monkeypatch.setattr(pager_handler.sys, "stdout", stdout)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr(
        pager_handler,
        "_run_pager_app",
        lambda document, *, links_enabled, syntax_session=None: launches.append(
            (document, syntax_session)
        ),
    )

    assert pager_handler.handle_pager_command(_args(syntax="yaml")) == 0

    document, session = launches[0]
    assert document.sections[0].raw_source is not None
    assert document.sections[0].raw_source.language == "yaml"
    assert session is not None
    assert session.syntax_enabled is True


def test_syntax_none_disables_session_highlighting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdin = _Stream("print(1)\n", tty=True)
    stdout = _Stream(tty=True)
    launches: list[object] = []
    monkeypatch.setattr(pager_handler.sys, "stdin", stdin)
    monkeypatch.setattr(pager_handler.sys, "stdout", stdout)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr(
        pager_handler,
        "_run_pager_app",
        lambda document, *, links_enabled, syntax_session=None: launches.append(
            syntax_session
        ),
    )

    assert pager_handler.handle_pager_command(_args(syntax="none")) == 0
    assert launches[0].syntax_enabled is False
    assert launches[0].color_enabled is True


def test_color_never_disables_syntax_and_color(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdin = _Stream("print(1)\n", tty=True)
    stdout = _Stream(tty=True)
    launches: list[object] = []
    monkeypatch.setattr(pager_handler.sys, "stdin", stdin)
    monkeypatch.setattr(pager_handler.sys, "stdout", stdout)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr(
        pager_handler,
        "_run_pager_app",
        lambda document, *, links_enabled, syntax_session=None: launches.append(
            syntax_session
        ),
    )

    assert (
        pager_handler.handle_pager_command(_args(color="never", syntax="python")) == 0
    )
    assert launches[0].syntax_enabled is False
    assert launches[0].color_enabled is False


def test_stdin_diff_is_classified_without_an_explicit_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdin = _Stream("diff --git a/old b/new\n", tty=True)
    stdout = _Stream(tty=True)
    launches: list[PagerDocument] = []
    monkeypatch.setattr(pager_handler.sys, "stdin", stdin)
    monkeypatch.setattr(pager_handler.sys, "stdout", stdout)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr(
        pager_handler,
        "_run_pager_app",
        lambda document, *, links_enabled, syntax_session=None: launches.append(
            document
        ),
    )

    assert pager_handler.handle_pager_command(_args()) == 0
    assert launches[0].sections[0].raw_source is not None
    assert launches[0].sections[0].raw_source.language == "diff"


def test_combined_real_paths_keep_per_section_owner_and_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "one" / "a.md"
    second = tmp_path / "two" / "b.md"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("alpha\n", encoding="utf-8")
    second.write_text("beta\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    document = pager_handler._build_pager_document([str(first), str(second)])

    assert [section.origin for section in document.sections] == [
        PagerOrigin.FILE,
        PagerOrigin.FILE,
    ]
    assert document.sections[0].owner is not None
    assert document.sections[1].owner is not None
    assert document.sections[0].link_anchors[0].directory == first.parent.resolve()
    assert document.sections[1].link_anchors[0].directory == second.parent.resolve()
    assert document.sections[0].plain_text == "alpha\n"
    assert document.sections[1].plain_text == "beta\n"


def test_links_never_is_passed_to_the_app_for_path_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "notes.md"
    path.write_text("https://example.test/x\n", encoding="utf-8")
    launches: list[tuple[PagerDocument, bool]] = []
    stdin = _Stream(tty=True)
    stdout = _Stream(tty=True)
    monkeypatch.setattr(pager_handler.sys, "stdin", stdin)
    monkeypatch.setattr(pager_handler.sys, "stdout", stdout)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr(
        pager_handler,
        "_run_pager_app",
        lambda document, *, links_enabled, syntax_session=None: launches.append(
            (document, links_enabled)
        ),
    )

    assert (
        pager_handler.handle_pager_command(_args(inputs=[str(path)], links="never"))
        == 0
    )
    assert launches[0][1] is False
    assert launches[0][0].sections[0].plain_text == "https://example.test/x\n"
