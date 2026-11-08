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
from dataclasses import dataclass
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


@dataclass(frozen=True)
class _SourceGuardFindings:
    """Violations collected by one read, parse, and AST walk per source file."""

    width_aware_modules: tuple[str, ...]
    print_width_flags: tuple[str, ...]
    prose_wrap_flags: tuple[str, ...]
    module_width_literals: tuple[str, ...]
    import_time_snapshots: tuple[str, ...]
    function_default_snapshots: tuple[str, ...]
    width_aware_call_literals: tuple[str, ...]
    width_aware_length_thresholds: tuple[str, ...]


def _scan_source_guards(
    repo_root: Path = _REPO_ROOT,
) -> _SourceGuardFindings:
    """Scan source policy once instead of repeating whole-tree AST walks.

    This intentionally has no cache: callers that change a temporary source
    tree get fresh results, and the ordinary policy test calls it once per run.
    """
    src_root = repo_root / "src" / "sase"
    width_authority = src_root / "markdown_width.py"
    print_width_flags: list[str] = []
    prose_wrap_flags: list[str] = []
    module_width_literals: list[str] = []
    import_time_snapshots: list[str] = []
    function_default_snapshots: list[str] = []
    width_aware_call_literals: list[str] = []
    width_aware_length_thresholds: list[str] = []
    width_aware_modules: list[str] = []

    for path in sorted(src_root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        is_authority = path == width_authority
        is_width_aware = not is_authority and "markdown_width" in text
        relative = path.relative_to(repo_root).as_posix()

        if is_width_aware:
            width_aware_modules.append(relative)
        if not is_authority:
            if _PRINT_WIDTH_FLAG_RE.search(text):
                print_width_flags.append(relative)
            if _PROSE_WRAP_FLAG_RE.search(text):
                prose_wrap_flags.append(relative)

        tree = ast.parse(text)
        if not is_authority:
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    if not isinstance(node.value, ast.Constant) or not isinstance(
                        node.value.value, int
                    ):
                        continue
                    targets = node.targets
                    value = node.value
                elif isinstance(node, ast.AnnAssign) and node.value is not None:
                    if not isinstance(node.value, ast.Constant) or not isinstance(
                        node.value.value, int
                    ):
                        continue
                    targets = [node.target]
                    value = node.value
                else:
                    continue

                for target in targets:
                    if not isinstance(target, ast.Name):
                        continue
                    if target.id in _ALLOWED_LITERAL_CONSTANTS:
                        continue
                    if _WIDTH_CONSTANT_RE.match(target.id):
                        module_width_literals.append(
                            f"{relative}:{value.lineno} {target.id}"
                        )

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
                import_time_snapshots.append(
                    f"{relative}:{node.lineno} {names[0]} = {source}"
                )

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                defaults = [
                    default
                    for default in (*node.args.defaults, *node.args.kw_defaults)
                    if default is not None
                ]
                for default in defaults:
                    source = _references_a_width_source(default)
                    if source is not None:
                        function_default_snapshots.append(
                            f"{relative}:{default.lineno} {node.name}(... = {source})"
                        )

            if not is_width_aware:
                continue
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg is None or "width" not in keyword.arg:
                        continue
                    if isinstance(keyword.value, ast.Constant) and isinstance(
                        keyword.value.value, int
                    ):
                        width_aware_call_literals.append(
                            f"{relative}:{keyword.value.lineno} {keyword.arg}="
                            f"{keyword.value.value}"
                        )
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
                    width_aware_length_thresholds.append(
                        f"{relative}:{comparator.lineno} len(...) vs {comparator.value}"
                    )

    return _SourceGuardFindings(
        width_aware_modules=tuple(width_aware_modules),
        print_width_flags=tuple(print_width_flags),
        prose_wrap_flags=tuple(prose_wrap_flags),
        module_width_literals=tuple(module_width_literals),
        import_time_snapshots=tuple(import_time_snapshots),
        function_default_snapshots=tuple(function_default_snapshots),
        width_aware_call_literals=tuple(width_aware_call_literals),
        width_aware_length_thresholds=tuple(width_aware_length_thresholds),
    )


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


def test_source_width_policy_scans_match_their_individual_regressions(
    tmp_path: Path,
) -> None:
    """The optimized combined scan still catches each former guard shape."""
    src_root = tmp_path / "src" / "sase"
    src_root.mkdir(parents=True)
    (src_root / "markdown_width.py").write_text(
        "DEFAULT_MARKDOWN_PRINT_WIDTH = 88\n", encoding="utf-8"
    )
    offender = src_root / "width_consumer.py"
    offender.write_text(
        """import markdown_width
# --print-width
# --prose-wrap
_MARKDOWN_PRINT_WIDTH = 120
CACHED = markdown_width.markdown_print_width()

def render(width=markdown_width.markdown_print_width()):
    wrap(text, max_width=121)
    if len(text) > 122:
        pass
""",
        encoding="utf-8",
    )

    findings = _scan_source_guards(tmp_path)

    assert findings.width_aware_modules == ("src/sase/width_consumer.py",)
    assert findings.print_width_flags == ("src/sase/width_consumer.py",)
    assert findings.prose_wrap_flags == ("src/sase/width_consumer.py",)
    assert findings.module_width_literals == (
        "src/sase/width_consumer.py:4 _MARKDOWN_PRINT_WIDTH",
    )
    assert findings.import_time_snapshots == (
        "src/sase/width_consumer.py:5 CACHED = markdown_print_width",
    )
    assert findings.function_default_snapshots == (
        "src/sase/width_consumer.py:7 render(... = markdown_print_width)",
    )
    assert findings.width_aware_call_literals == (
        "src/sase/width_consumer.py:8 max_width=121",
    )
    assert findings.width_aware_length_thresholds == (
        "src/sase/width_consumer.py:9 len(...) vs 122",
    )

    offender.write_text(
        "import markdown_width\n\ndef render(width=None):\n    return width\n",
        encoding="utf-8",
    )
    clean_findings = _scan_source_guards(tmp_path)
    assert clean_findings.print_width_flags == ()
    assert clean_findings.prose_wrap_flags == ()
    assert clean_findings.module_width_literals == ()
    assert clean_findings.import_time_snapshots == ()
    assert clean_findings.function_default_snapshots == ()
    assert clean_findings.width_aware_call_literals == ()
    assert clean_findings.width_aware_length_thresholds == ()


def test_source_modules_preserve_markdown_width_policy() -> None:
    """Check every source invariant with one whole-tree AST scan."""
    findings = _scan_source_guards()

    assert findings.width_aware_modules, (
        "no module imports sase.markdown_width — the inline-width guards below "
        "would pass vacuously"
    )
    assert not findings.print_width_flags, (
        "these modules re-declare a prettier prose flag instead of calling "
        f"prettier_markdown_argv(): {list(findings.print_width_flags)}"
    )
    assert not findings.prose_wrap_flags, (
        "these modules re-declare a prettier prose flag instead of calling "
        f"prettier_markdown_argv(): {list(findings.prose_wrap_flags)}"
    )
    assert not findings.module_width_literals, (
        "these constants re-fork the prose width instead of deriving from "
        f"DEFAULT_MARKDOWN_PRINT_WIDTH: {list(findings.module_width_literals)}"
    )
    assert not findings.import_time_snapshots, (
        "these module-level bindings snapshot the width at import time instead "
        f"of resolving it per call: {list(findings.import_time_snapshots)}"
    )
    assert not findings.function_default_snapshots, (
        "these parameter defaults freeze the prose width at def time; take "
        f"`int | None = None` and resolve inside instead: "
        f"{list(findings.function_default_snapshots)}"
    )
    assert not findings.width_aware_call_literals, (
        "these calls hardcode a width instead of deriving it from "
        f"markdown_print_width(): {list(findings.width_aware_call_literals)}"
    )
    assert not findings.width_aware_length_thresholds, (
        "these length thresholds hardcode a width instead of deriving it "
        f"from markdown_print_width(): "
        f"{list(findings.width_aware_length_thresholds)}"
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
