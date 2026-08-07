"""The single source of truth for the repo-wide Markdown prose width.

Every place that wraps Markdown prose derives its width from
``markdown_print_width()``: the programmatic prettier calls in
``sase.file_references``, the generated-skill renderer, the ``textwrap``-based
memory-shim and frontmatter generators, and the display wrapping in
``sase.markdown_wrap``.

The width is configurable through the ``markdown.print_width`` config field, so
it must be resolved *at call time*. A module-level snapshot, a function
parameter default, or an argparse default built at import time all freeze the
value before any config is read; ``tests/test_markdown_print_width.py`` guards
against each of those shapes.

The width cannot collapse to literally one declaration, because the prettier
CLI (``just fmt-md``, CI, editors) reads configuration from files on disk and
cannot import a Python constant. Its mirror is the ``"prettier"`` block in the
repo-root ``package.json``, which pins the *shipped default* rather than the
effective configured value so that a stock checkout is self-consistent;
``tests/test_markdown_print_width.py`` pins the two declarations equal so they
are one policy rather than two habits.

This module intentionally imports nothing from ``sase`` at module scope. The
promise runs in both directions: any module may import it without risking a
cycle, and ``sase.config.core`` imports ``DEFAULT_MARKDOWN_PRINT_WIDTH`` from
here, so a module-level ``sase.config`` import here would make that cycle real.
The ``sase.config`` import in ``markdown_print_width()`` must stay
function-local for that reason.
"""

from __future__ import annotations

DEFAULT_MARKDOWN_PRINT_WIDTH = 100


def markdown_print_width() -> int:
    """Return the configured Markdown prose width.

    Resolved on every call rather than snapshotted, so live edits to
    ``markdown.print_width`` are observed. ``load_merged_config()`` is cached,
    but the config-token cache still stats the filesystem periodically, so
    callers should hoist this out of per-row and per-line render loops.
    """
    from sase.config import get_markdown_print_width

    return get_markdown_print_width()


def prettier_markdown_argv(*, print_width: int | None = None) -> list[str]:
    """Return the shared prettier argv for Markdown prose.

    sase's own prettier invocations must pass an explicit ``--print-width``
    rather than relying on prettier's config discovery: they format files that
    live outside any repo (plans under ``~/.sase/plans/``, prompt archives,
    agent prompts), so discovery would resolve to whatever repo the process
    happens to be sitting in, or to nothing at all.

    Args:
        print_width: The column width to wrap prose at. ``None`` (the default)
            resolves the configured width, which is what every caller wants.
    """
    width = markdown_print_width() if print_width is None else print_width
    return [
        "prettier",
        "--prose-wrap=always",
        f"--print-width={width}",
        "--parser=markdown",
    ]
