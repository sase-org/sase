"""Compatibility shim for :mod:`sase.ace.patch.archive`."""

import sys as _sys

from sase.ace.patch import archive as _archive_module
from sase.ace.patch.archive import *  # noqa: F403

_sys.modules[__name__] = _archive_module
