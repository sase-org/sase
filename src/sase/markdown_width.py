"""The single source of truth for the repo-wide Markdown prose width.

Every place that wraps Markdown prose derives its width from
``MARKDOWN_PRINT_WIDTH``: the programmatic prettier calls in
``sase.file_references``, the generated-skill renderer, the ``textwrap``-based
memory-shim and frontmatter generators, and the display wrapping in
``sase.markdown_wrap``.

The width cannot collapse to literally one declaration, because the prettier
CLI (``just fmt-md``, CI, editors) reads configuration from files on disk and
cannot import a Python constant. Its mirror is the ``"prettier"`` block in the
repo-root ``package.json``; ``tests/test_markdown_print_width.py`` pins the two
declarations equal so they are one policy rather than two habits.

This module intentionally imports nothing from ``sase`` so that any module may
import it without risking a cycle.
"""

from __future__ import annotations

MARKDOWN_PRINT_WIDTH = 100


def prettier_markdown_argv(*, print_width: int = MARKDOWN_PRINT_WIDTH) -> list[str]:
    """Return the shared prettier argv for Markdown prose.

    sase's own prettier invocations must pass an explicit ``--print-width``
    rather than relying on prettier's config discovery: they format files that
    live outside any repo (plans under ``~/.sase/plans/``, prompt archives,
    agent prompts), so discovery would resolve to whatever repo the process
    happens to be sitting in, or to nothing at all.

    Args:
        print_width: The column width to wrap prose at. Defaults to
            ``MARKDOWN_PRINT_WIDTH``, which every caller uses today.
    """
    return [
        "prettier",
        "--prose-wrap=always",
        f"--print-width={print_width}",
        "--parser=markdown",
    ]
