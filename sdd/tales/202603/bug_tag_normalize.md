---
create_time: 2026-03-31 21:12:29
status: done
prompt: sdd/prompts/202603/bug_tag_normalize.md
---

# Plan: VCS-Agnostic BUG Tag Normalization

## Problem

The BUG tag sync added in the previous commit hardcodes `http://b/<id>` normalization in `reword.py:255-261`. This
format is Google-specific. GitHub PRs (and bare git repos) should not use that format — they should pass the value
through unchanged (or apply their own normalization).

## Design

Follow the established `prepare_description_for_reword()` pattern: add a new optional method to the VCS provider
interface with a sensible default, let plugins override it.

### Pattern Reference

The `prepare_description_for_reword(description)` method demonstrates the exact pattern:

- **Base class** (`_base.py`): default returns `description` unchanged
- **Hookspec** (`_hookspec.py`): `@hookspec(firstresult=True)` declaration
- **Plugin manager** (`_plugin_manager.py`): delegates to hook, falls back to default if no plugin handles it
- **Google plugin** (`retired Mercurial plugin/plugin.py`): overrides to escape special chars for hg
- **GitHub plugin**: does not override (uses default)

## Phase 1: Add `normalize_bug_value()` to VCS Provider Interface

### 1a. Base class (`src/sase/vcs_provider/_base.py`)

Add after `prepare_description_for_reword()` in the VCS-agnostic section:

```python
def normalize_bug_value(self, tag_value: str) -> str:
    """Normalize a BUG tag value for storage in a ChangeSpec.

    The default implementation returns the value unchanged.
    Providers with a canonical bug URL format (e.g. ``http://b/<id>``)
    should override this method.
    """
    return tag_value
```

### 1b. Hookspec (`src/sase/vcs_provider/_hookspec.py`)

Add after `vcs_prepare_description_for_reword`:

```python
@hookspec(firstresult=True)
def vcs_normalize_bug_value(self, tag_value: str) -> str: ...
```

### 1c. Plugin manager (`src/sase/vcs_provider/_plugin_manager.py`)

Add after `prepare_description_for_reword()`:

```python
def normalize_bug_value(self, tag_value: str) -> str:
    result = self._pm.hook.vcs_normalize_bug_value(tag_value=tag_value)
    if result is None:
        return tag_value
    return result
```

## Phase 2: Google Plugin Override (`../retired Mercurial plugin`)

In `retired Mercurial plugin/src/retired_mercurial_plugin/plugin.py`, add after `vcs_prepare_description_for_reword`:

```python
@hookimpl
def vcs_normalize_bug_value(self, tag_value: str) -> str:
    bug_id = (
        tag_value.removeprefix("https://b/")
        .removeprefix("http://b/")
        .removeprefix("b/")
    )
    return f"http://b/{bug_id}"
```

## Phase 3: Update `reword.py` to Use Provider Method

Replace the hardcoded normalization in `src/sase/ace/handlers/reword.py:249-267` with:

```python
if tag_name.upper() == "BUG":
    from sase.status_state_machine.field_updates import update_changespec_bug_atomic

    try:
        bug_value = provider.normalize_bug_value(tag_value)
        update_changespec_bug_atomic(changespec_file_path, changespec_name, bug_value)
        print("Synced BUG field to project file")
    except Exception as exc:
        print(f"Warning: failed to sync BUG field: {exc}")
```

The `provider` variable is already in scope (line 228).

## Phase 4: Tests

### 4a. sase core tests

Add a test in `tests/vcs_provider/` verifying `VCSPluginManager.normalize_bug_value()` returns the value unchanged when
no plugin overrides it (the default/GitHub behavior).

### 4b. retired Mercurial plugin tests

Add a test in `../retired Mercurial plugin/tests/test_hg_plugin.py` verifying the Google provider normalizes various input formats to
`http://b/<id>`:

- Bare ID: `"487724502"` → `"http://b/487724502"`
- With prefix: `"b/487724502"` → `"http://b/487724502"`
- Already normalized: `"http://b/487724502"` → `"http://b/487724502"` (idempotent)

## Non-Goals

- GitHub plugin does **not** need an override — the default (passthrough) is correct.
- No changes to `field_updates.py` — it writes whatever value it receives.
