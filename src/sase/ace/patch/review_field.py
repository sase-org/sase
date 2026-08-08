"""Patch review URL field labels and compatibility helpers."""

PRIMARY_REVIEW_URL_LABEL = "PR"
LEGACY_REVIEW_URL_LABEL = "CL"
REVIEW_URL_LABELS = (PRIMARY_REVIEW_URL_LABEL, LEGACY_REVIEW_URL_LABEL)
REVIEW_URL_PREFIXES = tuple(f"{label}:" for label in REVIEW_URL_LABELS)
REVIEW_URL_PREFIXES_WITH_SPACE = tuple(f"{label}: " for label in REVIEW_URL_LABELS)


def is_review_url_line(line: str) -> bool:
    """Return True if *line* starts with a supported review URL field label."""
    return line.startswith(REVIEW_URL_PREFIXES)


def parse_review_url_line(line: str) -> str | None:
    """Return the review URL value from a PR/legacy PR field line."""
    for prefix in REVIEW_URL_PREFIXES:
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def format_review_url_line(pr_url: str) -> str:
    """Format the canonical on-disk review URL field."""
    return f"{PRIMARY_REVIEW_URL_LABEL}: {pr_url}\n"
