"""Tests for the Rich xprompt show layout."""

from __future__ import annotations

from dataclasses import replace
from io import StringIO

from rich.console import Console

from sase.xprompt.cli_show_model import (
    ShowInput,
    ShowLocalXPrompt,
    ShowProvenance,
    ShowReference,
    ShowStep,
    XPromptShowRecord,
)
from sase.xprompt.cli_show_render import render_show
from sase.xprompt.highlight_theme import highlight_theme


def _record(**overrides: object) -> XPromptShowRecord:
    base = XPromptShowRecord(
        name="demo",
        reference="#demo",
        prefix="#",
        kind="xprompt",
        is_skill=False,
        is_swarm=False,
        segment_count=1,
        description=None,
        project="sase",
        provenance=ShowProvenance(
            source_id="project:demo",
            source_bucket="project",
            source_display="sase/xprompts/demo.md",
            definition_path="/work/sase/xprompts/demo.md",
            definition_line=1,
            hosted_url=None,
            editable=True,
        ),
        tags=[],
        skill=None,
        snippet=None,
        log_skill_use=None,
        input_signature=None,
        inputs=[],
        local_xprompts=[],
        steps=[],
        body=None,
        body_first_line=None,
        raw="",
        warnings=[],
        references=[],
    )
    return replace(base, **overrides)


def _render(record: XPromptShowRecord, *, color: bool, width: int = 100) -> str:
    stream = StringIO()
    console = Console(
        file=stream,
        no_color=not color,
        force_terminal=color,
        color_system="256",
        width=width,
        markup=False,
        emoji=False,
        highlight=False,
    )
    render_show(record, console=console)
    return stream.getvalue()


def _rstrip_lines(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.splitlines())


def test_plain_layout_covers_every_xprompt_section() -> None:
    record = _record(
        is_swarm=True,
        segment_count=2,
        description="A literal [bold]description[/bold].",
        tags=["demo", "reading"],
        skill=False,
        snippet=False,
        input_signature="(topic: text)",
        inputs=[
            ShowInput("topic", "text", True, None, "What to find.", False, 0),
            ShowInput(
                "query",
                "text",
                False,
                "first line\nsecond line",
                None,
                False,
                1,
            ),
        ],
        local_xprompts=[ShowLocalXPrompt("_helper", None, None, 3)],
        body="%model(test)\n#_helper\n---",
        body_first_line=45,
        warnings=["hosted URL unavailable"],
        references=[
            ShowReference("#_helper", "_helper", None, True, "local helper"),
            ShowReference("#missing", "missing", None, False, None),
        ],
    )

    rendered = _rstrip_lines(_render(record, color=False))

    assert "#demo" in rendered
    assert "xprompt · swarm · 2 segments" in rendered
    assert "A literal [bold]description[/bold]." in rendered
    assert "PROPERTIES" in rendered
    assert "INPUTS  #demo(topic: text)" in rendered
    assert "default: first line …" in rendered
    assert "LOCAL XPROMPTS" in rendered
    assert " 45 │ %model(test)" in rendered
    assert "REFERENCES" in rendered
    assert "#missing  unknown" in rendered
    assert "✗" in rendered
    assert "WARNINGS\n  hosted URL unavailable" in rendered
    assert "sase xprompt expand '#demo'   preview the expansion" in rendered
    assert "\x1b" not in rendered


def test_color_output_uses_shared_role_styles() -> None:
    record = _record(body="#foo\n%model(test)\n---")

    rendered = _render(record, color=True)
    styles = highlight_theme()

    assert styles["xprompt.invocation"].ansi_sgr in rendered
    assert styles["xprompt.directive"].ansi_sgr in rendered
    assert styles["xprompt.separator"].ansi_sgr in rendered


def test_empty_sections_are_omitted() -> None:
    rendered = _render(_record(), color=False)

    assert "INPUTS" not in rendered
    assert "LOCAL XPROMPTS" not in rendered
    assert "WORKFLOW STEPS" not in rendered
    assert "DEFINITION" not in rendered
    assert "REFERENCES" not in rendered
    assert "WARNINGS" not in rendered


def test_workflow_steps_render_bodies_and_explicit_elision() -> None:
    step_body = "\n".join(f"print({line})" for line in range(23))
    record = _record(
        kind="embeddable_workflow",
        reference="#flow",
        name="flow",
        input_signature="(topic: text)",
        steps=[
            ShowStep(
                index=1,
                name="compute",
                type="python",
                label="print(0)",
                hidden=False,
                condition="ready",
                output_schema={"type": "object"},
                body=step_body,
            )
        ],
        body="#final",
    )

    rendered = _render(record, color=False)

    assert "WORKFLOW STEPS" in rendered
    assert "compute  python · if ready" in rendered
    assert "print(19)" in rendered
    assert "print(20)" not in rendered
    assert "… (3 more lines)" in rendered
    assert "DEFINITION" in rendered
    assert "sase xprompt explain flow" in rendered


def test_definition_unknown_is_explicit_placeholder() -> None:
    provenance = ShowProvenance(
        source_id=None,
        source_bucket="config",
        source_display=None,
        definition_path=None,
        definition_line=None,
        hosted_url=None,
        editable=False,
    )

    rendered = _render(_record(provenance=provenance), color=False)

    assert "definition    (unknown)" in rendered
