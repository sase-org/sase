"""CSS for the memory review TUI."""

from __future__ import annotations

MEMORY_REVIEW_CSS = """
#memory-review-root {
    layout: vertical;
    height: 1fr;
}

#memory-review-title {
    height: 1;
    padding: 0 1;
    background: $boost;
    color: $text;
    text-style: bold;
}

#memory-review-status {
    height: 1;
    padding: 0 1;
    color: $text-muted;
}

#memory-review-content {
    height: 1fr;
}

#memory-review-list-pane {
    width: 58%;
    height: 1fr;
    border: solid $primary;
}

#memory-review-detail-pane {
    width: 42%;
    height: 1fr;
    border: solid $secondary;
}

#memory-review-list-title,
#memory-review-detail,
#memory-review-body,
#memory-review-footer {
    padding: 0 1;
}

#memory-review-table {
    height: 1fr;
}

#memory-review-detail {
    height: 45%;
    overflow-y: auto;
}

#memory-review-body {
    height: 55%;
    overflow-y: auto;
}

#memory-review-footer {
    height: 1;
    color: $text-muted;
    background: $boost;
}

#memory-review-input-modal {
    width: 72;
    height: auto;
    padding: 1 2;
    border: thick $primary;
    background: $surface;
}

#memory-review-input-title {
    text-style: bold;
    margin-bottom: 1;
}

#memory-review-input {
    width: 100%;
    height: 3;
    border: solid $secondary;
}

#memory-review-input-error {
    color: $error;
    margin-top: 1;
}

#memory-review-input-buttons {
    height: 3;
    margin-top: 1;
}
"""
