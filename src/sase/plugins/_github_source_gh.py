"""The ``gh`` CLI boundary for GitHub repository searches.

Owns the search constants that define the canonical plugin registry, the
endpoint construction for one page of ``search/repositories``, and the single
subprocess call every page goes through.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable

from sase.plugins._github_source_errors import GH_INSTALL_HINT, GhCommandError

#: Topic search that defines the canonical registry. No org filter, so both
#: ``sase-org`` (built-in) and community repositories are returned.
SASE_PLUGIN_TOPIC = "sase--plugin"
GH_SEARCH_QUERY = f"topic:{SASE_PLUGIN_TOPIC}"

#: GitHub REST search returns at most this many items for any one query.
GH_SEARCH_RESULT_CAP = 1000

#: Page size used for every ``search/repositories`` request.
GH_SEARCH_PER_PAGE = 100

#: ``page=11`` is a 422; never request past this.
GH_SEARCH_MAX_PAGES = GH_SEARCH_RESULT_CAP // GH_SEARCH_PER_PAGE

#: Per-request subprocess timeout for each ``gh api`` page, in seconds.
#: Explicit paging makes the whole-catalog budget scale with page count
#: (``GH_TIMEOUT_SECONDS * pages``) instead of a flat 20 s for ``--paginate``.
GH_TIMEOUT_SECONDS = 20.0

WhichFn = Callable[[str], str | None]
RunFn = Callable[..., "subprocess.CompletedProcess[str]"]


def search_endpoint(query: str, *, page: int) -> str:
    """Build the ``search/repositories`` endpoint for one page of ``query``."""
    encoded = query.replace(" ", "+")
    return f"search/repositories?q={encoded}&per_page={GH_SEARCH_PER_PAGE}&page={page}"


def gh_api(
    endpoint: str,
    *,
    run_fn: RunFn,
    timeout: float,
    allow_cap: bool,
) -> str | None:
    """Run ``gh api <endpoint>`` and return stdout.

    Returns ``None`` instead of raising when ``allow_cap`` is set and GitHub
    refused the request because it reaches past the 1000-result search cap.
    """
    try:
        result = run_fn(
            ["gh", "api", "-X", "GET", endpoint],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise GhCommandError(
            f"`gh api` timed out after {timeout:g}s while fetching the plugin catalog."
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise GhCommandError(
            f"`gh api` could not be run: {type(exc).__name__}: {exc}"
        ) from exc

    if result.returncode != 0:
        detail = _first_nonempty_line(result.stderr, result.stdout)
        if allow_cap and _is_search_cap_error(detail):
            return None
        suffix = f": {detail}" if detail else ""
        raise GhCommandError(
            "`gh api` failed while fetching the plugin catalog"
            f" (exit {result.returncode}){suffix}. {GH_INSTALL_HINT}"
        )
    return result.stdout


def _is_search_cap_error(detail: str | None) -> bool:
    if not detail:
        return False
    lowered = detail.lower()
    return "only the first 1000 search results" in lowered


def _first_nonempty_line(*texts: str) -> str | None:
    for text in texts:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
    return None
