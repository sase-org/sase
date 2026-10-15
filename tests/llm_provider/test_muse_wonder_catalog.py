"""End-to-end manifest coverage for the Muse Wonder model catalog."""

from __future__ import annotations

from sase.ace.tui.modals.model_picker_rows import build_model_rows
from sase.llm_provider.model_label import model_value_text
from sase.llm_provider.registry import resolve_model_provider
from sase.macro.model_completion import (
    build_model_completion_catalog,
    filter_explicit_model_shortcut_entries,
    filter_model_completion_entries,
    model_completion_catalog_payload,
)

_WONDER_MODELS = (
    "muse-wonder-1.0",
    "muse-wonder-1.0-contributor",
    "muse-wonder-full-1.0",
    "muse-wonder-full-1.0-contributor",
)


def test_wonder_models_resolve_from_the_real_manifest() -> None:
    assert resolve_model_provider("muse/muse-wonder-full-1.0") == (
        "muse",
        "muse-wonder-full-1.0",
    )
    assert resolve_model_provider("muse-wonder-1.0") == (
        "muse",
        "muse-wonder-1.0",
    )


def test_model_picker_rows_include_wonder_aliases_and_advisories() -> None:
    rows = {row.model_id: row for row in build_model_rows() if row.is_model}
    for model, alias in zip(
        _WONDER_MODELS,
        ("wonder10", "wonder10c", "wonderfull10", "wonderfull10c"),
        strict=True,
    ):
        assert rows[model].provider == "muse"
        assert rows[model].alias == alias
        assert f"({alias})" in rows[model].label

    assert rows["muse-wonder-full-1.0"].advisory_severity == "info"
    assert "ⓘ needs Power plan or higher" in rows["muse-wonder-full-1.0"].label
    assert rows["muse-wonder-1.0"].advisory_label is None


def test_completion_catalog_and_rust_filters_include_wonder_models() -> None:
    entries = build_model_completion_catalog(use_cache=False)
    muse_entries = [entry for entry in entries if entry.provider == "muse"]
    wonder_entries = [entry for entry in muse_entries if entry.value in _WONDER_MODELS]

    assert tuple(entry.value for entry in wonder_entries) == _WONDER_MODELS
    assert wonder_entries[0].aliases == ("wonder10",)
    assert wonder_entries[2].aliases == ("wonderfull10",)
    full = next(
        entry for entry in wonder_entries if entry.value == "muse-wonder-full-1.0"
    )
    assert "ⓘ needs Power plan or higher" in full.description

    scoped = filter_model_completion_entries(entries, "muse/wonder")
    assert {
        entry.value.removeprefix("muse/") for entry in scoped if entry.kind == "model"
    } == set(_WONDER_MODELS)
    shortcut = filter_explicit_model_shortcut_entries(entries, "wonderf")
    assert {entry.value for entry in shortcut} == {
        "muse-wonder-full-1.0",
        "muse-wonder-full-1.0-contributor",
    }


def test_lsp_payload_exposes_wonder_aliases_and_advisories() -> None:
    payload = model_completion_catalog_payload()
    raw_entries = payload["entries"]
    assert isinstance(raw_entries, list)
    entries = {entry["value"]: entry for entry in raw_entries}

    assert entries["muse-wonder-1.0"]["aliases"] == ["wonder10"]
    assert entries["muse-wonder-1.0"]["advisory_label"] == ""
    assert entries["muse-wonder-full-1.0"]["advisory_label"] == (
        "needs Power plan or higher"
    )
    assert entries["muse-wonder-1.0-contributor"]["advisory_label"] == (
        "trains on your data"
    )


def test_model_label_marks_wonder_full_plan_advisory() -> None:
    label = model_value_text("muse-wonder-full-1.0", "muse", "high")
    assert label is not None
    assert label.plain == "MUSE(muse-wonder-full-1.0) ⓘ @ high"
