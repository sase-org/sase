"""Unified prompt search corpus and engine for ``sase prompt search``.

The package is split so the pure data + engine layers stay separable from
rendering (and migratable to a shared backend later, per
``rust_core_backend_boundary``):

- :mod:`sase.prompt.search.model` — the source-agnostic :class:`PromptHit`
  result model and the :class:`PromptSearchResult` envelope.
- :mod:`sase.prompt.search.dates` — date-filter parsing and the documented
  per-source date precedence.
- :mod:`sase.prompt.search.sources` — archive + local loaders, unification, and
  sha-based de-duplication into one corpus.
- :mod:`sase.prompt.search.engine` — the pure, deterministic match/filter/rank/
  limit engine over a loaded corpus.

This module re-exports the public data-layer and engine surface that the ChangeSpecI
layer builds on.
"""

from __future__ import annotations

from sase.prompt.search.dates import (
    PromptSearchDateError,
    hit_date,
    parse_search_date,
    resolve_archive_date,
)
from sase.prompt.search.engine import EmptyPromptQueryError, search_prompts
from sase.prompt.search.model import (
    PromptHit,
    PromptSearchMatch,
    PromptSearchResult,
    PromptSource,
)
from sase.prompt.search.sources import (
    collect_prompt_hits,
    load_local_prompt_hits,
    load_archive_prompt_hits,
)

__all__ = [
    "EmptyPromptQueryError",
    "PromptHit",
    "PromptSearchDateError",
    "PromptSearchMatch",
    "PromptSearchResult",
    "PromptSource",
    "collect_prompt_hits",
    "hit_date",
    "load_local_prompt_hits",
    "load_archive_prompt_hits",
    "parse_search_date",
    "resolve_archive_date",
    "search_prompts",
]
