"""Host-config safety guards for tests that seed SASE config files."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests._conftest_environment import (
    _assert_not_real_host_sase_config_layer,
    _REAL_HOST_SASE_CONFIG_DIR,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TESTS_ROOT = _REPO_ROOT / "tests"


def _module_scope_config_dir_bindings(tree: ast.Module) -> dict[str, int]:
    bindings: dict[str, int] = {}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module != "sase.config.core":
            continue
        for alias in node.names:
            if alias.name == "CONFIG_DIR":
                bindings[alias.asname or alias.name] = node.lineno
    return bindings


def _path_expression_starts_from(
    node: ast.expr, binding_names: frozenset[str]
) -> str | None:
    if isinstance(node, ast.Name) and node.id in binding_names:
        return node.id
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _path_expression_starts_from(node.left, binding_names)
    return None


def _is_sase_config_layer_name(node: ast.expr) -> bool:
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return False
    name = Path(node.value).name
    return name in {"sase.yml", "sase.yaml"} or (
        name.startswith("sase_") and name.endswith((".yml", ".yaml"))
    )


def _config_dir_seed_targets(
    tree: ast.Module, bindings: dict[str, int]
) -> list[tuple[int, str]]:
    targets: list[tuple[int, str]] = []
    binding_names = frozenset(bindings)
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
            continue
        if not _is_sase_config_layer_name(node.right):
            continue
        binding = _path_expression_starts_from(node.left, binding_names)
        if binding is not None:
            targets.append((node.lineno, binding))
    return targets


def test_config_seed_tests_do_not_snapshot_config_dir_at_module_scope() -> None:
    """Config seeding must resolve ``CONFIG_DIR`` after isolation fixtures run."""
    offenders: list[str] = []
    for path in sorted(_TESTS_ROOT.rglob("*.py")):
        relative = path.relative_to(_REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        bindings = _module_scope_config_dir_bindings(tree)
        if not bindings:
            continue
        targets = _config_dir_seed_targets(tree, bindings)
        if not targets:
            continue
        for line, binding in targets:
            import_line = bindings[binding]
            offenders.append(
                f"{relative}:{import_line} imports {binding} at module scope; "
                f"{relative}:{line} builds a writable config layer from it"
            )

    assert not offenders, (
        "tests that seed SASE config files must use runtime module lookup "
        "after pytest isolation fixtures have rebound sase.config.core.CONFIG_DIR: "
        f"{offenders}"
    )


def test_host_config_layer_guard_rejects_real_sase_config_layers(
    tmp_path: Path,
) -> None:
    with pytest.raises(AssertionError, match="real host SASE config layer"):
        _assert_not_real_host_sase_config_layer(_REAL_HOST_SASE_CONFIG_DIR / "sase.yml")

    _assert_not_real_host_sase_config_layer(tmp_path / ".config" / "sase" / "sase.yml")
