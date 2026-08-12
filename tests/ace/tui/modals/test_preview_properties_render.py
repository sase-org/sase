"""Tests for the pure xprompt properties band/view renderers."""

from __future__ import annotations

from dataclasses import replace
from io import StringIO

from rich.console import Console, RenderableType

from sase.ace.tui.modals.preview_properties_render import (
    build_properties_band,
    build_properties_view,
)
from sase.xprompt.cli_show_model import ShowInput, ShowStep
from sase.xprompt.properties import XPromptProperties


def _properties(**overrides: object) -> XPromptProperties:
    base = XPromptProperties(
        reference="#demo",
        kind="xprompt",
        description=None,
        input_signature=None,
        inputs=[],
        local_xprompts=[],
        steps=[],
        tags=[],
        skill=None,
        skill_name=None,
        snippet=None,
        log_skill_use=None,
        memory_type=None,
        segment_count=1,
        project=None,
        source_bucket=None,
        definition_path=None,
    )
    return replace(base, **overrides)


def _plain(renderable: RenderableType) -> str:
    stream = StringIO()
    console = Console(
        file=stream,
        no_color=True,
        force_terminal=False,
        width=100,
        markup=False,
        emoji=False,
        highlight=False,
    )
    console.print(renderable)
    return stream.getvalue()


def test_build_properties_band_returns_none_for_empty_properties() -> None:
    assert build_properties_band(_properties()) is None


def test_build_properties_band_contains_input_name_type_and_default() -> None:
    properties = _properties(
        inputs=[ShowInput("project", "line", False, "sase", None, False, 0)],
    )

    rendered = _plain(build_properties_band(properties))

    assert "project" in rendered
    assert "line" in rendered
    assert "default: sase" in rendered


def test_build_properties_band_required_marker_only_for_required_inputs() -> None:
    properties = _properties(
        inputs=[
            ShowInput("target", "word", True, None, None, False, 0),
            ShowInput("notes", "text", False, None, None, False, 1),
        ],
    )

    rendered = _plain(build_properties_band(properties))

    assert "required" in rendered
    assert "optional" in rendered


def test_build_properties_band_overflow_shows_capped_rows_and_hint() -> None:
    inputs = [
        ShowInput(f"input{i}", "word", False, None, None, False, i) for i in range(9)
    ]
    properties = _properties(inputs=inputs)

    rendered = _plain(build_properties_band(properties, max_input_rows=6))

    for i in range(5):
        assert f"input{i}" in rendered
    for i in range(5, 9):
        assert f"input{i}" not in rendered
    assert "… +4 more" in rendered
    assert "p for all properties" in rendered


def test_build_properties_band_enum_marker_shows_choices() -> None:
    properties = _properties(
        inputs=[
            ShowInput(
                "mode",
                "enum",
                False,
                None,
                None,
                False,
                0,
                choices=("fast", "slow", "auto", "custom"),
            ),
        ],
    )

    rendered = _plain(build_properties_band(properties))

    assert "one of: fast, slow, auto, +1 more" in rendered


def test_build_properties_band_chips_include_only_applicable_signals() -> None:
    properties = _properties(
        tags=["bd"],
        skill=["claude"],
        steps=[ShowStep(1, "run", "agent", "Do it", False, None, None)],
        segment_count=3,
    )

    rendered = _plain(build_properties_band(properties))

    assert "tags: bd" in rendered
    assert "skill: claude" in rendered
    assert "1 step" in rendered
    assert "swarm · 3 segments" in rendered


def test_build_properties_band_chips_omit_signals_that_do_not_apply() -> None:
    properties = _properties(description="just words, nothing else declared here")

    rendered = _plain(build_properties_band(properties))

    assert "tags" not in rendered
    assert "skill" not in rendered
    assert "step" not in rendered
    assert "swarm" not in rendered


def test_build_properties_view_renders_every_input_without_truncation() -> None:
    inputs = [
        ShowInput(f"input{i}", "word", False, None, None, False, i) for i in range(9)
    ]
    properties = _properties(inputs=inputs)

    rendered = _plain(build_properties_view(properties))

    for i in range(9):
        assert f"input{i}" in rendered
    assert "more" not in rendered
