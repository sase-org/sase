"""Compatibility shim for :mod:`sase.ace.patch.cache`."""

import sys as _sys

from sase.ace.patch import cache as _cache_module
from sase.ace.patch.cache import *  # noqa: F403

_sys.modules[__name__] = _cache_module
