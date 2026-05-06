---
create_time: 2026-05-06 17:53:51
status: done
prompt: sdd/prompts/202605/sase_26_5_completion.md
---
# Plan: Finish sase-26.5 Android Pairing-To-Inbox Integration

## Context

Verification of bead `sase-26.5` found the Android foundation mostly complete in `../sase-android`, with all phase beads
closed and the copied mobile API contract matching `../sase-core`. The remaining functional gap is in the final app
integration path: `NotificationRepository.start()` runs once when `SaseMobileApp` is composed. If the app starts
unpaired, the repository observes no session, enters logged-out state, and does not automatically restart after the user
pairs a gateway from Settings.

This misses the epic requirement that the repository refresh after successful pairing and leaves SSE live sync dependent
on manual refresh or app restart.

## Goal

Make successful pairing immediately activate the notification foundation:

- after Settings completes pairing, the app restarts the notification repository;
- the repository loads cached state, performs a full refresh, and starts the SSE loop for the newly paired host;
- repeated starts do not create duplicate SSE loops;
- forgetting a host stops live notification sync cleanly.

## Implementation

1. Update `NotificationRepository` in `../sase-android` so `start()` owns a single active coroutine job. Restarting
   should cancel the previous job, reset `stopped`, load cache, refresh if a session exists, and run the SSE loop.
2. Update `SaseMobileApp` in `../sase-android` to observe `SessionController.state`. Derive the paired host key from the
   session status and restart/stop notification sync when the paired host changes.
3. Add focused tests:
   - repository `start()` can be called again after a session is added and then performs the full refresh;
   - app smoke no longer needs a manual inbox refresh immediately after pairing.
4. Re-run the strongest available Android gate. If local SDK license acceptance still blocks Gradle, record the exact
   blocker and run lighter checks that do not require the Android SDK where possible.

## Definition Of Done

- Pairing from the app transitions into a populated inbox path without app restart or manual refresh.
- Notification repository restarts are idempotent enough to avoid duplicate long-running loops.
- Existing bead notes about Android SDK license blocking remain true if the same Gradle gate cannot run locally.
