"""Tests for the ``llm.model_advisory`` doctor check."""

from __future__ import annotations

from typing import Any

import pytest

from sase.doctor.checks_providers_advisory import check_llm_model_advisory
from sase.llm_provider.alias_view import AliasView

_FLAGGED = "muse-spark-1.2-contributor"
_ADVISORY = {
    "severity": "warn",
    "label": "trains on your data",
    "detail": "Meta trains on this model's inputs and outputs.",
}


def _view(name: str, provider: str, model: str) -> AliasView:
    return AliasView(
        name=name,
        kind="role",
        configured=True,
        configured_value=f"{provider}/{model}",
        provider=provider,
        model=model,
        override=None,
    )


@pytest.fixture
def routes(monkeypatch: pytest.MonkeyPatch):
    """Pin the alias snapshot and default-provider resolution doctor reads."""

    def _install(
        views: list[AliasView],
        *,
        advisories: dict[str, dict[str, str]] | None = None,
        resolutions: dict[str, str] | None = None,
    ) -> None:
        monkeypatch.setattr(
            "sase.llm_provider.alias_view.build_alias_views",
            lambda **_kwargs: views,
        )
        monkeypatch.setattr(
            "sase.llm_provider.registry.model_advisory_map",
            lambda: {_FLAGGED: dict(_ADVISORY)} if advisories is None else advisories,
        )
        monkeypatch.setattr(
            "sase.llm_provider.registry.get_default_provider_name",
            lambda: "muse",
        )
        payload: dict[str, Any] = {
            "providers": {
                "muse": {
                    "model_resolutions": resolutions or {"large": "muse-spark-1.2"}
                }
            }
        }
        monkeypatch.setattr(
            "sase.llm_provider.registry.get_llm_metadata_payload",
            lambda: payload,
        )

    return _install


def test_ok_when_no_provider_flags_a_model(routes) -> None:
    routes([_view("default", "muse", "muse-spark-1.2")], advisories={})

    check = check_llm_model_advisory()

    assert check.id == "llm.model_advisory"
    assert check.status == "OK"
    assert "no registered provider flags" in check.summary


def test_ok_when_nothing_routes_to_a_flagged_model(routes) -> None:
    routes([_view("default", "muse", "muse-spark-1.2")])

    check = check_llm_model_advisory()

    assert check.status == "OK"
    assert check.details == ()
    assert list(check.data["advisory_models"]) == [_FLAGGED]


def test_warns_for_a_configured_alias_and_quotes_the_detail(routes) -> None:
    routes(
        [
            _view("default", "muse", "muse-spark-1.2"),
            _view("cheap", "muse", _FLAGGED),
        ]
    )

    check = check_llm_model_advisory()

    assert check.status == "WARN"
    assert check.summary == "1 configured route(s) resolve to an advisory-flagged model"
    assert check.details == (
        f"@cheap -> muse/{_FLAGGED}: Meta trains on this model's inputs and outputs.",
    )
    finding = check.data["findings"][0]
    assert finding["source"] == "@cheap"
    assert finding["model"] == _FLAGGED
    assert finding["severity"] == "warn"
    assert check.next_steps


def test_warns_when_the_default_provider_tier_lands_on_a_flagged_model(routes) -> None:
    routes([], resolutions={"large": _FLAGGED, "small": _FLAGGED})

    check = check_llm_model_advisory()

    assert check.status == "WARN"
    sources = {finding["source"] for finding in check.data["findings"]}
    assert sources == {"muse large tier", "muse small tier"}


def test_registry_failure_reports_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> dict[str, dict[str, str]]:
        raise RuntimeError("registry is broken")

    monkeypatch.setattr(
        "sase.llm_provider.registry.model_advisory_map",
        _boom,
    )

    check = check_llm_model_advisory()

    assert check.status == "ERROR"
    assert "RuntimeError: registry is broken" in check.details[0]
