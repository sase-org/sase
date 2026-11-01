"""Tests for tools/_tui_import_footprint: the normalized import footprint."""

from __future__ import annotations

import os
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests._tui_import_fixtures import (
    MONOLITH_FILES,
    PACKAGE,
    SPLIT_FILES,
    TARGET,
    footprint,
    measure_package,
    write_files,
)


def _fp(text: str) -> int:
    return footprint.source_footprint(text)


def _bytes(*tokens: str) -> int:
    """UTF-8 width of the expected significant tokens."""
    return sum(len(token.encode("utf-8")) for token in tokens)


# --------------------------------------------------------------------------
# Per-file metric
# --------------------------------------------------------------------------


def test_comments_whitespace_and_formatting_are_neutral() -> None:
    compact = "def f(a,b):return a+b\n"
    spread = (
        "# leading comment\n"
        "\n"
        "def f(\n"
        "    a,  # first\n"
        "    b\n"
        "):\n"
        "\n"
        "    return a + \\\n"
        "        b  # trailing\n"
    )
    expected = _bytes("def", "f", "(", "a", ",", "b", ")", ":", "return", "a", "+", "b")
    assert _fp(compact) == expected == _fp(spread)


def test_import_statements_are_excluded_wherever_they_appear() -> None:
    source = (
        "from __future__ import annotations\n"
        "import os\n"
        "from a import (b,\n    c)\n"
        "from . import d as e\n"
        "x = 1\n"
        "def f():\n"
        "    import json\n"
        "    return 1\n"
        "if TYPE_CHECKING:\n"
        "    from x import y\n"
    )
    assert _fp(source) == _bytes(
        *("x", "=", "1"),
        *("def", "f", "(", ")", ":", "return", "1"),
        *("if", "TYPE_CHECKING", ":"),
    )


def test_executable_code_sharing_an_import_line_still_counts() -> None:
    assert _fp("import os; value = 1\n") == _bytes(";", "value", "=", "1")
    assert _fp("value = 1; import os\n") == _bytes("value", "=", "1", ";")
    assert _fp("if True: import os\n") == _bytes("if", "True", ":")


def test_docstrings_are_excluded_but_other_strings_count() -> None:
    docstrings = (
        '"""Module doc."""\n'
        "class C:\n"
        '    """Class doc."""\n'
        "    x = 1\n"
        "def f():\n"
        '    """Doc."""\n'
        "async def g():\n"
        "    'doc'\n"
        "    return 2\n"
    )
    assert _fp(docstrings) == _bytes(
        *("class", "C", ":", "x", "=", "1"),
        *("def", "f", "(", ")", ":"),
        *("async", "def", "g", "(", ")", ":", "return", "2"),
    )

    assert _fp('x = 1\n"""not a doc"""\n') == _bytes("x", "=", "1", '"""not a doc"""')
    header = _bytes("def", "f", "(", ")", ":")
    assert _fp('def f():\n    """doc"""\n    "second"\n') == header + _bytes('"second"')
    # An interpolated string is never a docstring.
    assert _fp('def f():\n    f"""doc{1}"""\n') == header + _bytes(
        'f"""', "doc", "{", "1", "}", '"""'
    )
    assert _fp('"""doc"""; x = 1\n') == _bytes(";", "x", "=", "1")


def test_literal_export_lists_are_excluded_and_empty_facades_cost_nothing() -> None:
    facade = (
        '"""Facade."""\n\n'
        "from __future__ import annotations\n\n"
        "from ._a import a\n\n"
        '__all__ = ["a", "b"]\n'
    )
    assert _fp(facade) == 0
    assert _fp('__all__ = ("a",)\n') == 0
    assert _fp("__all__ = []\n") == 0
    assert _fp("") == 0


def test_computed_and_non_plain_exports_still_count() -> None:
    a = '"a"'
    assert _fp('__all__ = ["a"] + other\n') == _bytes(
        "__all__", "=", "[", a, "]", "+", "other"
    )
    assert _fp('__all__ += ["a"]\n') == _bytes("__all__", "+=", "[", a, "]")
    assert _fp("__all__ = [name for name in names]\n") == _bytes(
        *("__all__", "=", "[", "name", "for", "name", "in", "names", "]")
    )
    assert _fp('__all__ = ["a", b]\n') == _bytes("__all__", "=", "[", a, ",", "b", "]")
    assert _fp('__all__: list[str] = ["a"]\n') == _bytes(
        *("__all__", ":", "list", "[", "str", "]", "=", "[", a, "]")
    )
    assert _fp('__all__ = other = ["a"]\n') == _bytes(
        "__all__", "=", "other", "=", "[", a, "]"
    )
    # Only a module-level assignment is the export declaration.
    assert _fp('def f():\n    __all__ = ["a"]\n') == _bytes(
        *("def", "f", "(", ")", ":", "__all__", "=", "[", a, "]")
    )


