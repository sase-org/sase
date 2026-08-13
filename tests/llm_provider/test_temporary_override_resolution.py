"""Tests for temporary LLM override provider/model resolution."""

from __future__ import annotations

import json
import time

from sase.llm_provider.temporary_override import (
    resolve_effective_default_provider_model,
    set_temporary_override,
)
from sase.llm_provider.temporary_override_state import state_path


# ---------------------------------------------------------------------------
# resolve_effective_default_provider_model
# ---------------------------------------------------------------------------


def test_resolve_effective_default_no_override() -> None:
    provider, model = resolve_effective_default_provider_model()
    assert provider in {"claude", "codex", "gemini"}
    assert isinstance(model, str) and model


def test_resolve_effective_default_with_override() -> None:
    set_temporary_override("codex/o3", 3600.0, source="ace")
    provider, model = resolve_effective_default_provider_model()
    assert provider == "codex"
    assert model == "o3"


def test_resolve_effective_default_ignores_expired_override() -> None:
    set_temporary_override("codex/o3", 60.0, source="ace")
    # Force the override to be in the past by rewriting the v2 state entry.
    path = state_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["overrides"]["default"]["expires_at"] = time.time() - 1
    path.write_text(json.dumps(data), encoding="utf-8")

    provider, _ = resolve_effective_default_provider_model()
    assert provider != "codex" or _ != "o3"
    # And the stale state file is cleaned up by the read.
    assert not path.exists()
