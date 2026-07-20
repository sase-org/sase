"""Safety guard for axe daemon lifecycle changes under pytest."""

import os
from collections.abc import Mapping


AXE_LIFECYCLE_TEST_OVERRIDE_ENV = "SASE_AXE_ALLOW_LIFECYCLE_IN_TESTS"
AXE_LIFECYCLE_TEST_BLOCK_MESSAGE = (
    "Axe lifecycle changes are disabled while running under pytest. Set "
    f"{AXE_LIFECYCLE_TEST_OVERRIDE_ENV}=1 only for isolated lifecycle tests."
)
_PYTEST_CONTEXT_ENV_VARS = ("PYTEST_CURRENT_TEST", "PYTEST_VERSION")


def axe_lifecycle_blocked_in_tests(
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Return whether axe lifecycle changes must be refused in this process."""
    effective_environ = os.environ if environ is None else environ
    if effective_environ.get(AXE_LIFECYCLE_TEST_OVERRIDE_ENV) == "1":
        return False
    return any(name in effective_environ for name in _PYTEST_CONTEXT_ENV_VARS)


__all__ = [
    "AXE_LIFECYCLE_TEST_BLOCK_MESSAGE",
    "AXE_LIFECYCLE_TEST_OVERRIDE_ENV",
    "axe_lifecycle_blocked_in_tests",
]
