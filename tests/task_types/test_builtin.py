from __future__ import annotations

from typing import Any

from rich.cells import cell_len

from sase.task_types._builtin import _builtin_task_type_specs
from sase.task_types._validation import validate_task_type_spec


_EXPECTED_ACCENTS = {
    "bug": "#FF5F5F",
    "ci": "#D7D700",
    "feature": "#5FD75F",
    "flake": "#00D7D7",
    "memory": "#8787FF",
}
_EXPECTED_GLYPHS = {
    "bug": "⨯",
    "ci": "⚙",
    "feature": "✦",
    "flake": "≈",
    "memory": "▤",
}
_EXPECTED_FIELDS = {
    "bug": ("location", "repro", "impact"),
    "ci": ("node_id", "sha", "why_not_flake"),
    "feature": ("proposal", "why_out_of_scope"),
    "flake": ("node_id", "repro_cmd", "evidence"),
    "memory": ("path", "proposed_change"),
}


def _by_slug() -> dict[str, dict[str, Any]]:
    return {spec["task_type"]: spec for spec in _builtin_task_type_specs()}


def test_builtin_catalog_has_the_five_planned_slugs() -> None:
    assert list(_by_slug()) == ["bug", "ci", "feature", "flake", "memory"]


def test_every_builtin_spec_validates_and_has_a_stable_digest() -> None:
    for spec in _builtin_task_type_specs():
        first = validate_task_type_spec(spec)
        second = validate_task_type_spec(spec)
        assert first == second
        assert len(first) == 64


def test_builtin_glyphs_and_accents_match_the_hand_tuned_set() -> None:
    for slug, spec in _by_slug().items():
        assert spec["glyph"] == _EXPECTED_GLYPHS[slug]
        assert spec["accent_color"] == _EXPECTED_ACCENTS[slug]
        assert cell_len(spec["glyph"]) == 1


def test_builtin_summaries_and_when_to_use_fit_the_caps() -> None:
    for spec in _builtin_task_type_specs():
        summary = spec["summary"]
        when_to_use = spec["when_to_use"]
        assert "\n" not in summary
        assert len(summary) <= 120
        assert len(when_to_use) <= 400
        assert summary == summary.strip()
        assert when_to_use == when_to_use.strip()


def test_builtin_field_names_and_required_flags_match_the_plan() -> None:
    specs = _by_slug()
    for slug, names in _EXPECTED_FIELDS.items():
        fields = {field["name"]: field for field in specs[slug]["fields"]}
        assert tuple(fields) == names
    assert specs["bug"]["fields"][0]["required"] is True
    assert specs["bug"]["fields"][1]["required"] is True
    assert specs["bug"]["fields"][2]["required"] is False
    assert specs["ci"]["fields"][0]["required"] is True
    assert specs["ci"]["fields"][1]["required"] is False
    assert specs["ci"]["fields"][1]["role"] == ["data"]
    assert specs["ci"]["fields"][2]["required"] is True
    assert specs["feature"]["fields"][0]["required"] is True
    assert specs["feature"]["fields"][1]["required"] is True
    assert specs["flake"]["fields"][0]["pattern"] == r"\S+::\S+"
    assert specs["flake"]["fields"][1]["required"] is False
    assert specs["flake"]["fields"][2]["required"] is True
    assert specs["memory"]["fields"][0]["required"] is True
    assert specs["memory"]["fields"][1]["required"] is True


def test_flake_requires_corroboration_and_ci_does_not() -> None:
    specs = _by_slug()
    assert specs["flake"]["triage"]["min_plus_ones"] == 1
    assert specs["ci"]["triage"]["min_plus_ones"] == 0
    assert "triage" not in specs["bug"]
    assert "triage" not in specs["feature"]
    assert "triage" not in specs["memory"]


def test_builtins_leave_default_size_unset_and_stay_agent_creatable() -> None:
    for spec in _builtin_task_type_specs():
        assert "default_size" not in spec
        assert spec.get("agent_creatable", True) is True


def test_memory_when_to_use_names_the_close_ritual() -> None:
    when_to_use = _by_slug()["memory"]["when_to_use"]
    assert "explicit user permission" in when_to_use
    assert "sase memory init" in when_to_use
