"""Cross-repo parity: every new stats language highlights via Pygments."""

from __future__ import annotations

import pytest
from pygments.lexers import get_lexer_by_name

from sase.core.source_language_facade import resolve_source_language
from sase.pager.syntax import normalize_language
from sase.stats.render.languages import _LANGUAGE_LABELS

_NEW_SUFFIX_IDS = [
    ("swift", "swift"),
    ("m", "objective-c"),
    ("mm", "objective-c++"),
    ("kt", "kotlin"),
    ("kts", "kotlin"),
    ("dart", "dart"),
    ("scala", "scala"),
    ("groovy", "groovy"),
    ("cs", "csharp"),
    ("cxx", "cpp"),
    ("hh", "cpp"),
    ("hxx", "cpp"),
    ("mts", "typescript"),
    ("cts", "typescript"),
    ("php", "php"),
    ("pl", "perl"),
    ("pm", "perl"),
    ("ps1", "powershell"),
    ("psm1", "powershell"),
    ("fish", "fish"),
    ("awk", "awk"),
    ("R", "r"),
    ("r", "r"),
    ("jl", "julia"),
    ("bat", "batch"),
    ("rake", "ruby"),
    ("gemspec", "ruby"),
    ("ex", "elixir"),
    ("exs", "elixir"),
    ("erl", "erlang"),
    ("hrl", "erlang"),
    ("hs", "haskell"),
    ("ml", "ocaml"),
    ("mli", "ocaml"),
    ("clj", "clojure"),
    ("cljs", "clojure"),
    ("cljc", "clojure"),
    ("elm", "elm"),
    ("zig", "zig"),
    ("nim", "nim"),
    ("scss", "scss"),
    ("sass", "sass"),
    ("less", "less"),
    ("vue", "vue"),
    ("graphql", "graphql"),
    ("gql", "graphql"),
    ("tf", "terraform"),
    ("nix", "nix"),
    ("proto", "protobuf"),
    ("cmake", "cmake"),
    ("vim", "vim"),
]


@pytest.mark.parametrize(("suffix", "language_id"), _NEW_SUFFIX_IDS)
def test_new_suffix_resolves_and_highlights(suffix: str, language_id: str) -> None:
    result = resolve_source_language(
        category="raw_file",
        logical_filename=f"sample.{suffix}",
    )
    assert result.language == language_id
    normalized = normalize_language(result.language)
    assert normalized is not None
    # Must not raise ClassNotFound.
    get_lexer_by_name(normalized)
    assert language_id in _LANGUAGE_LABELS
