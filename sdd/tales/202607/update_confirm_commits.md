---
create_time: 2026-07-07 14:24:14
status: done
prompt: sdd/prompts/202607/update_confirm_commits.md
---
# Plan: Show All Repo Commit Groups in Update Confirmation

## Problem

The `u` action from the Admin Center Updates tab opens a confirmation modal for `sase update`. In editable/dev mode, the
modal command summary correctly lists every checkout that will be fetched and fast-forwarded, such as `sase`,
`sase-core`, and installed editable plugin repos. However, the visible "Incoming commits" panel can appear to show only
the main `sase` repo.

## Diagnosis

The current data plumbing is mostly correct:

- `SaseUpdateActionsMixin._open_sase_dev_update_modal()` passes `_dev_update_incoming_commits_loader(plan)` into
  `PluginActionConfirmModal`.
- `_dev_update_incoming_commits_loader()` builds one commit source spec for every `plan.actionable_roots` entry.
- `PluginActionConfirmModal._apply_incoming_commit_groups()` already accepts and renders multiple `RepoIncomingCommits`
  groups.

The likely root cause is presentation, not missing commit collection. The default confirmation preview limit is
`ace.updates.incoming_commits.confirm_max_per_repo: 250`. The modal renders the full first repo group before the next
group. When `sase` has enough incoming commits, it fills the visible commits pane and pushes `sase-core` and plugin
groups below the initial viewport. The right-side scrollbar in the screenshot is consistent with this: more content
likely exists, but the first visible screen is monopolized by the main repo.

There is also a test gap: existing tests verify the modal can render multiple groups when each group is short, and full
`sase update` tests only assert that an incoming-commit loader exists. Nothing verifies that a long first repo still
leaves later repos visible in the confirmation panel.

## Proposed Fix

Make the confirmation modal render multi-repo incoming commits in a balanced preview format:

1. Preserve existing commit fetching behavior and background threading.
   - Do not add synchronous git/GitHub work to the Textual event loop.
   - Continue using the existing loader and `run_worker(..., thread=True)` path.

2. Add a confirmation-modal-specific grouped renderer.
   - For multiple repo groups, render all group headers first or cap the initial per-group visible commit count so every
     repo with incoming commits appears in the first viewport.
   - Keep total counts accurate using the existing `IncomingCommits.total` and `extra` fields.
   - Preserve scroll support so users can still inspect longer details.

3. Keep single-repo behavior effectively unchanged.
   - If only one repo has incoming commits, it can still use the current detailed list behavior.
   - The change should primarily affect multi-repo confirmations.

4. Make unavailable/empty groups explicit enough to diagnose failures.
   - If a repo group was requested but fetching failed, keep the existing unavailable message with the repo label.
   - If no groups are returned, continue hiding the commits panel.

## Tests

Add focused regression coverage:

- Unit/widget test for `PluginActionConfirmModal` with a long `sase` group followed by `sase-core` and a plugin group.
  Assert the rendered body includes the later repo labels before scrolling.
- Full Updates-tab `u` dev-update test using a `DevUpdatePlan` with three actionable roots and a fake
  `_fetch_incoming_commit_groups` result. Assert the confirmation modal commit body includes `sase`, `sase-core`, and
  the plugin label.
- Preserve or update existing grouped modal tests so short grouped previews still render commit subjects and counts.

## Verification

After code changes, run:

- The targeted modal/update tests for incoming commit previews.
- `just install`, then `just check`, because this repo requires it after file changes.

If visual output changes materially, run the relevant ACE PNG snapshot tests and inspect/update goldens only if the
changed preview layout is intentional.
