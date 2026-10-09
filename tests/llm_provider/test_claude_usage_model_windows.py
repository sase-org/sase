"""Focused Claude usage-window model attribution tests (Haiku 5.5)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sase.llm_provider.usage._claude_support import parse_usage_windows

OBSERVED_AT = datetime(
    2026,
    9,
    7,
    18,
    0,
    tzinfo=ZoneInfo("America/New_York"),
).timestamp()

_RESET = "resets Sep 12 at 8pm (America/New_York)"


def _windows(text: str) -> tuple[list[dict[str, object]], str | None]:
    return parse_usage_windows(text, observed_at=OBSERVED_AT)


def test_haiku_5_5_row_attributes_to_weekly_model_window() -> None:
    """An explicit Haiku 5.5 row maps to its own weekly model window."""
    text = f"Current week (Haiku 5.5): 40% used · {_RESET}"
    windows, diagnostic = _windows(text)

    assert diagnostic is None
    assert len(windows) == 1
    assert windows[0]["key"] == "weekly:claude-haiku-5-5"
    assert windows[0]["applicability"] == {
        "kind": "models",
        "model_ids": ["claude-haiku-5-5"],
    }


def test_haiku_4_5_row_still_attributes_to_weekly_model_window() -> None:
    """An explicit Haiku 4.5 row keeps its own weekly model window."""
    text = f"Current week (Haiku 4.5): 30% used · {_RESET}"
    windows, diagnostic = _windows(text)

    assert diagnostic is None
    assert len(windows) == 1
    assert windows[0]["key"] == "weekly:claude-haiku-4-5"
    assert windows[0]["applicability"] == {
        "kind": "models",
        "model_ids": ["claude-haiku-4-5"],
    }


def test_bare_haiku_row_attributes_to_current_haiku() -> None:
    """A bare Haiku row means the current Haiku (5.5)."""
    text = f"Current week (Haiku): 35% used · {_RESET}"
    windows, diagnostic = _windows(text)

    assert diagnostic is None
    assert len(windows) == 1
    assert windows[0]["key"] == "weekly:claude-haiku-5-5"
    assert windows[0]["applicability"] == {
        "kind": "models",
        "model_ids": ["claude-haiku-5-5"],
    }


def test_combined_probe_yields_distinct_model_windows() -> None:
    """All-models, Fable, and both Haiku rows parse to distinct keys."""
    text = "\n".join(
        [
            f"Current week (all models): 25% used · {_RESET}",
            f"Current week (Fable): 100% used · {_RESET}",
            f"Current week (Haiku 5.5): 40% used · {_RESET}",
            f"Current week (Haiku 4.5): 30% used · {_RESET}",
        ]
    )
    windows, diagnostic = _windows(text)

    assert diagnostic is None
    by_key = {window["key"]: window for window in windows}
    assert sorted(by_key) == [
        "weekly",
        "weekly:claude-fable-5",
        "weekly:claude-haiku-4-5",
        "weekly:claude-haiku-5-5",
    ]
    assert by_key["weekly:claude-haiku-5-5"]["applicability"] == {
        "kind": "models",
        "model_ids": ["claude-haiku-5-5"],
    }
    assert by_key["weekly:claude-haiku-4-5"]["applicability"] == {
        "kind": "models",
        "model_ids": ["claude-haiku-4-5"],
    }
