"""CSS for the reusable pager reading surface."""

from __future__ import annotations

PAGER_CSS = """
PagerScreen {
    layout: vertical;
    background: $background;
}

PagerScreen .hidden {
    display: none;
}

PagerScreen #pager-subject {
    height: 1;
    padding: 0 1;
    background: $boost;
}

PagerScreen #pager-trail {
    height: 1;
    padding: 0 1;
    color: $text-muted;
}

PagerScreen #pager-chrome-rule {
    height: 1;
    padding: 0 1;
    color: $text-muted;
}

PagerScreen #pager-body-scroll {
    height: 1fr;
}

PagerScreen #pager-body {
    width: 100%;
    padding: 0 1;
}

PagerScreen #pager-search-command {
    height: 1;
    padding: 0 1;
}

PagerScreen #pager-footer-rule {
    height: 1;
    padding: 0 1;
    color: $text-muted;
}

PagerScreen #pager-footer {
    height: 1;
    padding: 0 1;
    color: $text-muted;
}

PagerHelpScreen {
    background: transparent;
}

PagerHelpScreen #pager-help {
    width: 64;
    height: auto;
    max-height: 80%;
    border: round $accent;
    padding: 1 2;
    background: $surface;
}
"""

__all__ = ["PAGER_CSS"]
