"""Shared fixtures for VCS-aware agent launch tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_vcs_tag_pattern_cache() -> object:
    """Rebuild the lazily-cached VCS tag pattern from the real providers.

    Sibling tests patch workflow metadata to a reduced set (e.g. ``#cd`` only);
    if the global VCS tag pattern is (re)built during that window it sticks,
    dropping ``#git`` and breaking the tag-aware launch toast/guard. Reset it
    before and after each test so ``extract_vcs_workflow_tag`` reflects the
    actually-registered providers.
    """
    import sase.xprompt._parsing as parsing
    import sase.xprompt._parsing_vcs_tags as vcs_tags

    parsing._VCS_TAG_PATTERN = None
    vcs_tags._VCS_TAG_PATTERN = None
    yield
    parsing._VCS_TAG_PATTERN = None
    vcs_tags._VCS_TAG_PATTERN = None
