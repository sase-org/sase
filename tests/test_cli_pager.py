"""Coverage for reusable terminal pager behavior."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from sase import cli_pager
from sase.cli_pager import PagerMode, page_or_print
from sase.pager.document import (
    PagerDocument,
    PagerOrigin,
    PagerSection,
    section_target_spans,
)
from sase.pager.link_scan import LinkSpanKind


class _Stream:
    def __init__(self, *, tty: bool = False) -> None:
        self.tty = tty
        self.text = ""

    def isatty(self) -> bool:
        return self.tty

    def write(self, text: str) -> int:
        self.text += text
        return len(text)

    def flush(self) -> None:
        return None


@pytest.fixture(autouse=True)
def clean_pager_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in ("SASE_PAGER", "PAGER", "LESS", "TERM", "SASE_AGENT"):
        monkeypatch.delenv(name, raising=False)
    yield


def _streams(monkeypatch: pytest.MonkeyPatch, *, tty: bool) -> tuple[_Stream, _Stream]:
    stdout = _Stream(tty=tty)
    stderr = _Stream()
    monkeypatch.setattr(cli_pager.sys, "stdout", stdout)
    monkeypatch.setattr(cli_pager.sys, "stderr", stderr)
    return stdout, stderr


def _terminal(monkeypatch: pytest.MonkeyPatch, *, tty: bool = True) -> _Stream:
    stdout, _stderr = _streams(monkeypatch, tty=tty)
    monkeypatch.setenv("TERM", "xterm-256color")
    return stdout


@pytest.mark.parametrize(
    ("tty", "term", "agent", "text", "expected"),
    [
        (False, "xterm", False, "long\nlong\n", "long\nlong\n"),
        (True, None, False, "long\nlong\n", "long\nlong\n"),
        (True, "dumb", False, "long\nlong\n", "long\nlong\n"),
        (True, "xterm", True, "long\nlong\n", "long\nlong\n"),
        (True, "xterm", False, "fits\n", "fits\n"),
    ],
)
def test_auto_writes_direct_when_paging_conditions_fail(
    monkeypatch: pytest.MonkeyPatch,
    tty: bool,
    term: str | None,
    agent: bool,
    text: str,
    expected: str,
) -> None:
    stdout, _stderr = _streams(monkeypatch, tty=tty)
    if term is not None:
        monkeypatch.setenv("TERM", term)
    if agent:
        monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setattr(
        cli_pager.shutil,
        "get_terminal_size",
        lambda fallback: os.terminal_size((80, 24)),
    )
    launches: list[tuple[str, PagerDocument | None]] = []
    monkeypatch.setattr(
        cli_pager,
        "_run_sase_pager",
        lambda text, *, document, syntax_session=None: launches.append(
            (text, document)
        ),
    )

    page_or_print(text, mode=PagerMode.AUTO)

    assert launches == []
    assert stdout.text == expected


def test_auto_pages_when_text_is_taller_than_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = _terminal(monkeypatch)
    monkeypatch.setattr(
        cli_pager.shutil,
        "get_terminal_size",
        lambda fallback: os.terminal_size((10, 2)),
    )
    launches: list[tuple[str, PagerDocument | None]] = []
    monkeypatch.setattr(
        cli_pager,
        "_run_sase_pager",
        lambda text, *, document, syntax_session=None: launches.append(
            (text, document)
        ),
    )

    page_or_print("one\ntwo\nthree\n", mode=PagerMode.AUTO)

    assert launches == [("one\ntwo\nthree\n", None)]
    assert stdout.text == ""


def test_always_pages_fitting_text_but_not_redirected_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = _terminal(monkeypatch)
    launches: list[tuple[str, PagerDocument | None]] = []
    monkeypatch.setattr(
        cli_pager,
        "_run_sase_pager",
        lambda text, *, document, syntax_session=None: launches.append(
            (text, document)
        ),
    )

    page_or_print("fits\n", mode=PagerMode.ALWAYS)
    assert launches == [("fits\n", None)]
    assert stdout.text == ""

    redirected, _stderr = _streams(monkeypatch, tty=False)
    page_or_print("fits\n", mode=PagerMode.ALWAYS)
    assert redirected.text == "fits\n"


def test_supplied_pager_document_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _terminal(monkeypatch)
    document = PagerDocument(
        sections=(
            PagerSection(
                identity="bead:sase-1",
                title="sase-1",
                kind="bead",
                body="body\n",
            ),
        ),
        title="sase-1",
        origin=PagerOrigin.BEAD,
    )
    launches: list[tuple[str, PagerDocument | None]] = []
    monkeypatch.setattr(
        cli_pager,
        "_run_sase_pager",
        lambda text, *, document, syntax_session=None: launches.append(
            (text, document)
        ),
    )

    page_or_print("body\n", mode=PagerMode.ALWAYS, document=document)

    assert launches == [("body\n", document)]


def test_pager_environment_no_longer_selects_external_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _terminal(monkeypatch)
    monkeypatch.setenv("SASE_PAGER", "less -S")
    monkeypatch.setenv("PAGER", "cat")
    launches: list[tuple[str, PagerDocument | None]] = []
    monkeypatch.setattr(
        cli_pager,
        "_run_sase_pager",
        lambda text, *, document, syntax_session=None: launches.append(
            (text, document)
        ),
    )

    page_or_print("body\n", mode=PagerMode.ALWAYS)

    assert launches == [("body\n", None)]


def test_sase_pager_startup_failure_falls_back_to_direct_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = _terminal(monkeypatch)

    def fail_run_sase_pager(
        _text: str,
        *,
        document: PagerDocument | None,
        syntax_session: object = None,
    ) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(cli_pager, "_run_sase_pager", fail_run_sase_pager)

    page_or_print("body\n", mode=PagerMode.ALWAYS)

    assert stdout.text == "body\n"


def test_row_estimate_strips_sgr_and_counts_wrapped_cells() -> None:
    assert cli_pager._estimated_display_rows("\x1b[31mabcd\x1b[0m", columns=2) == 2
    assert cli_pager._estimated_display_rows("abcdef", columns=3) == 2


def test_fallback_stdin_section_freezes_context_known_kinds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[PagerDocument] = []

    class _FakePager:
        def __init__(
            self, document: PagerDocument, *, syntax_session: object = None
        ) -> None:
            captured.append(document)

        def run(self) -> None:
            return None

    monkeypatch.setattr("sase.pager.app.SasePager", _FakePager)
    monkeypatch.setattr(
        "sase.pager.known_kinds.known_kinds_from_link_context",
        lambda _context: ("designs",),
    )

    cli_pager._run_sase_pager(
        "see designs:202609/spec.md\n",
        document=None,
        syntax_session=object(),
    )

    document = captured[0]
    section = document.sections[0]
    spans = section_target_spans(section, document.origin)

    assert "designs" in section.known_kinds
    assert [(span.kind, span.text, span.target) for span in spans] == [
        (
            LinkSpanKind.ARTIFACT_REF.value,
            "designs:202609/spec.md",
            "designs:202609/spec.md",
        )
    ]


def test_direct_write_does_not_classify_or_lex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout, _stderr = _streams(monkeypatch, tty=False)
    monkeypatch.setattr(
        "sase.pager.syntax_policy.resolve_source_language",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("direct write lexed")),
    )
    monkeypatch.setattr(
        "sase.pager.syntax.highlight_source",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("direct write lexed")
        ),
    )

    page_or_print("print(1)\n", mode=PagerMode.NEVER)

    assert stdout.text == "print(1)\n"
