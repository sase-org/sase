---
create_time: 2026-03-30 10:39:59
status: done
prompt: sdd/prompts/202603/retain_focus_after_name_change.md
---

# Plan: Retain ChangeSpec Focus After Status-Induced Name Changes

## Problem

When a ChangeSpec's name changes during a status transition in the `sase ace` TUI, the selection jumps to a different
ChangeSpec. The user reports this specifically for Draft->Ready (where the `_<N>` suffix is stripped), but the issue
affects all name-changing transitions.

## Root Cause

`_reload_and_reposition()` in `changespec.py:126-149` only searches by **exact name match**. When the name changes
(suffix stripped or appended), the exact match fails and the selection defaults to index 0.

While `_apply_status_change()` in `status.py:233-236` has special handling for Draft->Ready with suffix (computing the
new name via `strip_reverted_suffix` and passing it explicitly), this approach has two problems:

1. **Incomplete coverage**: Only Draft->Ready with suffix is handled. WIP->Ready with suffix and Ready->Draft (suffix
   append) are NOT handled -- both fall through to `_reload_and_reposition()` without a `current_name`, using the old
   (now non-existent) name from `self.changespecs[current_idx]`.

2. **Auto-refresh race**: The auto-refresh timer (`_on_auto_refresh` at `event_handlers.py:71-96`) calls
   `_reload_and_reposition()` without a name. If it fires during `self.suspend()` (while the transition runs with
   console output for sibling reverts), it reads the old name from `self.changespecs`, can't find it on disk, and resets
   to index 0. While the subsequent explicit call at line 236 would fix this, there's a window where the state is wrong.

## Solution

Add a **base name fallback search** to `_reload_and_reposition()`. When the exact name match fails, try matching by base
name (suffix-stripped identity). This handles ALL name-changing transitions in one place, and also makes auto-refresh
resilient to name changes.

### Changes

#### 1. `src/sase/ace/tui/actions/changespec.py` -- Add base name fallback to `_reload_and_reposition`

After the exact name match loop fails, add a two-stage fallback:

1. Try to find a ChangeSpec whose name IS the base name (handles suffix strip: `foo_1` -> `foo`)
2. Try to find a ChangeSpec whose base name matches (handles suffix append: `foo` -> `foo_1`)

```python
def _reload_and_reposition(self, current_name: str | None = None) -> None:
    ...
    new_idx = 0
    if current_name:
        for idx, cs in enumerate(new_changespecs):
            if cs.name == current_name:
                new_idx = idx
                break
        else:
            # Name changed (suffix strip/append) -- match by base name
            from sase.core.changespec import strip_reverted_suffix
            base = strip_reverted_suffix(current_name)
            # Prefer exact base name (suffix was stripped)
            for idx, cs in enumerate(new_changespecs):
                if cs.name == base:
                    new_idx = idx
                    break
            else:
                # Try any CS with same base name (suffix was appended)
                for idx, cs in enumerate(new_changespecs):
                    if strip_reverted_suffix(cs.name) == base:
                        new_idx = idx
                        break
    ...
```

This cascading search correctly handles:

- **Draft/WIP -> Ready** (suffix strip): `current_name="foo_1"`, base=`"foo"`, first fallback finds `"foo"` exactly
- **Ready -> Draft** (suffix append): `current_name="foo"`, base=`"foo"` (same), first fallback fails (no `"foo"`),
  second fallback finds `"foo_1"` whose base is `"foo"`
- **Auto-refresh during transition**: Same fallback logic applies, preventing index-0 reset

#### 2. `src/sase/ace/tui/actions/status.py` -- Simplify `_apply_status_change`

Remove the special `may_have_sibling_reverts` name computation at lines 233-238 and always call
`_reload_and_reposition()` without explicit name. The improved fallback in `_reload_and_reposition` handles it.

Before:

```python
if success and may_have_sibling_reverts:
    new_name = strip_reverted_suffix(changespec.name)
    self._reload_and_reposition(current_name=new_name)
else:
    self._reload_and_reposition()
```

After:

```python
self._reload_and_reposition()
```

The `may_have_sibling_reverts` variable and its computation at lines 184-188 can stay since it's still used to decide
whether to suspend for console output (lines 190-214).

#### 3. Tests

Add test coverage for `_reload_and_reposition` to verify:

- Exact name match still works
- Base name fallback finds suffix-stripped CS
- Base name fallback finds suffix-appended CS
- Falls back to index 0 when no match at all

## Name-Changing Transitions Covered

| Transition                     | Name Change      | Before Fix                     | After Fix           |
| ------------------------------ | ---------------- | ------------------------------ | ------------------- |
| Draft -> Ready (with suffix)   | `foo_1` -> `foo` | Explicitly handled but fragile | Handled by fallback |
| WIP -> Ready (with suffix)     | `foo_1` -> `foo` | NOT handled (resets to 0)      | Handled by fallback |
| Ready -> Draft                 | `foo` -> `foo_1` | NOT handled (resets to 0)      | Handled by fallback |
| Auto-refresh during transition | Any of above     | Resets to 0                    | Handled by fallback |
