"""Shared compact status-count chips for ACE agent surfaces."""

from __future__ import annotations

from rich.text import Text

AGENT_COUNT_CHIP_NEUTRAL_STYLE = "#AFAFAF"
AGENT_COUNT_CHIP_QUEUED_STYLE = "bold #5F87FF"
AGENT_COUNT_CHIP_METRIC_STYLES: dict[str, str] = {
    "stopped": "bold #FFAF00",
    "running": "bold #00D7AF",
    "queued": AGENT_COUNT_CHIP_QUEUED_STYLE,
    "waiting": "bold #AF87FF",
    "failed": "bold #FF5F5F",
    "unread": "bold #1a1a1a on #FFD700",
    "done": "bold #5FD7FF",
}
AGENT_COUNT_CHIP_METRICS: tuple[tuple[str, str], ...] = (
    ("stopped", "S"),
    ("running", "R"),
    ("queued", "Q"),
    ("waiting", "W"),
    ("failed", "F"),
    ("unread", "U"),
    ("done", "D"),
)


def format_agent_count_chip(
    *,
    stopped: int = 0,
    running: int = 0,
    queued: int = 0,
    waiting: int = 0,
    failed: int = 0,
    unread: int = 0,
    done: int = 0,
    chrome_style: str | None = None,
) -> Text:
    """Return a zero-suppressing ``[S1 R2 ...]`` Rich status chip."""
    counts = (stopped, running, queued, waiting, failed, unread, done)
    if not any(counts):
        return Text()

    resolved_chrome_style = (
        chrome_style if chrome_style is not None else AGENT_COUNT_CHIP_NEUTRAL_STYLE
    )
    chip = Text("[", style=resolved_chrome_style)
    has_prior_metric = False
    for (name, label), count in zip(AGENT_COUNT_CHIP_METRICS, counts, strict=True):
        if not count:
            continue
        if has_prior_metric:
            chip.append(" ", style=resolved_chrome_style)
        has_prior_metric = True
        metric_style = AGENT_COUNT_CHIP_METRIC_STYLES[name]
        # The unread token uses a visible background, so highlight its letter
        # as well as its count by default. An explicit chrome style keeps every
        # letter aligned with the surrounding chip while preserving count styles.
        letter_style = resolved_chrome_style
        if chrome_style is None and name == "unread":
            letter_style = metric_style
        chip.append(label, style=letter_style)
        chip.append(str(count), style=metric_style)
    chip.append("]", style=resolved_chrome_style)
    return chip
