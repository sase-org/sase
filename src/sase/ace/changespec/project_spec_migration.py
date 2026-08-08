"""Compatibility shim for :mod:`sase.ace.patch.project_spec_migration`."""

import sys as _sys

from sase.ace.patch import project_spec_migration as _project_spec_migration_module
from sase.ace.patch.project_spec_migration import *  # noqa: F403

_sys.modules[__name__] = _project_spec_migration_module
