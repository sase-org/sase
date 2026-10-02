"""Deterministic synthetic corpus for the pager benchmark (``pager-bench``).

Each builder returns the full text for one ``(corpus, line_count)`` case.
All builders are seeded and deterministic so reruns compare against the same
bytes. Files are written by :func:`write_corpus` into a caller-owned temp dir;
this module performs no timing itself.
"""

from __future__ import annotations

import random
from pathlib import Path

CASE_NAMES = (
    "code-sparse",
    "log-dense",
    "wide",
    "long-wrap",
    "ansi",
    "multi",
    "markdown",
)

#: Line-count ladder. ``--max-lines`` caps it; ``--cases`` selects corpora.
LINE_LADDER = (500, 2000, 20000, 100000)


def _rng(seed: int) -> random.Random:
    return random.Random(seed)


def build_code_sparse(lines: int) -> str:
    """Python-like lines with a file-path link every 50 lines."""
    rng = _rng(1000 + lines)
    out: list[str] = []
    for index in range(lines):
        if index % 50 == 0:
            out.append(f"see src/sase/module_{index // 50:04d}.py for details")
        else:
            name = rng.choice(("alpha", "beta", "gamma", "delta"))
            out.append(
                f"    result_{index} = compute_{name}({index}, {index * 2})  # ok"
            )
    return "\n".join(out) + "\n"


def build_log_dense(lines: int) -> str:
    """One path link per line (worst case for link scanning)."""
    return "".join(
        f"/var/log/service/worker-{i % 64:02d}.log message {i}\n" for i in range(lines)
    )


def build_wide(lines: int) -> str:
    """CJK, emoji, and combining characters."""
    rng = _rng(2000 + lines)
    cjk = "日本語のテスト行"
    emoji = "🚀📦✅"
    combining = "éüñ"  # e + combining accents
    out: list[str] = []
    for index in range(lines):
        pick = rng.choice((cjk, emoji, combining))
        out.append(f"{index:06d} {pick} padding text {pick}")
    return "\n".join(out) + "\n"


def build_long_wrap(lines: int) -> str:
    """~200-column lines that need wrapping at 120 columns."""
    rng = _rng(3000 + lines)
    words = ("lorem", "ipsum", "dolor", "sit", "amet", "consectetur", "adipiscing")
    out: list[str] = []
    for index in range(lines):
        chunk = " ".join(rng.choice(words) for _ in range(34))
        out.append(f"{index:06d} {chunk}")
    return "\n".join(out) + "\n"


def build_ansi(lines: int) -> str:
    """SGR-colored stdin-style text."""
    out: list[str] = []
    for index in range(lines):
        color = 31 + (index % 6)
        out.append(
            f'\x1b[{color}mlevel=info msg="event {index}" worker={index % 8}\x1b[0m'
        )
    return "\n".join(out) + "\n"


def build_multi(lines: int) -> str:
    """Six bead-like sections separated by rule markers."""

    def section(title: str, count: int) -> str:
        body = "\n".join(f"{title} line {i} with some body text" for i in range(count))
        return f"## {title}\n\n{body}\n"

    per, rest = divmod(lines, 6)
    counts = [per + (1 if i < rest else 0) for i in range(6)]
    return "\n---\n".join(section(f"section-{i}", counts[i]) for i in range(6))


def build_markdown(lines: int) -> str:
    """Markdown within syntax caps, so the syntax overlay runs."""
    out: list[str] = []
    for index in range(lines):
        if index % 20 == 0:
            out.append(f"```python\ndef handler_{index}():\n    return {index}\n```")
        elif index % 7 == 0:
            out.append(f"## Heading {index}")
        elif index % 5 == 0:
            out.append(f"- item {index} with a [link](https://example.test/{index})")
        else:
            out.append(f"Paragraph {index} with *emphasis* and `code span`.")
    return "\n".join(out) + "\n"


BUILDERS = {
    "code-sparse": build_code_sparse,
    "log-dense": build_log_dense,
    "wide": build_wide,
    "long-wrap": build_long_wrap,
    "ansi": build_ansi,
    "multi": build_multi,
    "markdown": build_markdown,
}


def write_corpus(
    root: Path,
    *,
    cases: tuple[str, ...] = CASE_NAMES,
    ladder: tuple[int, ...] = LINE_LADDER,
) -> list[dict[str, object]]:
    """Write every ``(case, line_count)`` file under *root*.

    Returns descriptors ``{"name", "lines", "path", "bytes"}`` in a stable
    order. Unknown case names raise :exc:`KeyError`.
    """
    root.mkdir(parents=True, exist_ok=True)
    descriptors: list[dict[str, object]] = []
    for name in cases:
        builder = BUILDERS[name]
        for count in ladder:
            text = builder(count)
            path = root / f"{name}-{count}.txt"
            path.write_text(text, encoding="utf-8")
            descriptors.append(
                {"name": name, "lines": count, "path": str(path), "bytes": len(text)}
            )
    return descriptors
