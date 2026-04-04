---
create_time: 2026-04-04 14:43:28
status: done
---

# Plan: Fix Silent Mentor Profile Matching Failures

## Problem

`sase axe` is not adding MENTORS entries to ChangeSpecs that should match mentor profiles (e.g., Java files matching
`**/*.java`). The issue is undiagnosable because the entire mentor matching pipeline silently swallows errors at
multiple levels.

## Root Cause

The mentor matching code path has **three layers of silent failure**:

1. **`get_all_mentor_profiles()`** (`src/sase/config/mentor.py:212-214`) — catches `FileNotFoundError` and `ValueError`,
   returns `[]` with no logging. If the plugin config fails to load, zero profiles are found and nothing is reported.

2. **`add_mentor_entry()`** (`src/sase/ace/mentors/entries.py:80`) — bare `except Exception: return False` swallows ALL
   errors (file locking failures, parse errors, write errors) with no logging.

3. **`_profile_matches_commit()`** (`src/sase/ace/scheduler/mentor_profile_matching.py:84-127`) — file I/O with no
   try/except. Any access error (permissions, missing file, encoding) crashes the entire chop script process. The
   lumberjack captures the stderr but the error is cryptic.

Additionally, `add_matching_profiles_upfront()` provides no diagnostic output when it finds zero matching profiles,
making it impossible to distinguish "no profiles loaded" from "profiles loaded but none matched" from "profiles matched
but add_mentor_entry failed".

## Changes

### 1. `src/sase/config/mentor.py` — Log when profile loading fails

In `get_all_mentor_profiles()`, add `logging.warning()` before returning empty list on exception. This surfaces plugin
config loading failures that currently vanish silently.

### 2. `src/sase/ace/mentors/entries.py` — Log exceptions in `add_mentor_entry()`

Replace the bare `except Exception: return False` with `except Exception` that logs the exception before returning
False. Same treatment for `clear_mentor_draft_flags()`, `set_mentor_draft_flags()`, and `remove_mentor_data()` which all
have the same pattern.

### 3. `src/sase/ace/scheduler/mentor_profile_matching.py` — Add diagnostic logging and error resilience

- In `_profile_matches_commit()`: wrap file I/O in try/except so a single bad diff file doesn't crash the entire chop
  script. Log the error and continue checking other criteria.
- In `add_matching_profiles_upfront()`: add diagnostic `log()` calls showing how many profiles were loaded, how many
  commits were checked, and the match result. This output goes to the chop script's stdout, which the lumberjack
  captures and logs.

### 4. `src/sase/ace/scheduler/mentor_checks.py` — Add Phase 2 diagnostic

Add a `log()` call at Phase 2 showing the number of loaded mentor profiles, so we can tell from axe logs whether the
plugin config was loaded.
