"""GitHub configuration helpers."""

from sase.config import load_merged_config


def get_github_username() -> str | None:
    """Read ``github_username`` from the merged sase config.

    Returns:
        The configured GitHub username, or ``None`` if not set.
    """
    config = load_merged_config()
    value = config.get("github_username")
    return str(value) if value else None
