# Memory Episodes E2E Fixture

This fixture is materialized into a temporary directory by `tests/test_memory_episodes_e2e.py`. Files ending in `.tmpl`
use absolute path tokens so the checked-in fixture can exercise the real collector and CLI without depending on the
developer machine's `~/.sase` state.
