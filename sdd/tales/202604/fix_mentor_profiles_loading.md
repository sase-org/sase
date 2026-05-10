---
create_time: 2026-04-04 16:13:52
status: done
prompt: sdd/prompts/202604/fix_mentor_profiles_loading.md
---

# Fix MENTORS ChangeSpec field not being populated by sase axe

## Problem

`sase axe` logs show `Phase 2: 0 mentor profile(s) loaded from config` for every ChangeSpec, meaning the MENTORS field
is never populated. This affects all ChangeSpecs globally.

## Root Cause

In `retired Mercurial plugin/src/retired_mercurial_plugin/default_config.yml`, the `bugs` mentor in the `code` profile (line 100-104) has
`focus_areas` formatted as a flat dict instead of a list:

```yaml
- mentor_name: bugs
  role: "QA reviewer"
  focus_areas:
    focus_name: bugs # <-- Missing '-' prefix!
    description: >-
      Review the code changes...
```

YAML parses this as `{'focus_name': 'bugs', 'description': '...'}` (a dict) instead of
`[{'focus_name': 'bugs', 'description': '...'}]` (a list of one dict).

**Failure chain:**

1. `_load_mentor_profiles()` in `src/sase/config/mentor.py:149` validates `isinstance(focus_areas, list)` and raises
   `ValueError`
2. `get_all_mentor_profiles()` catches the `ValueError` at line 217 and returns `[]`
3. All ChangeSpecs see 0 profiles, so MENTORS is never populated

**Compounding factor:** The validation loop in `_load_mentor_profiles()` is all-or-nothing — a single invalid profile
raises a `ValueError` that aborts loading of ALL profiles, even valid ones.

## Changes

### Phase 1: Fix the YAML (retired Mercurial plugin repo)

**File:** `retired Mercurial plugin/src/retired_mercurial_plugin/default_config.yml` (line 100-104)

Add the missing `-` and fix indentation so `focus_areas` is a list:

```yaml
focus_areas:
  - focus_name: bugs
    description: >-
      Review the code changes...
```

### Phase 2: Make profile loading resilient (sase core repo)

**File:** `src/sase/config/mentor.py` — `_load_mentor_profiles()`

Change the profile parsing loop to catch `ValueError` per-profile (log a warning and skip the bad profile) instead of
letting one bad profile abort the entire list. This way, a YAML typo in one profile doesn't silently disable all mentor
matching.
