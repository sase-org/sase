"""Facade preserving the original Grok core test module import path.

The tests formerly in this module now live in focused siblings:

- :mod:`tests.llm_provider.test_grok_provider_metadata`
- :mod:`tests.llm_provider.test_grok_provider_invocation`
- :mod:`tests.llm_provider.test_grok_provider_stream`
- :mod:`tests.llm_provider.test_grok_provider_rules`

Shared fixtures live in :mod:`tests.llm_provider._grok_provider_core_helpers`.
Only the public fixture-directory constant is re-exported here.
"""

from .test_grok_provider_stream import GROK_STREAM_FIXTURES

__all__ = ["GROK_STREAM_FIXTURES"]
