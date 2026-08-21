"""Guards that keep the Markdown prose width a single, runtime-resolved policy.

The width lives in exactly two places by necessity — the
``markdown.print_width`` config field (whose shipped default is
``DEFAULT_MARKDOWN_PRINT_WIDTH``) for Python callers and ``package.json``'s
``prettier`` block for the prettier CLI — and these tests are what make those
two declarations one policy instead of two habits.

Because the width is configurable, a second failure mode exists that a literal
scan cannot see: a module that snapshots the value at import time is
syntactically clean and silently ignores config. The import-time-snapshot and
parameter-default guards below are what keep the migration off frozen constants
from quietly regressing.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
import yaml

from sase.config import core as config_core
from sase.file_references import format_with_prettier
from sase.markdown_width import (
    DEFAULT_MARKDOWN_PRINT_WIDTH,
    markdown_print_width,
    prettier_markdown_argv,
)
from sase.markdown_wrap import MIN_PROSE_WRAP_WIDTH

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

# The two names that resolve the prose width. Binding either at import time —
# to a module-level name or to a function parameter default — freezes the value
# before any config is read.
_WIDTH_SOURCE_NAMES = {"markdown_print_width", "DEFAULT_MARKDOWN_PRINT_WIDTH"}

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


def _references_a_width_source(node: ast.expr) -> str | None:
    """Return the width source *node* resolves, if it is one.

    Catches both ``markdown_print_width()`` and a bare
    ``DEFAULT_MARKDOWN_PRINT_WIDTH``, through a plain name or an attribute
    access such as ``markdown_width.DEFAULT_MARKDOWN_PRINT_WIDTH``.
    """
    if isinstance(node, ast.Call):
        return _references_a_width_source(node.func)
    if isinstance(node, ast.Name) and node.id in _WIDTH_SOURCE_NAMES:
        return node.id
    if isinstance(node, ast.Attribute) and node.attr in _WIDTH_SOURCE_NAMES:
        return node.attr
    return None


def test_package_json_mirrors_the_width_authority() -> None:
    """The prettier CLI's declaration must equal the shipped Python default.

    Deliberately the *default* and not the effective configured value: a stock
    checkout must be self-consistent for a contributor with no SASE config, and
    the suite runs with an isolated ``CONFIG_DIR`` so an effective value would
    be un-assertable without leaking developer config into the tests.
    """
    assert _prettier_config()["printWidth"] == DEFAULT_MARKDOWN_PRINT_WIDTH


def test_package_json_declares_always_prose_wrap() -> None:
    """Prose wrapping is part of the policy, not just the width."""
    assert _prettier_config()["proseWrap"] == "always"


def test_prettier_markdown_argv_uses_the_width_authority() -> None:
    argv = prettier_markdown_argv()

    assert argv[0] == "prettier"
    assert f"--print-width={markdown_print_width()}" in argv
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
        f"DEFAULT_MARKDOWN_PRINT_WIDTH: {offenders}"
    )


def test_no_module_snapshots_the_width_at_import_time() -> None:
    """No module-level name may be bound to a resolved prose width.

    This is the guard that makes the configurable width actually configurable:
    ``_FRONTMATTER_WRAP_WIDTH = markdown_print_width()`` is syntactically clean
    and silently ignores config forever after the module is imported.
    """
    offenders: list[str] = []
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        if path == _WIDTH_AUTHORITY:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets: list[ast.expr] = list(node.targets)
                value = node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets = [node.target]
                value = node.value
            else:
                continue
            source = _references_a_width_source(value)
            if source is None:
                continue
            names = [
                target.id for target in targets if isinstance(target, ast.Name)
            ] or ["<binding>"]
            offenders.append(
                f"{path.relative_to(_REPO_ROOT).as_posix()}:{node.lineno} "
                f"{names[0]} = {source}"
            )

    assert not offenders, (
        f"these module-level bindings snapshot the prose width at import time "
        f"instead of resolving it per call: {offenders}"
    )


def test_no_function_parameter_defaults_to_the_width() -> None:
    """A default argument is evaluated once at ``def`` time.

    That is the same import-time snapshot wearing a different hat, and it is
    exactly the shape ``prettier_markdown_argv`` used to have.
    """
    offenders: list[str] = []
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            defaults = [
                default
                for default in (*node.args.defaults, *node.args.kw_defaults)
                if default is not None
            ]
            for default in defaults:
                source = _references_a_width_source(default)
                if source is None:
                    continue
                offenders.append(
                    f"{path.relative_to(_REPO_ROOT).as_posix()}:{default.lineno} "
                    f"{node.name}(... = {source})"
                )

    assert not offenders, (
        f"these parameter defaults freeze the prose width at def time; take "
        f"`int | None = None` and resolve inside instead: {offenders}"
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
        f"markdown_print_width(): {offenders}"
    )


def test_no_width_aware_module_compares_a_length_to_an_inline_literal() -> None:
    """A line-length threshold must derive from the authority too.

    ``len(f"description: {description}") > 120`` is the other shape the
    constant scan misses: a width used as a comparison threshold rather than
    bound to a name.

    Only *ordering* comparisons against a value at or above the wrap floor
    count. ``len(issues) == 1`` is a cardinality check, not a width, and a
    prose width can never be below ``MIN_PROSE_WRAP_WIDTH``.
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
            if not all(
                isinstance(op, ast.Gt | ast.GtE | ast.Lt | ast.LtE) for op in node.ops
            ):
                continue
            for comparator in node.comparators:
                if (
                    isinstance(comparator, ast.Constant)
                    and isinstance(comparator.value, int)
                    and not isinstance(comparator.value, bool)
                    and comparator.value >= MIN_PROSE_WRAP_WIDTH
                ):
                    offenders.append(
                        f"{path.relative_to(_REPO_ROOT).as_posix()}:"
                        f"{comparator.lineno} len(...) vs {comparator.value}"
                    )

    assert not offenders, (
        f"these length thresholds hardcode a width instead of deriving it "
        f"from markdown_print_width(): {offenders}"
    )


