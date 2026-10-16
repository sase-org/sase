from __future__ import annotations

from pathlib import Path

from tests.main.init_skills_handler_helpers import collapse_whitespace


ROOT = Path(__file__).resolve().parents[1]


def test_provider_reference_separates_muse_and_grok_selection() -> None:
    text = collapse_whitespace(
        (ROOT / "docs/reference/providers/agent-clis.md").read_text(encoding="utf-8")
    )

    assert "SASE never auto-detects it" in text
    assert "Model-alias routing is separate" in text
    assert "Default provider autodetection never selects it" in text


def test_macro_model_comments_avoid_overloaded_explicit_only_wording() -> None:
    text = (ROOT / "docs/macros.md").read_text(encoding="utf-8")

    assert "%model:muse/muse-spark-1.3" in text
    assert "Meta Muse Code — never auto-detected from PATH" in text
    assert "%model:grok/grok-4.7" in text
    assert "xAI Grok Build — never auto-detected; also in alias selectors" in text
    assert "explicit-only, never auto-detected" not in text
