"""Language identity helpers for the Projects language breakdown."""

from __future__ import annotations

from rich.text import Text

from sase.stats.render._languages_shared import language_color
from sase.stats.render._text import DASH, DIM
from sase.stats.render.context import RenderContext

_LANGUAGE_LABELS: dict[str, str] = {
    "python": "Python",
    "rust": "Rust",
    "typescript": "TypeScript",
    "tsx": "TSX",
    "javascript": "JavaScript",
    "jsx": "JSX",
    "css": "CSS",
    "html": "HTML",
    "lua": "Lua",
    "sh": "Shell",
    "bash": "Bash",
    "zsh": "Zsh",
    "fish": "Fish",
    "json": "JSON",
    "yaml": "YAML",
    "toml": "TOML",
    "xml": "XML",
    "sql": "SQL",
    "markdown": "Markdown",
    "rst": "reStructuredText",
    "jinja": "Jinja",
    "diff": "Diff",
    "c": "C",
    "cpp": "C++",
    "go": "Go",
    "java": "Java",
    "ruby": "Ruby",
    "perl": "Perl",
    "php": "PHP",
    "awk": "Awk",
    "r": "R",
    "powershell": "PowerShell",
    "docker": "Dockerfile",
    "make": "Makefile",
    "swift": "Swift",
    "kotlin": "Kotlin",
    "objective-c": "Objective-C",
    "objective-c++": "Objective-C++",
    "dart": "Dart",
    "scala": "Scala",
    "groovy": "Groovy",
    "csharp": "C#",
    "elixir": "Elixir",
    "erlang": "Erlang",
    "haskell": "Haskell",
    "ocaml": "OCaml",
    "clojure": "Clojure",
    "elm": "Elm",
    "zig": "Zig",
    "nim": "Nim",
    "julia": "Julia",
    "batch": "Batchfile",
    "scss": "SCSS",
    "sass": "Sass",
    "less": "Less",
    "vue": "Vue",
    "graphql": "GraphQL",
    "terraform": "Terraform",
    "nix": "Nix",
    "protobuf": "Protocol Buffers",
    "cmake": "CMake",
    "vim": "Vim script",
}


def language_label(language_id: str) -> str:
    """Return the display label for a sase-core language id."""
    if language_id in _LANGUAGE_LABELS:
        return _LANGUAGE_LABELS[language_id]
    if not language_id:
        return language_id
    return language_id[0].upper() + language_id[1:]


def language_share_label(part: int | None, whole: int | None) -> str:
    """Format a language share without ever printing a false 100%."""
    if whole is None:
        return DASH
    if not whole:
        return "0%" if part == 0 else DASH
    if part is None:
        return DASH
    if part == 0:
        return "0%"
    percent = round(part * 100 / whole)
    if percent == 0:
        return "<1%"
    if percent == 100 and part < whole:
        return ">99%"
    return f"{percent}%"


def top_language(
    languages: tuple[object, ...] | None,
) -> tuple[str, int] | None:
    """Return the (id, lines) of the top lines>0 language, if any."""
    best: tuple[str, int] | None = None
    for item in languages or ():
        name = getattr(item, "name", "")
        lines = getattr(item, "lines", 0) or 0
        if lines <= 0:
            continue
        if best is None or lines > best[1]:
            best = (name, lines)
    return best


def language_cell_text(
    language_id: str | None,
    lines: int | None,
    whole: int | None,
    ctx: RenderContext,
) -> Text:
    """Render the repo LANGUAGE cell (swatch + label + share)."""
    if language_id is None or lines is None or whole is None or not whole:
        return Text(DASH, style=DIM)
    label = language_label(language_id)
    share = language_share_label(lines, whole)
    text = Text()
    if ctx.unicode:
        text.append("● ", style=language_color(language_id))
    text.append(f"{label} {share}")
    return text


__all__ = [
    "language_cell_text",
    "language_label",
    "language_share_label",
    "top_language",
]
