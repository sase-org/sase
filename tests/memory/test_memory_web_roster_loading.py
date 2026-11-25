"""Tests for the roster_loading axis and generated on-demand pointer."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sase.markdown_width import markdown_print_width
from sase.markdown_wrap import wrap_markdown
from sase.memory.web import (
    END_MARKER,
    START_MARKER,
    discover_memory_webs,
    parse_web_descriptor,
    render_on_demand_roster_pointer,
    render_web_body_with_roster,
    render_web_descriptor_with_roster,
    render_web_projection_body,
    strip_managed_roster_markers,
    validate_memory_webs,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _descriptor(
    *,
    roster: str = "list",
    extra: str = "",
    body: str = "Authored preamble.\n",
) -> str:
    return (
        "---\n"
        "web: true\n"
        f"roster: {roster}\n"
        "roster_label: RECORDS\n"
        "strand_noun: record\n"
        "description: Runbook catalog.\n"
        f"{extra}"
        "---\n\n"
        f"{body}"
    )


def _strand(
    keyword: str = "Alpha Record",
    *,
    slug: str | None = None,
    summary: str = "First record.\n",
) -> str:
    return f"---\nkeyword: {keyword}\nsummary: {summary}---\n\nStrand body for {keyword}.\n"


def _seed(
    root: Path,
    *,
    extra: str = "",
    body: str | None = None,
    strand_count: int = 2,
    roster: str = "list",
    slug: str = "runbooks",
) -> None:
    region = f"{START_MARKER}\nold roster\n{END_MARKER}\n"
    descriptor_body = "Authored preamble.\n\n" + region if body is None else body
    _write(
        root / "sase" / "memory" / f"{slug}.md",
        _descriptor(roster=roster, extra=extra, body=descriptor_body),
    )
    for index in range(strand_count):
        keyword = f"Record {index}"
        _write(
            root / "sase" / "memory" / slug / f"record-{index}.md",
            _strand(keyword, summary=f"Summary {index}.\n"),
        )


def _parse(tmp_path: Path, extra: str = "", **kwargs: object):
    path = tmp_path / "sase" / "memory" / "runbooks.md"
    return parse_web_descriptor(
        root=tmp_path,
        memory_root=path.parent,
        path=path,
        text=_descriptor(extra=extra, **kwargs),  # type: ignore[arg-type]
    )


def test_parse_defaults_roster_loading_to_always(tmp_path: Path) -> None:
    web, error = _parse(tmp_path)

    assert error is None and web is not None
    assert web.roster_loading == "always"
    assert web.roster_read_when == ()


@pytest.mark.parametrize("value", ["always", "on_demand"])
def test_parse_accepts_roster_loading_values(tmp_path: Path, value: str) -> None:
    web, error = _parse(tmp_path, extra=f"roster_loading: {value}\n")

    assert error is None and web is not None
    assert web.roster_loading == value


def test_parse_normalizes_roster_read_when(tmp_path: Path) -> None:
    web, error = _parse(
        tmp_path,
        extra=(
            "roster_loading: on_demand\n"
            "roster_read_when:\n"
            "  - '  before writing a plan  '\n"
            "  - when performing research\n"
        ),
    )

    assert error is None and web is not None
    assert web.roster_read_when == (
        "before writing a plan",
        "when performing research",
    )


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        (
            "roster_loading: sometimes\n",
            "roster_loading must be always or on_demand",
        ),
        (
            "roster_loading: true\n",
            "roster_loading must be always or on_demand",
        ),
        (
            "roster_read_when: before planning\n",
            "roster_read_when must be a list of non-empty strings",
        ),
        (
            "roster_read_when:\n  - ''\n",
            "roster_read_when must be a list of non-empty strings",
        ),
        (
            "roster_read_when:\n  - 1\n",
            "roster_read_when must be a list of non-empty strings",
        ),
    ],
)
def test_parse_rejects_invalid_roster_loading_keys(
    tmp_path: Path, extra: str, expected: str
) -> None:
    web, error = _parse(tmp_path, extra=extra)

    assert web is None
    assert error is not None
    assert expected in error


def test_validation_reserves_roster_web_slug(tmp_path: Path) -> None:
    _seed(tmp_path, slug="roster", extra="roster_loading: always\n", strand_count=1)

    report = validate_memory_webs(discover_memory_webs(tmp_path))

    assert any("reserved" in blocker for blocker in report.blockers)


def test_validation_blocks_on_demand_without_description(tmp_path: Path) -> None:
    path = tmp_path / "sase" / "memory" / "runbooks.md"
    _write(
        path,
        "---\nweb: true\nroster: list\nroster_loading: on_demand\n---\n\n"
        "Authored preamble.\n",
    )
    _write(
        tmp_path / "sase" / "memory" / "runbooks" / "record-0.md",
        _strand(),
    )

    report = validate_memory_webs(discover_memory_webs(tmp_path))

    assert any("requires a description" in blocker for blocker in report.blockers)


def test_validation_blocks_on_demand_empty_authored_body(tmp_path: Path) -> None:
    _seed(
        tmp_path,
        extra="roster_loading: on_demand\n",
        body=f"{START_MARKER}\n{END_MARKER}\n",
        strand_count=1,
    )

    report = validate_memory_webs(discover_memory_webs(tmp_path))

    assert any(
        "empty outside the managed roster region" in blocker
        for blocker in report.blockers
    )


def test_validation_warns_on_demand_without_read_when(tmp_path: Path) -> None:
    _seed(tmp_path, extra="roster_loading: on_demand\n", strand_count=1)

    report = validate_memory_webs(discover_memory_webs(tmp_path))

    assert report.blockers == ()
    assert any("no roster_read_when" in warning for warning in report.warnings)


def test_validation_warns_read_when_on_always_web(tmp_path: Path) -> None:
    _seed(
        tmp_path,
        extra="roster_read_when:\n  - before writing a plan\n",
        strand_count=1,
    )

    report = validate_memory_webs(discover_memory_webs(tmp_path))

    assert report.blockers == ()
    assert any(
        "roster_read_when has no effect" in warning for warning in report.warnings
    )


def test_validation_warns_inline_on_demand(tmp_path: Path) -> None:
    _seed(
        tmp_path,
        extra="roster_loading: on_demand\n",
        roster="inline",
        strand_count=1,
    )

    report = validate_memory_webs(discover_memory_webs(tmp_path))

    assert report.blockers == ()
    assert any(
        "inline" in warning and "on_demand" in warning for warning in report.warnings
    )


def _pointer_web(tmp_path: Path, *, extra: str, strand_count: int):
    _seed(tmp_path, extra=extra, strand_count=strand_count)
    (web,) = discover_memory_webs(tmp_path).webs
    return web


def _expected_pointer(
    *,
    count: int,
    triggers: tuple[str, ...] = (),
    slug: str = "runbooks",
    label: str = "RECORDS",
    noun: str = "record",
) -> str:
    counted = noun if count == 1 else f"{noun}s"
    verb = "is" if count == 1 else "are"
    command = f'`sase memory read roster:{slug} -r "<why>"`'
    lead = f"**Roster on demand.** This web's {count} {counted} {verb} not listed here."
    if triggers:
        instruction = f"You MUST read the {label} roster with {command}:"
        bullets = "\n".join(f"- {trigger}" for trigger in triggers)
        body = f"{lead} {instruction}\n\n{bullets}"
    else:
        instruction = f"Read the {label} roster with {command} when you need one."
        body = f"{lead} {instruction}"
    footer = f'Read one {noun} with `sase memory read {slug}:<keyword> -r "<why>"`.'
    return wrap_markdown(f"{body}\n\n{footer}", width=markdown_print_width())


def test_pointer_text_plural_with_triggers(tmp_path: Path) -> None:
    web = _pointer_web(
        tmp_path,
        extra=(
            "roster_loading: on_demand\n"
            "roster_read_when:\n"
            "  - before writing a plan\n"
            "  - when performing research\n"
        ),
        strand_count=2,
    )

    assert render_on_demand_roster_pointer(web) == _expected_pointer(
        count=2,
        triggers=("before writing a plan", "when performing research"),
    )


def test_pointer_text_singular_without_triggers(tmp_path: Path) -> None:
    web = _pointer_web(tmp_path, extra="roster_loading: on_demand\n", strand_count=1)

    assert render_on_demand_roster_pointer(web) == _expected_pointer(count=1)


def test_pointer_text_zero_strands_uses_plural(tmp_path: Path) -> None:
    web = _pointer_web(tmp_path, extra="roster_loading: on_demand\n", strand_count=0)

    assert render_on_demand_roster_pointer(web) == _expected_pointer(count=0)


def test_projection_replaces_roster_and_keeps_on_disk_region(tmp_path: Path) -> None:
    web = _pointer_web(
        tmp_path,
        extra=(
            "roster_loading: on_demand\nroster_read_when:\n  - before writing a plan\n"
        ),
        strand_count=2,
    )

    projected, projected_error = render_web_projection_body(web)
    on_disk, on_disk_error = render_web_descriptor_with_roster(web)

    assert projected_error is None and projected is not None
    assert on_disk_error is None and on_disk is not None
    assert "Authored preamble." in projected
    assert "**Roster on demand.**" in projected
    assert "`sase memory read roster:runbooks" in projected
    assert START_MARKER not in projected
    assert END_MARKER not in projected
    assert "1. **Record 0**" not in projected
    assert "Strand body" not in projected
    assert START_MARKER in on_disk
    assert END_MARKER in on_disk
    assert "1. **Record 0**" in on_disk
    assert "Authored preamble." in on_disk
    assert "**Roster on demand.**" not in on_disk


def test_projection_appends_pointer_when_markers_are_absent(tmp_path: Path) -> None:
    _seed(
        tmp_path,
        extra="roster_loading: on_demand\n",
        body="Authored preamble.\n",
        strand_count=1,
    )
    (web,) = discover_memory_webs(tmp_path).webs

    projected, error = render_web_projection_body(web)

    assert error is None and projected is not None
    assert projected.startswith("Authored preamble.\n\n**Roster on demand.**")
    assert START_MARKER not in projected
    pointer = render_on_demand_roster_pointer(web)
    assert projected == f"Authored preamble.\n\n{pointer}\n"


def test_absent_key_and_explicit_always_match_today(tmp_path: Path) -> None:
    _seed(tmp_path, extra="", strand_count=2)
    (absent,) = discover_memory_webs(tmp_path).webs
    explicit = replace(absent, roster_loading="always")

    today, today_error = render_web_body_with_roster(absent)
    absent_projected, absent_error = render_web_projection_body(absent)
    explicit_projected, explicit_error = render_web_projection_body(explicit)

    assert today_error is None and today is not None
    assert absent_error is None and explicit_error is None
    assert absent_projected == strip_managed_roster_markers(today)
    assert explicit_projected == absent_projected
    assert "1. **Record 0**" in (absent_projected or "")
    assert "**Roster on demand.**" not in (absent_projected or "")