def test_unicode_offsets_do_not_shift_excluded_spans() -> None:
    # ast reports UTF-8 byte columns; tokenize reports character columns.
    two_and_three_byte = 's = "é☃☃"; import os; value = 1\n'
    assert _fp(two_and_three_byte) == _bytes(
        *("s", "=", '"é☃☃"', ";", ";", "value", "=", "1")
    )
    four_byte = 's = "😀"; import os; value = 1\n'
    assert _fp(four_byte) == _bytes(*("s", "=", '"😀"', ";", ";", "value", "=", "1"))
    assert _fp('"""é☃"""; x = 1\n') == _bytes(";", "x", "=", "1")


def test_interpolated_strings_count_their_source_width() -> None:
    simple = 'x = f"a{{b}}{y!r:>{w}}c"\n'
    assert _fp(simple) == _bytes("x", "=", 'f"a{{b}}{y!r:>{w}}c"')
    multiline = 'x = f"""a{{\n  b"""\n'
    assert _fp(multiline) == _bytes("x", "=", 'f"""a{{\n  b"""')
    plain = 'x = """a\n  b"""\n'
    assert _fp(plain) == _bytes("x", "=", '"""a\n  b"""')
    # Escaped braces and \N{NAME} escapes keep every source character counted.
    named = 'x = f"{{\\N{EM DASH}}}"\n'
    assert _fp(named) == _bytes("x", "=", 'f"{{\\N{EM DASH}}}"')


def test_decode_source_normalizes_newlines_bom_and_declared_encodings() -> None:
    expected = _bytes("x", "=", "1", "y", "=", "2")
    for raw in (b"x = 1\ny = 2\n", b"x = 1\r\ny = 2\r\n", b"x = 1\ry = 2\r"):
        assert _fp(footprint.decode_source(raw)) == expected
    assert _fp(footprint.decode_source(b"\xef\xbb\xbfx = 1\n")) == _bytes("x", "=", "1")
    latin = b"# -*- coding: latin-1 -*-\nx = '\xe9'\n"
    assert _fp(footprint.decode_source(latin)) == _bytes("x", "=", "'é'")
    crlf_string = b'x = """a\r\nb"""\r\n'
    assert _fp(footprint.decode_source(crlf_string)) == _bytes("x", "=", '"""a\nb"""')


# --------------------------------------------------------------------------
# Source resolution and failures
# --------------------------------------------------------------------------


def test_missing_or_absent_sources_are_actionable_failures(tmp_path: Path) -> None:
    gone = footprint.ModuleSource(file=str(tmp_path / "gone.py"))
    with pytest.raises(footprint.FootprintError, match=r"'pkg.gone'.*does not exist"):
        footprint.measure_footprint({"pkg.gone": gone}, base_dir=tmp_path)
    with pytest.raises(footprint.FootprintError, match="no source file"):
        footprint.measure_footprint(
            {"pkg.nofile": footprint.ModuleSource(file=None)}, base_dir=tmp_path
        )
    extension = footprint.ModuleSource(file=str(tmp_path / "ext.so"))
    with pytest.raises(footprint.FootprintError, match="not a Python source"):
        footprint.measure_footprint({"pkg.ext": extension}, base_dir=tmp_path)


def test_unparseable_sources_name_the_module(tmp_path: Path) -> None:
    broken = tmp_path / "broken.py"
    broken.write_text("def (:\n", encoding="utf-8")
    source = footprint.ModuleSource(file=str(broken))
    with pytest.raises(
        footprint.FootprintError, match=r"cannot parse source of 'pkg.broken'"
    ):
        footprint.measure_footprint({"pkg.broken": source}, base_dir=tmp_path)
    binary = tmp_path / "binary.py"
    binary.write_bytes(b"x = '\xff'\n")
    with pytest.raises(footprint.FootprintError, match=r"'pkg.binary'"):
        footprint.measure_footprint(
            {"pkg.binary": footprint.ModuleSource(file=str(binary))},
            base_dir=tmp_path,
        )


def test_source_backed_bytecode_paths_resolve_to_their_source(tmp_path: Path) -> None:
    module = tmp_path / "mod.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    compiled = py_compile.compile(str(module), doraise=True)
    assert compiled is not None
    cached = Path(compiled)
    assert cached.parent.name == "__pycache__"
    sibling = tmp_path / "side.py"
    sibling.write_text("VALUE = 2\n", encoding="utf-8")
    side_pyc = tmp_path / "side.pyc"
    py_compile.compile(str(sibling), cfile=str(side_pyc), doraise=True)

    assert (
        footprint.resolve_source_path(
            "mod", footprint.ModuleSource(file=str(cached)), tmp_path
        )
        == module
    )
    assert (
        footprint.resolve_source_path(
            "side", footprint.ModuleSource(file=str(side_pyc)), tmp_path
        )
        == sibling
    )
    # Relative paths resolve against the measured interpreter's directory.
    relative = footprint.ModuleSource(file="mod.py")
    assert footprint.resolve_source_path("mod", relative, tmp_path) == module


