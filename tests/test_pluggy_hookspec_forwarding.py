"""Guards for hookspec arguments that pluggy will actually dispatch."""

from collections.abc import Callable
import inspect

from pluggy._hooks import varnames
import pytest

from sase.llm_provider._hookspec import LLMHookSpec
from sase.vcs_provider._hookspec import VCSHookSpec
from sase.workspace_provider._hookspec import WorkspaceHookSpec


def _hook_functions() -> list[tuple[str, str, Callable[..., object]]]:
    families = (
        ("VCSHookSpec", VCSHookSpec, "vcs_"),
        ("WorkspaceHookSpec", WorkspaceHookSpec, "ws_"),
        ("LLMHookSpec", LLMHookSpec, "llm_"),
    )
    hooks: list[tuple[str, str, Callable[..., object]]] = []
    for family_name, hookspec_class, prefix in families:
        for hook_name, fn in inspect.getmembers(
            hookspec_class, predicate=inspect.isfunction
        ):
            if hook_name.startswith(prefix):
                hooks.append((family_name, hook_name, fn))
    return hooks


@pytest.mark.parametrize(("family_name", "hook_name", "fn"), _hook_functions())
def test_hookspec_arguments_are_forwarded_by_pluggy(
    family_name: str, hook_name: str, fn: Callable[..., object]
) -> None:
    declared = [
        param_name
        for param_name in inspect.signature(fn).parameters
        if param_name != "self"
    ]
    passed, _ = varnames(fn)
    dropped = [param_name for param_name in declared if param_name not in passed]

    assert dropped == [], (
        f"{family_name}.{hook_name} declares arguments pluggy will not forward: "
        f"{dropped}"
    )
