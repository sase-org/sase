from __future__ import annotations

from pathlib import Path

from tests.main.init_skills_handler_helpers import collapse_whitespace


ROOT = Path(__file__).resolve().parents[1]


def test_getting_started_muse_grok_wording_separates_provider_selection() -> None:
    text = collapse_whitespace(
        (ROOT / "docs/getting_started.md").read_text(encoding="utf-8")
    )

    assert "never auto-detects `muse` or `grok` from PATH" in text
    assert (
        "Grok Build can still be reached automatically through the shipped `@xsmall`, "
        "`@small`, and `@medium` pools"
    ) in text
    assert "as the last `@xlarge` fallback candidate" in text
    assert "explicit-only and never auto-detected" not in text


def test_xprompt_model_comments_avoid_overloaded_explicit_only_wording() -> None:
    text = (ROOT / "docs/xprompt.md").read_text(encoding="utf-8")

    assert "%model:muse/muse-spark-1.2" in text
    assert "Meta Muse Code — never auto-detected from PATH" in text
    assert "%model:grok/grok-4.6" in text
    assert "xAI Grok Build — never auto-detected; also in alias pools" in text
    assert "explicit-only, never auto-detected" not in text
