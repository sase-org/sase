"""Guards that keep the Markdown prose width a single declaration.

The width lives in exactly two places by necessity — ``MARKDOWN_PRINT_WIDTH``
for Python callers and ``package.json``'s ``prettier`` block for the prettier
CLI — and these tests are what make those two declarations one policy instead
of two habits.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from sase.markdown_width import MARKDOWN_PRINT_WIDTH, prettier_markdown_argv

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _REPO_ROOT / "src" / "sase"
_WIDTH_AUTHORITY = _SRC_ROOT / "markdown_width.py"

# Names a module-level prose-width constant would plausibly take. A constant
# matching one of these may not be bound to a bare integer literal anywhere
# except the width authority itself.
_WIDTH_CONSTANT_RE = re.compile(
    r"^_?[A-Z0-9_]*(?:PRINT_WIDTH|PROSE_WRAP_WIDTH|MARKDOWN_WRAP_WIDTH"
    r"|FRONTMATTER_WRAP_WIDTH)$"
)
# ``MIN_PROSE_WRAP_WIDTH`` is a floor for the ``--wrap`` CLI option, not the
# prose-width policy, so it is allowed to be its own literal.
_ALLOWED_LITERAL_CONSTANTS = {"MIN_PROSE_WRAP_WIDTH"}

_PRINT_WIDTH_FLAG_RE = re.compile(r"--print-width")
_PROSE_WRAP_FLAG_RE = re.compile(r"--prose-wrap")


def _width_aware_modules() -> list[Path]:
    """Return the modules that have declared themselves prose-width-aware.

    Scanning every module under ``src/`` for inline width literals would be the
    flaky whole-repo grep this suite is meant to avoid: ``Console(width=120)``
    in TUI code and every unrelated numeric comparison would trip it. Importing
    ``sase.markdown_width`` is the narrow, self-declared signal that a module
    wraps prose, so these are the modules held to the stricter standard.
    """
    modules = [
        path
        for path in sorted(_SRC_ROOT.rglob("*.py"))
        if path != _WIDTH_AUTHORITY
        and "markdown_width" in path.read_text(encoding="utf-8")
    ]
    assert modules, (
        "no module imports sase.markdown_width — the inline-width guards below "
        "would pass vacuously"
    )
    return modules


def _prettier_config() -> dict[str, object]:
    package_json = json.loads((_REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    config = package_json.get("prettier")
    assert isinstance(config, dict), "package.json must declare a prettier config block"
    return config


def test_package_json_mirrors_the_width_authority() -> None:
    """The prettier CLI's declaration must equal the Python declaration."""
    assert _prettier_config()["printWidth"] == MARKDOWN_PRINT_WIDTH


def test_package_json_declares_always_prose_wrap() -> None:
    """Prose wrapping is part of the policy, not just the width."""
    assert _prettier_config()["proseWrap"] == "always"


def test_prettier_markdown_argv_uses_the_width_authority() -> None:
    argv = prettier_markdown_argv()

    assert argv[0] == "prettier"
    assert f"--print-width={MARKDOWN_PRINT_WIDTH}" in argv
    assert "--prose-wrap=always" in argv
    assert "--parser=markdown" in argv


def test_prettier_markdown_argv_honors_an_explicit_width() -> None:
    assert "--print-width=42" in prettier_markdown_argv(print_width=42)


def test_justfile_declares_no_prose_width() -> None:
    """`just fmt-md` and `fmt-md-check` must defer to package.json.

    A flag here would be a second CLI declaration that package.json silently
    loses to.
    """
    justfile = (_REPO_ROOT / "Justfile").read_text(encoding="utf-8")

    assert not _PRINT_WIDTH_FLAG_RE.search(justfile)
    assert not _PROSE_WRAP_FLAG_RE.search(justfile)


@pytest.mark.parametrize("flag_re", [_PRINT_WIDTH_FLAG_RE, _PROSE_WRAP_FLAG_RE])
def test_only_the_width_authority_builds_prettier_flags(
    flag_re: re.Pattern[str],
) -> None:
    """No module under src/ may assemble its own prettier prose flags."""
    offenders = [
        path.relative_to(_REPO_ROOT).as_posix()
        for path in sorted(_SRC_ROOT.rglob("*.py"))
        if path != _WIDTH_AUTHORITY and flag_re.search(path.read_text(encoding="utf-8"))
    ]

    assert not offenders, (
        f"these modules re-declare a prettier prose flag instead of calling "
        f"prettier_markdown_argv(): {offenders}"
    )


def test_only_the_width_authority_binds_a_width_to_an_integer_literal() -> None:
    """Every other prose-width constant must derive from the authority."""
    offenders: list[str] = []
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        if path == _WIDTH_AUTHORITY:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not isinstance(node.value, ast.Constant) or not isinstance(
                node.value.value, int
            ):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id in _ALLOWED_LITERAL_CONSTANTS:
                    continue
                if _WIDTH_CONSTANT_RE.match(target.id):
                    offenders.append(
                        f"{path.relative_to(_REPO_ROOT).as_posix()}:{node.lineno} "
                        f"{target.id}"
                    )

    assert not offenders, (
        f"these constants re-fork the prose width instead of deriving from "
        f"MARKDOWN_PRINT_WIDTH: {offenders}"
    )


def test_no_width_aware_module_passes_an_inline_width_literal() -> None:
    """A width may not be re-forked as a bare ``width=<int>`` call argument.

    The constant scan above only sees module-level bindings, which is how
    ``textwrap.fill(description, width=118)`` in the generated-skill renderer
    survived the unification and had to be caught by a failing golden instead.
    """
    offenders: list[str] = []
    for path in _width_aware_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg is None or "width" not in keyword.arg:
                    continue
                if isinstance(keyword.value, ast.Constant) and isinstance(
                    keyword.value.value, int
                ):
                    offenders.append(
                        f"{path.relative_to(_REPO_ROOT).as_posix()}:"
                        f"{keyword.value.lineno} {keyword.arg}="
                        f"{keyword.value.value}"
                    )

    assert not offenders, (
        f"these calls hardcode a width instead of deriving it from "
        f"MARKDOWN_PRINT_WIDTH: {offenders}"
    )


def test_no_width_aware_module_compares_a_length_to_an_inline_literal() -> None:
    """A line-length threshold must derive from the authority too.

    ``len(f"description: {description}") > 120`` is the other shape the
    constant scan misses: a width used as a comparison threshold rather than
    bound to a name.
    """
    offenders: list[str] = []
    for path in _width_aware_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            left = node.left
            if not (
                isinstance(left, ast.Call)
                and isinstance(left.func, ast.Name)
                and left.func.id == "len"
            ):
                continue
            for comparator in node.comparators:
                if isinstance(comparator, ast.Constant) and isinstance(
                    comparator.value, int
                ):
                    offenders.append(
                        f"{path.relative_to(_REPO_ROOT).as_posix()}:"
                        f"{comparator.lineno} len(...) vs {comparator.value}"
                    )

    assert not offenders, (
        f"these length thresholds hardcode a width instead of deriving it "
        f"from MARKDOWN_PRINT_WIDTH: {offenders}"
    )