def test_sourceless_bytecode_is_a_failure_not_a_zero(tmp_path: Path) -> None:
    write_files(tmp_path, {"legacy/__init__.py": "", "legacy/mod.py": "VALUE = 1\n"})
    mod = tmp_path / "legacy" / "mod.py"
    py_compile.compile(
        str(mod), cfile=str(tmp_path / "legacy" / "mod.pyc"), doraise=True
    )
    mod.unlink()
    shutil.rmtree(tmp_path / "legacy" / "__pycache__", ignore_errors=True)
    with pytest.raises(footprint.FootprintError, match="only compiled bytecode"):
        measure_package(tmp_path, target="legacy.mod", package="legacy")


def test_namespace_packages_contribute_zero_without_failing(tmp_path: Path) -> None:
    write_files(tmp_path, {"nspkg/mod.py": "VALUE = 1\n"})
    measurement = measure_package(tmp_path, target="nspkg.mod", package="nspkg")
    assert measurement.first_party_modules == ("nspkg", "nspkg.mod")
    assert dict(measurement.footprint.module_bytes) == {
        "nspkg.mod": _bytes("VALUE", "=", "1")
    }
    assert measurement.footprint_bytes == _bytes("VALUE", "=", "1")


def test_import_failure_is_reported_with_the_interpreter_error(tmp_path: Path) -> None:
    write_files(tmp_path, MONOLITH_FILES)
    with pytest.raises(footprint.ImportProbeError, match="ModuleNotFoundError"):
        measure_package(tmp_path, target=f"{PACKAGE}.missing")


# --------------------------------------------------------------------------
# Closure footprint
# --------------------------------------------------------------------------


def test_empty_facades_and_package_inits_cost_nothing(tmp_path: Path) -> None:
    write_files(tmp_path, SPLIT_FILES)
    measurement = measure_package(tmp_path)
    assert measurement.first_party_modules == tuple(
        sorted([PACKAGE, TARGET, f"{PACKAGE}._alpha", f"{PACKAGE}._beta"])
    )
    assert measurement.footprint.module_bytes[PACKAGE] == 0
    assert measurement.footprint.module_bytes[TARGET] == 0
    assert measurement.footprint_bytes == sum(
        measurement.footprint.module_bytes.values()
    )


def test_two_module_names_aliasing_one_source_count_it_once(tmp_path: Path) -> None:
    real = "def real() -> int:\n    return 1\n"
    app = 'import sys\nfrom . import real\nsys.modules[__name__ + "_alias"] = real\n'
    write_files(
        tmp_path,
        {
            f"{PACKAGE}/__init__.py": "",
            f"{PACKAGE}/real.py": real,
            f"{PACKAGE}/app.py": app,
        },
    )
    measurement = measure_package(tmp_path)

    assert f"{PACKAGE}.app_alias" in measurement.first_party_modules
    assert f"{PACKAGE}.real" in measurement.first_party_modules
    # One canonical entry (the lexicographically first name) per unique file.
    assert f"{PACKAGE}.app_alias" in measurement.footprint.module_bytes
    assert f"{PACKAGE}.real" not in measurement.footprint.module_bytes
    assert measurement.footprint_bytes == _fp(real) + _fp(app)


def test_measurement_machinery_does_not_inflate_the_probe_counts(
    tmp_path: Path,
) -> None:
    write_files(tmp_path, SPLIT_FILES)
    measurement = measure_package(tmp_path)
    plain = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib, json, sys, time\n"
            f"import {TARGET}\n"
            "print(len(sys.modules))",
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
    )
    assert measurement.module_count == int(plain.stdout)


def test_footprint_cache_hits_are_identical_and_never_trusted_when_corrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    cache_dir = tmp_path / "cache"
    write_files(project, SPLIT_FILES)
    cold = measure_package(project, cache=footprint.FootprintCache(cache_dir))
    saved = list(cache_dir.glob("footprint-*.json"))
    assert len(saved) == 1

    def _forbidden(_text: str) -> int:
        raise AssertionError("a warm cache must not re-parse unchanged sources")

    with monkeypatch.context() as scoped:
        scoped.setattr(footprint, "source_footprint", _forbidden)
        warm = measure_package(project, cache=footprint.FootprintCache(cache_dir))
    assert warm.footprint == cold.footprint

    saved[0].write_text("{not json", encoding="utf-8")
    recovered = measure_package(project, cache=footprint.FootprintCache(cache_dir))
    assert recovered.footprint == cold.footprint


def test_footprint_cache_is_keyed_by_content(tmp_path: Path) -> None:
    project = tmp_path / "project"
    cache = footprint.FootprintCache(tmp_path / "cache")
    write_files(project, MONOLITH_FILES)
    before = measure_package(project, cache=cache)
    app = project / PACKAGE / "app.py"
    app.write_text(app.read_text(encoding="utf-8") + "\nEXTRA = 1\n", encoding="utf-8")
    after = measure_package(project, cache=cache)
    assert after.footprint_bytes == before.footprint_bytes + _bytes("EXTRA", "=", "1")
