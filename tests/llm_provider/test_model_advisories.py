"""Tests for the provider-neutral ``llm_model_advisories`` hook.

Covers registry normalization (including malformed third-party input), the
Muse Contributor advisory itself, the guard keeping advisory models out of the
tier mapping, and the three surfaces that render an advisory.
"""

from __future__ import annotations

from typing import Any

import pytest

from sase.llm_provider._registry_metadata import provider_metadata
from sase.llm_provider.model_label import model_value_text
from sase.llm_provider.muse import _TIER_TO_MODEL, MuseProvider
from sase.llm_provider.registry import model_advisory_for, model_advisory_map

_CONTRIBUTOR = "muse-spark-1.2-contributor"


class _Plugin:
    """Minimal stand-in for a provider plugin instance."""

    def __init__(self, advisories: Any) -> None:
        self._advisories = advisories

    def llm_provider_name(self) -> str:
        return "fake"

    def llm_model_advisories(self) -> Any:
        return self._advisories


def _advisories_for(value: Any) -> dict[str, dict[str, str]]:
    return provider_metadata("fake", _Plugin(value))["model_advisories"]


# --- Normalization ---------------------------------------------------------


def test_advisory_is_normalized_from_the_hook() -> None:
    advisories = _advisories_for(
        {"m1": {"severity": "warn", "label": "short", "detail": "a sentence"}}
    )

    assert advisories == {
        "m1": {"severity": "warn", "label": "short", "detail": "a sentence"}
    }


def test_provider_without_the_hook_stays_valid() -> None:
    class _Bare:
        def llm_provider_name(self) -> str:
            return "bare"

    metadata = provider_metadata("bare", _Bare())

    assert metadata["model_advisories"] == {}
    assert metadata["provider_name"] == "bare"


def test_raising_hook_degrades_to_no_advisories() -> None:
    class _Boom:
        def llm_model_advisories(self) -> dict[str, dict[str, str]]:
            raise RuntimeError("third-party plugin exploded")

    assert provider_metadata("boom", _Boom())["model_advisories"] == {}


@pytest.mark.parametrize(
    "value",
    [
        None,
        "not-a-dict",
        [("m1", {"label": "x"})],
        {"m1": "not-a-dict"},
        {"m1": {"detail": "no label means nothing to render"}},
        {"m1": {"label": "   "}},
        {"  ": {"label": "blank model id"}},
    ],
)
def test_malformed_advisories_are_dropped_not_raised(value: Any) -> None:
    assert _advisories_for(value) == {}


def test_unknown_severity_degrades_to_info() -> None:
    advisories = _advisories_for({"m1": {"severity": "catastrophe", "label": "x"}})

    assert advisories["m1"]["severity"] == "info"
    assert advisories["m1"]["detail"] == ""


def test_one_bad_entry_does_not_drop_its_siblings() -> None:
    advisories = _advisories_for({"good": {"label": "kept"}, "bad": 7})

    assert set(advisories) == {"good"}


# --- Muse's Contributor advisory ------------------------------------------


def test_muse_flags_the_contributor_model() -> None:
    advisories = MuseProvider().llm_model_advisories()

    assert set(advisories) == {_CONTRIBUTOR}
    assert advisories[_CONTRIBUTOR]["severity"] == "warn"
    assert advisories[_CONTRIBUTOR]["label"] == "trains on your data"
    assert "train" in advisories[_CONTRIBUTOR]["detail"]


def test_registry_publishes_the_contributor_advisory() -> None:
    assert model_advisory_map()[_CONTRIBUTOR]["label"] == "trains on your data"
    assert model_advisory_for(_CONTRIBUTOR) is not None
    assert model_advisory_for("muse-spark-1.2") is None
    assert model_advisory_for(None) is None


def test_tier_mapping_never_routes_to_an_advisory_model() -> None:
    """SASE must not opt a user into training terms on their behalf.

    ``small`` phases route directly to the ``@small`` built-in alias, so a
    future cost optimization pointing a tier at the Contributor model would
    silently ship proprietary source into Meta's training corpus.
    """
    advisory_models = set(MuseProvider().llm_model_advisories())

    assert advisory_models
    assert not advisory_models & set(_TIER_TO_MODEL.values())


# --- Render sites ----------------------------------------------------------


def test_model_picker_row_carries_the_advisory() -> None:
    from sase.ace.tui.modals.model_picker_rows import build_model_rows

    rows = {row.model_id: row for row in build_model_rows() if row.is_model}

    flagged = rows[_CONTRIBUTOR]
    assert flagged.advisory_label == "trains on your data"
    assert flagged.advisory_severity == "warn"
    assert "⚠ trains on your data" in flagged.label
    assert flagged.description is not None and "train" in flagged.description
    # The detail is searchable, so filtering on the terms finds the row.
    assert any("trains on your data" in term for term in flagged.search_terms)

    assert rows["muse-spark-1.2"].advisory_label is None
    assert "⚠" not in rows["muse-spark-1.2"].label


def test_model_picker_option_renders_the_advisory() -> None:
    from sase.ace.tui.modals.model_picker_options import build_model_options

    options = {
        option.id: str(option.prompt) for option in build_model_options() if option
    }

    assert "⚠ trains on your data" in options[_CONTRIBUTOR]
    assert "⚠" not in options["muse-spark-1.2"]


def test_model_completion_detail_carries_the_advisory() -> None:
    from sase.xprompt.model_completion import build_model_completion_catalog

    entries = {
        entry.value: entry
        for entry in build_model_completion_catalog(use_cache=False)
        if entry.kind == "model"
    }

    flagged = entries[_CONTRIBUTOR]
    assert flagged.advisory_label == "trains on your data"
    assert flagged.advisory_severity == "warn"
    assert "⚠ trains on your data" in flagged.description

    assert entries["muse-spark-1.2"].advisory_label == ""
    assert "⚠" not in entries["muse-spark-1.2"].description


def test_model_completion_payload_exposes_the_advisory() -> None:
    from sase.xprompt.model_completion import model_completion_catalog_payload

    entries = {
        entry["value"]: entry
        for entry in model_completion_catalog_payload()["entries"]  # type: ignore[index]
    }

    assert entries[_CONTRIBUTOR]["advisory_label"] == "trains on your data"
    assert entries["muse-spark-1.2"]["advisory_label"] == ""


def test_model_label_marks_an_active_advisory_model() -> None:
    flagged = model_value_text(_CONTRIBUTOR, "muse", "high")
    plain = model_value_text("muse-spark-1.2", "muse", "high")

    assert flagged is not None and plain is not None
    assert flagged.plain == f"MUSE({_CONTRIBUTOR}) ⚠ @ high"
    assert plain.plain == "MUSE(muse-spark-1.2) @ high"