def test_print_width_default_and_schema_contract() -> None:
    """The constant, `default_config.yml`, and the schema must all agree."""
    defaults = yaml.safe_load(
        (_REPO_ROOT / "src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (_REPO_ROOT / "src/sase/config/sase.schema.json").read_text(encoding="utf-8")
    )
    markdown = schema["properties"]["markdown"]

    assert defaults["markdown"] == {"print_width": DEFAULT_MARKDOWN_PRINT_WIDTH}
    assert markdown["additionalProperties"] is False
    print_width = markdown["properties"]["print_width"]
    assert print_width["type"] == "integer"
    assert print_width["default"] == DEFAULT_MARKDOWN_PRINT_WIDTH
    # Below this floor ``wrap_markdown()`` silently returns text unwrapped, so
    # the schema minimum and the wrap floor are one number.
    assert print_width["minimum"] == MIN_PROSE_WRAP_WIDTH


def test_markdown_print_width_follows_configuration(monkeypatch) -> None:
    monkeypatch.setattr(
        config_core, "load_merged_config", lambda: {"markdown": {"print_width": 72}}
    )

    assert markdown_print_width() == 72
    assert "--print-width=72" in prettier_markdown_argv()


def test_format_with_prettier_follows_configuration(monkeypatch) -> None:
    """The width reaches the one resolution point through every default."""
    monkeypatch.setattr(
        config_core, "load_merged_config", lambda: {"markdown": {"print_width": 60}}
    )
    captured: list[list[str]] = []

    class _Result:
        stdout = "formatted\n"

    def fake_run(argv: list[str], **_kwargs: object) -> _Result:
        captured.append(argv)
        return _Result()

    monkeypatch.setattr("sase.file_references.shutil.which", lambda _name: "/bin/true")
    monkeypatch.setattr("sase.file_references.subprocess.run", fake_run)

    assert format_with_prettier("text") == "formatted\n"
    assert captured and "--print-width=60" in captured[0]


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"markdown": None},
        {"markdown": []},
        {"markdown": {}},
        {"markdown": {"print_width": MIN_PROSE_WRAP_WIDTH - 1}},
        {"markdown": {"print_width": "88"}},
        {"markdown": {"print_width": 88.0}},
        {"markdown": {"print_width": True}},
        {"markdown": {"print_width": None}},
    ],
)
def test_markdown_print_width_falls_back_for_invalid_values(
    monkeypatch, config: dict[str, object]
) -> None:
    monkeypatch.setattr(config_core, "load_merged_config", lambda: config)

    assert markdown_print_width() == DEFAULT_MARKDOWN_PRINT_WIDTH


def test_markdown_print_width_does_not_propagate_config_errors(monkeypatch) -> None:
    """A broken ``sase.yml`` must not turn `sase plan propose` into a traceback."""

    def unavailable() -> dict[str, object]:
        raise OSError("config unavailable")

    monkeypatch.setattr(config_core, "load_merged_config", unavailable)

    assert markdown_print_width() == DEFAULT_MARKDOWN_PRINT_WIDTH
