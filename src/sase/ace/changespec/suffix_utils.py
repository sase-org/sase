"""Legacy suffix parsing names backed by :mod:`sase.ace.patch.suffix_utils`."""

from sase.ace.patch.suffix_utils import ParsedSuffix, parse_suffix_prefix

_ParsedSuffix = ParsedSuffix

__all__ = ["ParsedSuffix", "_ParsedSuffix", "parse_suffix_prefix"]
