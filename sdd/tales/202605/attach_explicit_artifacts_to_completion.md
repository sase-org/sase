---
create_time: 2026-05-13 16:54:50
status: done
prompt: sdd/prompts/202605/attach_explicit_artifacts_to_completion.md
---
# Attach explicit agent artifacts to completion notifications

## Problem

When an agent calls `sase artifact create`, the produced file is moved into the persistent artifact store under
`~/.sase/artifacts/` and recorded in `~/.sase/artifacts/index.jsonl` as an explicit artifact for the agent's
`SASE_ARTIFACTS_DIR`.

The agent completion path currently builds `Notification.files` from:

- the saved chat transcript
- the diff path
- generated Markdown PDFs
- auto-discovered image paths from the workspace
- failure report/log files on failure

It does not read explicit artifacts from the artifact index. In the observed run
`/home/bryan/.sase/projects/sase/artifacts/ace-run/20260513164304`, the notification only included the chat file, while
the explicit generated PNG was correctly indexed at
`/home/bryan/.sase/artifacts/agents/sase/20260513164304/sase-3e-rust-daemon-indexed-projections-infographic-f1dadc77bbe2.png`.
The Telegram plugin already sends image/PDF/document attachments from `Notification.files`, so the missing host-side
file list entry is the root cause.

## Plan

1. Extend the SASE completion notification path in `src/sase/axe/run_agent_runner_finalize.py` so successful and failed
   completion notifications can append explicit artifact paths for the current agent run.

2. Pass the current artifacts directory from `src/sase/axe/run_agent_runner.py` into `send_completion_notification`.
   This is the stable association key used by `list_explicit_agent_artifacts`.

3. Add a small helper near completion finalization that:
   - calls `sase.core.agent_artifact_facade.list_explicit_agent_artifacts(current_artifacts_dir)`;
   - returns only artifact paths that are non-empty existing files;
   - catches index/read errors and degrades to no extra attachments so notification delivery cannot fail because the
     artifact index is unavailable;
   - leaves chat/plan/default artifacts alone and focuses on explicit artifacts created by the agent.

4. Append explicit artifact paths after the existing standard completion attachments using the existing
   `append_unique_paths` helper. This preserves current ordering, avoids duplicate sends when an artifact is also
   auto-discovered, and lets Telegram render images inline via its existing `_is_image_file` handling.

5. Add focused unit coverage in `tests/test_run_agent_runner_notifications.py`:
   - explicit artifact paths are appended to `extra_files`;
   - duplicates against chat/diff/PDF/image attachments are removed;
   - missing/unreadable explicit artifact entries do not break notification creation.

6. Verify with targeted tests first, then run the repo-required checks:
   - `just install` if needed for this workspace
   - targeted pytest for the notification tests
   - `just check`

## Out of scope

- Changing Telegram formatting or send behavior. The Telegram plugin already attaches files listed in notifications and
  sends images inline.
- Backfilling already-sent notifications. This fix should affect future completion notifications; a separate one-off
  notification can be created manually if the existing generated image needs to be resent.
