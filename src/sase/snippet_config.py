"""Snippet configuration loading and validation.

DEPRECATED: This module is deprecated. Use xprompt.loader instead.
This module now wraps xprompt.loader for backward compatibility.
"""

from sase.xprompt.loader import get_all_xprompts

__all__ = ["get_all_xprompts"]
