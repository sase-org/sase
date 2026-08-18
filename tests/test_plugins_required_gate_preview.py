"""Rendering coverage for the PluginsRequired gate's Markdown preview and note."""

from __future__ import annotations

from types import SimpleNamespace

from sase.plugins._required_gate_preview import (
    plugins_required_presentation_note,
    render_plugins_required_preview,
)

from tests.test_plugins_required_gate_helpers import missing_entry


def _payload(**overrides: object) -> SimpleNamespace:
    fields: dict[str, object] = {
        "project": "sase",
        "project_label": "sase",
        "missing": [missing_entry()],
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_preview_is_byte_identical_across_two_renders_of_the_same_payload() -> None:
    payload = _payload()
    assert render_plugins_required_preview(payload) == render_plugins_required_preview(
        payload
    )


def test_preview_uses_pinned_label_not_the_project_key() -> None:
    preview = render_plugins_required_preview(
        _payload(project="gh_sase-org__sase", project_label="sase")
    )
    assert "gh_sase-org__sase" not in preview
    assert "**Project:** sase" in preview


def test_preview_lists_each_requirement_and_notes_axe_restart() -> None:
    preview = render_plugins_required_preview(
        _payload(
            missing=[
                missing_entry(),
                missing_entry(
                    requirement="sase-research-artifacts>=0.2",
                    name="sase-research-artifacts",
                    kind="version_mismatch",
                    install_command="sase plugin install sase-research-artifacts",
                ),
            ]
        )
    )
    assert "sase-github" in preview
    assert "sase-research-artifacts" in preview
    assert "not installed" in preview
    assert "installed version does not match" in preview
    assert "`sase plugin install sase-github`" in preview
    assert "successful install restarts axe" in preview
    assert "fail closed" in preview


def test_presentation_note_names_count_and_project() -> None:
    note = plugins_required_presentation_note(
        _payload(
            missing=[
                missing_entry(),
                missing_entry(name="sase-research-artifacts"),
            ]
        )
    )
    assert note == "2 required plugins to install · sase"


def test_presentation_note_singular_for_one_plugin() -> None:
    assert plugins_required_presentation_note(_payload()) == (
        "1 required plugin to install · sase"
    )
