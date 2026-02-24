"""GitHub configuration helpers (backward-compat wrapper).

The canonical implementation now lives in :mod:`sase_github.config`.
"""

try:
    from sase_github.config import get_github_username  # type: ignore[import-untyped]
except ImportError:
    from sase.config import load_merged_config

    def get_github_username() -> str | None:  # type: ignore[misc]
        """Read ``github_username`` from the merged sase config."""
        config = load_merged_config()
        value = config.get("github_username")
        return str(value) if value else None


__all__ = ["get_github_username"]
