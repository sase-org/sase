"""Chezmoi template emission for machine-specific AMD H1 titles."""

from __future__ import annotations

from collections.abc import Sequence

_CHEZMOI_LITERAL_OPEN = '{{ "{{" }}'


def _escape_chezmoi_literals(text: str) -> str:
    """Escape literal ``{{`` so chezmoi renders the body back verbatim."""
    return text.replace("{{", _CHEZMOI_LITERAL_OPEN)


def unescape_chezmoi_literals(text: str) -> str:
    """Invert :func:`_escape_chezmoi_literals` for on-disk template reads."""
    return text.replace(_CHEZMOI_LITERAL_OPEN, "{{")


def _h1_action(titles: Sequence[tuple[str, str]], fallback_title: str) -> str:
    parts: list[str] = []
    for index, (hostname, title) in enumerate(titles):
        keyword = "if" if index == 0 else "else if"
        parts.append(
            f'{{{{ {keyword} eq .chezmoi.hostname "{hostname}" }}}}'
            f"# {_escape_chezmoi_literals(title)}"
        )
    parts.append(
        f"{{{{ else }}}}# {_escape_chezmoi_literals(fallback_title)}{{{{ end }}}}"
    )
    return "".join(parts)


def render_chezmoi_h1_template(
    content: str,
    *,
    titles: Sequence[tuple[str, str]],
    fallback_title: str,
) -> tuple[str | None, str | None]:
    """Replace the H1 with a hostname switch and escape literal ``{{``.

    *titles* must already be sorted by hostname. The rendered target still has
    exactly one H1 line; unmatched hostnames keep *fallback_title*.
    """
    if not titles:
        return None, "chezmoi H1 template requires at least one hostname title"
    titles = tuple(sorted(titles, key=lambda item: item[0]))

    lines = content.splitlines(keepends=True)
    h1_index: int | None = None
    for index, line in enumerate(lines):
        if line.lstrip("\ufeff").startswith("# "):
            h1_index = index
            break
    if h1_index is None:
        return None, "rendered AGENTS.md has no H1 title line to templatize"

    h1_line = lines[h1_index]
    if h1_line.endswith("\r\n"):
        newline = "\r\n"
    elif h1_line.endswith("\n"):
        newline = "\n"
    else:
        newline = ""

    escaped = [_escape_chezmoi_literals(line) for line in lines]
    escaped[h1_index] = _h1_action(titles, fallback_title) + newline
    return "".join(escaped), None


__all__ = [
    "render_chezmoi_h1_template",
    "unescape_chezmoi_literals",
]
