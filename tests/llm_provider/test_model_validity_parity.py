"""Parity between the Rust model classifier and the runtime `%model` path.

The classifier (:func:`classify_model_value` over
:func:`model_validity_snapshot`) must agree with the launch path
(:func:`resolve_model_provider_with_effort` with ``consume=False`` plus the
``%model`` directive parser): accepted tokens route to a provider and parse,
rejected tokens either resolve to no provider or fail directive parsing.
Neither side moves the load-balance cursor.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding
from sase.llm_provider import config as llm_config
from sase.llm_provider import model_alias_config
from sase.llm_provider import registry
from sase.llm_provider.model_validity import (
    clear_model_validity_snapshot_cache,
    model_validity_snapshot,
)
from sase.macro.directives import extract_prompt_directives
from sase.macro.effort import EFFORT_LEVELS_ORDERED

FIXTURE_PROVIDERS = ["claude", "codex", "fakey"]
FIXTURE_MODELS = {
    "opus": "claude",
    "sonnet": "claude",
    "gpt-5.6-sol": "codex",
    "fakey-large": "fakey",
}
FIXTURE_ALIASES = {"large", "medium", "xlarge"}

ACCEPTED_TOKENS = (
    "@large",
    "claude/opus@xhigh",
    "codex/new-model",
    "fakey-large",
    "fakey/fakey-large",
)


@pytest.fixture
def fixture_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Serve one fixture world to the snapshot builder and the resolver."""
    monkeypatch.setattr(registry, "_provider_names", lambda: list(FIXTURE_PROVIDERS))
    monkeypatch.setattr(
        registry, "registered_provider_names", lambda: list(FIXTURE_PROVIDERS)
    )
    monkeypatch.setattr(registry, "model_to_provider_map", lambda: dict(FIXTURE_MODELS))
    monkeypatch.setattr(
        model_alias_config, "model_alias_names", lambda: set(FIXTURE_ALIASES)
    )
    monkeypatch.setattr(llm_config, "model_alias_names", lambda: set(FIXTURE_ALIASES))
    clear_model_validity_snapshot_cache()
    yield
    clear_model_validity_snapshot_cache()


def _cursor_bytes() -> bytes | None:
    path = Path(sase_home()) / "llm_lb.json"
    if not path.exists():
        return None
    return path.read_bytes()


def test_model_classifier_parity_with_resolver_and_directives(
    fixture_registry: None,
) -> None:
    cursor_before = _cursor_bytes()

    snapshot = model_validity_snapshot(use_cache=False)
    assert snapshot == {
        "schema_version": 1,
        "providers": FIXTURE_PROVIDERS,
        "models": dict(sorted(FIXTURE_MODELS.items())),
        "aliases": sorted(FIXTURE_ALIASES),
        "effort_levels": list(EFFORT_LEVELS_ORDERED),
    }

    classify = require_rust_binding("classify_model_value")

    for token in ACCEPTED_TOKENS:
        result = classify({"name": "m", "value": token, "snapshot": snapshot})
        assert result["ok"], token
        provider, _model, _effort = registry.resolve_model_provider_with_effort(
            token, consume=False
        )
        assert provider is not None, token
        extract_prompt_directives(f"%model:{token}")

    rejected = {
        "opsu": ["opus"],
        "@lareg": ["@large"],
        "large": ["@large"],
        "cluade/opus": [],
        "opus@turbo": [],
    }
    for token, expected_suggestions in rejected.items():
        result = classify({"name": "m", "value": token, "snapshot": snapshot})
        assert not result["ok"], token
        for suggestion in expected_suggestions:
            assert suggestion in result["suggestions"], (token, result)
        try:
            provider, _model, _effort = registry.resolve_model_provider_with_effort(
                token, consume=False
            )
        except Exception:  # noqa: BLE001 - either side may reject.
            provider = None
        try:
            extract_prompt_directives(f"%model:{token}")
            parsed = True
        except Exception:  # noqa: BLE001 - either side may reject.
            parsed = False
        assert provider is None or not parsed, token

    assert (
        "did you mean `opus`"
        in classify({"name": "m", "value": "opsu", "snapshot": snapshot})["message"]
    )
    assert (
        "model aliases need `@`"
        in classify({"name": "m", "value": "large", "snapshot": snapshot})["message"]
    )
    assert (
        "provider `cluade` is not installed"
        in classify({"name": "m", "value": "cluade/opus", "snapshot": snapshot})[
            "message"
        ]
    )
    assert (
        "is not an effort level"
        in classify({"name": "m", "value": "opus@turbo", "snapshot": snapshot})[
            "message"
        ]
    )

    # `%model:opsu` still parses and still falls back at launch.
    extract_prompt_directives("%model:opsu")
    provider, _model, _effort = registry.resolve_model_provider_with_effort(
        "opsu", consume=False
    )
    assert provider is None

    assert _cursor_bytes() == cursor_before
