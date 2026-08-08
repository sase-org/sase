"""Compatibility shim for :mod:`sase.ace.patch.suffix_utils`."""

import sys as _sys

from sase.ace.patch import suffix_utils as _suffix_utils_module
from sase.ace.patch.suffix_utils import *  # noqa: F403

_sys.modules[__name__] = _suffix_utils_module
