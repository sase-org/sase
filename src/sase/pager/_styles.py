"""CSS for the standalone ``SasePager`` reading surface."""

from __future__ import annotations

PAGER_CSS = """
Screen {
    layout: vertical;
}

.hidden {
    display: none;
}

#pager-subject {
    height: 1;
    padding: 0 1;
    background: $boost;
}

#pager-trail {
    height: 1;
    padding: 0 1;
    color: $text-muted;
}

#pager-chrome-rule {
    height: 1;
    padding: 0 1;
    color: $text-muted;
}

#pager-body-scroll {
    height: 1fr;
}

#pager-body {
    width: 100%;
    padding: 0 1;
}

#pager-search-command {
    height: 1;
    padding: 0 1;
}

#pager-footer-rule {
    height: 1;
    padding: 0 1;
    color: $text-muted;
}

#pager-footer {
    height: 1;
    padding: 0 1;
    color: $text-muted;
}

#pager-help {
    width: 64;
    height: auto;
    max-height: 80%;
    border: round $accent;
    padding: 1 2;
    background: $surface;
}
"""

__all__ = ["PAGER_CSS"]
