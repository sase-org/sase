"""Body, syntax, and attached-target tests for the pager document model."""

from __future__ import annotations

import pytest
from rich.text import Text

from sase.pager.document import (
    AttachedTarget,
    PagerOrigin,
    PagerSection,
    RawSourceSpec,
    section_syntax_language,
    section_target_spans,
)


def test_ansi_body_round_trips_plain_text_and_styles() -> None:
    section = PagerSection(
        identity="file:/tmp/demo.py",
        title="demo.py",
        kind="file",
        body="\x1b[31mred\x1b[0m src/sase/pager/document.py",
    )

    body = section.body_text

    assert section.plain_text == "red src/sase/pager/document.py"
    assert isinstance(section.body_renderable, Text)
    assert body.plain == section.plain_text
    assert body.spans
    assert body.spans[0].start == 0
    assert body.spans[0].end == 3


def test_string_body_keeps_a_single_trailing_newline() -> None:
    section = PagerSection(
        identity="file:/tmp/demo.txt",
        title="demo.txt",
        kind="file",
        body="indexed\n",
    )
    assert section.plain_text == "indexed\n"


def test_string_body_preserves_double_trailing_newline() -> None:
    section = PagerSection(
        identity="file:/tmp/demo.txt",
        title="demo.txt",
        kind="file",
        body="indexed\n\n",
    )
    assert section.plain_text == "indexed\n\n"


def test_string_body_does_not_double_trailing_newline_when_from_ansi_keeps_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def keep_trailing(text: str, *_args: object, **_kwargs: object) -> Text:
        result = Text(text.rstrip("\n"))
        if text.endswith("\n"):
            result.append("\n")
        return result

    monkeypatch.setattr(Text, "from_ansi", staticmethod(keep_trailing))
    section = PagerSection(
        identity="file:/tmp/demo.txt",
        title="demo.txt",
        kind="file",
        body="indexed\n",
    )
    assert section.plain_text == "indexed\n"


def test_raw_source_defaults_to_none_and_does_not_affect_rendering() -> None:
    section = PagerSection(
        identity="file:/tmp/demo.py",
        title="demo.py",
        kind="file",
        body="print('hi')\n",
    )
    assert section.raw_source is None
    assert section_syntax_language(section) is None


def test_section_syntax_language_returns_the_spec_language_when_eligible() -> None:
    section = PagerSection(
        identity="file:/tmp/demo.py",
        title="demo.py",
        kind="file",
        body="print('hi')\n",
        raw_source=RawSourceSpec(language="python"),
    )
    assert section_syntax_language(section) == "python"


def test_section_syntax_language_is_none_when_ineligible() -> None:
    section = PagerSection(
        identity="file:/tmp/demo.py",
        title="demo.py",
        kind="file",
        body="print('hi')\n",
        raw_source=RawSourceSpec(language="python", eligible=False),
    )
    assert section_syntax_language(section) is None


def test_section_syntax_language_is_none_without_a_language_hint() -> None:
    section = PagerSection(
        identity="file:/tmp/demo.txt",
        title="demo.txt",
        kind="file",
        body="plain text\n",
        raw_source=RawSourceSpec(language=None),
    )
    assert section_syntax_language(section) is None


def test_attached_target_suppresses_overlapping_scanned_span() -> None:
    body = "open src/sase/pager/document.py and https://example.test"
    path_start = body.index("src/")
    path_end = path_start + len("src/sase/pager/document.py")
    section = PagerSection(
        identity="file:/tmp/demo.py",
        title="demo.py",
        kind="file",
        body=body,
        targets=(
            AttachedTarget(
                kind="commit",
                target={"sha": "abcdef1234567890"},
                start=path_start,
                end=path_end,
            ),
        ),
    )

    targets = section_target_spans(section, PagerOrigin.FILE)

    assert [(target.source, target.kind, target.start) for target in targets] == [
        ("attached", "commit", path_start),
        ("scanned", "url", body.index("https://")),
    ]
    assert targets[0].target == {"sha": "abcdef1234567890"}
    assert targets[0].text == "src/sase/pager/document.py"


def test_attached_target_span_must_fit_body() -> None:
    with pytest.raises(ValueError, match="exceeds body length"):
        PagerSection(
            identity="file:/tmp/demo.py",
            title="demo.py",
            kind="file",
            body="short",
            targets=(
                AttachedTarget(kind="file", target="/tmp/demo.py", start=0, end=9),
            ),
        )
