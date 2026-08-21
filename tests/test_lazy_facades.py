"""Import contracts for package-level lazy re-export facades."""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest


_CASES = (
    (
        "sase.core",
        "generate_timestamp",
        "sase.core.time",
        (
            "sase.core.changespec",
            "sase.core.clipboard",
            "sase.core.glossary_facade",
            "sase.core.patch",
            "sase.core.paths",
            "sase.core.shell",
            "sase.core.time",
        ),
    ),
    (
        "sase.sdd",
        "ensure_beads_initialized",
        "sase.sdd.beads",
        ("sase.sdd.beads", "sase.sdd.files", "sase.sdd.store"),
    ),
    (
        "sase.workspace_provider",
        "CheckoutMarker",
        "sase.workspace_provider.marker",
        (
            "sase.workspace_provider._hookspec",
            "sase.workspace_provider._plugin_manager",
            "sase.workspace_provider._registry",
            "sase.workspace_provider.lookup",
            "sase.workspace_provider.marker",
            "sase.workspace_provider.ownership",
            "sase.workspace_provider.registry",
        ),
    ),
)


@pytest.mark.parametrize(
    ("package", "sample", "owner", "forbidden_after_import"),
    _CASES,
)
def test_package_facades_are_lazy_and_cache_exports(
    package: str,
    sample: str,
    owner: str,
    forbidden_after_import: tuple[str, ...],
) -> None:
    source = textwrap.dedent(
        f"""
        import importlib
        import sys

        package = {package!r}
        sample = {sample!r}
        owner = {owner!r}
        forbidden_after_import = {forbidden_after_import!r}

        module = importlib.import_module(package)
        loaded = [name for name in forbidden_after_import if name in sys.modules]
        assert not loaded, loaded
        missing_from_dir = [name for name in module.__all__ if name not in dir(module)]
        assert not missing_from_dir, missing_from_dir

        value = getattr(module, sample)
        assert owner in sys.modules, (owner, sorted(sys.modules))
        assert getattr(module, sample) is value

        namespace = {{}}
        exec(f"from {{package}} import {{sample}} as imported", namespace)
        assert namespace["imported"] is value
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout


def test_core_lazy_facade_preserves_legacy_changespec_export() -> None:
    source = textwrap.dedent(
        """
        import sase.core
        from sase.core import get_workspace_directory_for_changespec

        assert (
            sase.core.get_workspace_directory_for_changespec
            is get_workspace_directory_for_changespec
        )
        assert "get_workspace_directory_for_changespec" in dir(sase.core)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
