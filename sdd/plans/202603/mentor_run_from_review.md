---
create_time: 2026-03-22 19:22:16
status: done
prompt: sdd/prompts/202603/mentor_run_from_review.md
---

# Plan: Run Mentor Profile from Mentor Review Panel

## Summary

Add the ability to manually trigger mentor profiles from the Mentor Review modal. Users press `r` to open a profile
picker showing all configured `mentor_profiles`, with status indicators for profiles already active on the current
entry. Selecting a profile starts its mentors as background processes.

## UX Flow

1. User opens Mentor Review modal (`,m`)
2. Presses `r` → **Mentor Profile Select** modal opens on top
3. Modal shows all configured `mentor_profiles`:
   - `●` yellow = mentors currently running for this entry
   - `✓` green = all mentors completed (COMMENTED/PASSED)
   - `✗` red = some mentors failed
   - No indicator = profile not yet run
   - Each entry shows profile name + mentor count
4. j/k navigation, Enter to select, q/Esc to cancel
5. On selection, review modal dismisses with `MentorRunResult`
6. Mixin handler adds the profile to the MENTORS entry (if needed), starts unstarted mentors, shows notification

## Files to Create

### 1. `src/sase/ace/tui/modals/mentor_profile_select_modal.py`

New modal for selecting a mentor profile to run.

```python
class MentorProfileSelectModal(CopyModeForwardingMixin, ModalScreen[str | None]):
```

**Constructor args:**

- `profiles: list[MentorProfileConfig]` - all configured profiles
- `existing_mentors: list[_MentorInfo]` - mentors already in the review data (for status display)

**UI layout:**

- Container with title "Run Mentor Profile"
- Static widget showing the profile list (Rich Text, custom rendered)
- Footer with keybinding hints

**Keybindings:**

- `j/k` - navigate profiles
- `Enter` - select profile (dismiss with `profile_name`)
- `q/Escape` - close (dismiss with `None`)

**Rendering:**

- Each profile line shows: selection indicator, profile name, mentor count, status badge
- Status is derived by cross-referencing `existing_mentors` with profile's mentors
- Matches the color scheme of the review modal (cyan headers, green selection, etc.)

## Files to Modify

### 2. `src/sase/ace/tui/modals/mentor_review_modal.py`

**Add `MentorRunResult` dataclass:**

```python
@dataclass
class MentorRunResult:
    profile_name: str
    cl_name: str
    entry_id: str
```

**Add `r` binding to `MentorReviewModal.BINDINGS`:**

```python
("r", "run_profile", "Run mentor profile"),
```

**Add `action_run_profile` method:**

- Load all mentor profiles via `get_all_mentor_profiles()`
- If no profiles configured, show notification and return
- Push `MentorProfileSelectModal` with profiles + current mentors data
- On dismiss: if profile selected, dismiss self with `MentorRunResult`

**Update `_update_footer`:**

- Add `("r", "run")` to the bindings list

**Update modal return type:**

```python
class MentorReviewModal(
    CopyModeForwardingMixin,
    ModalScreen[MentorApplyResult | MentorKillResult | MentorRunResult | None]
):
```

### 3. `src/sase/ace/tui/actions/agent_workflow/_mentor_review.py`

**Update `on_mentor_review_dismiss` callback:**

- Add `isinstance(result, MentorRunResult)` check
- Call new `_run_mentor_profile(result, project_file)` method

**Add `_run_mentor_profile` method:**

```python
def _run_mentor_profile(self, run_result, project_file):
```

- Load the profile via `get_mentor_profile_by_name(run_result.profile_name)`
- Re-parse the project file for fresh state (concurrency safety)
- Call `add_mentor_entry()` to ensure profile is in the MENTORS entry
- Determine which mentors are already started (from status lines)
- Call `_start_single_mentor()` for each unstarted mentor
- Show notification with count of started mentors
- Call `_reload_and_reposition()` to refresh the TUI

### 4. `src/sase/ace/tui/modals/__init__.py`

- Import and export `MentorRunResult` from `mentor_review_modal`
- Import and export `MentorProfileSelectModal` from `mentor_profile_select_modal`

### 5. `src/sase/ace/tui/styles.tcss`

Add styles for the profile select modal:

- `#mentor-profile-select-container` - sized to ~50% width, ~40% height, centered, double border
- `#mentor-profile-select-title` - centered bold title
- `#mentor-profile-select-list` - scrollable profile list area
- `#mentor-profile-select-footer` - bottom keybinding hints

## Key Implementation Details

### Starting Mentors Manually

Uses `_start_single_mentor()` from `src/sase/ace/scheduler/mentor_runner.py`. This function:

1. Generates a timestamp
2. Marks the mentor as STARTING in the project file
3. Spawns the mentor runner subprocess
4. Marks as RUNNING with PID tracking

Before calling it, we must:

1. Ensure the profile exists in the MENTORS entry via `add_mentor_entry()`
2. Check which mentors already have status lines (to skip already-started ones)
3. Re-read the ChangeSpec from disk for concurrency safety

### Status Indicators in Profile Select

For each profile, derive status by checking `existing_mentors`:

- Collect all `_MentorInfo` entries whose `profile_name` matches
- If any are running → `● running` (yellow)
- If all are terminal (COMMENTED/PASSED/FAILED) → `✓ done` (green) or `✗ failed` (red)
- If none found → no indicator (profile hasn't been run)

### Edge Cases

- **No profiles configured:** Show notification "No mentor profiles configured"
- **All mentors already running:** Start nothing, notify "All mentors already running for {profile}"
- **No MENTORS entry exists:** `add_mentor_entry()` creates one
- **Profile already in entry but mentors not started:** Start the unstarted mentors
