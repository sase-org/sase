---
create_time: 2026-07-07 17:49:34
status: done
prompt: sdd/prompts/202607/telegram_update_core.md
---
# Fix Telegram `/update` Missing `sase-core` Dev Checkout Updates

## Diagnosis

Telegram `/update` reaches SASE through the mobile/chat update bridge:

- `sase.integrations._mobile_helper_updates.update_start_response()`
- `sase.integrations.chat_install.start_chat_install_worker()`
- detached worker in `sase.integrations.chat_install._run_worker()`
- subprocess command from `sase.integrations._chat_install_worker.run_update_command()`: `python -m sase update --json`

That means Telegram currently follows the top-level CLI `sase update` path, not the TUI Admin Center path directly.

The two paths do not choose the same editable dev-update targets:

- The TUI full SASE update path calls `make_sase_dev_update_preview()` and targets every editable runtime inventory
  record whose role is `host`, `core`, or `plugin`.
- The CLI path calls `dev_route()` and targets only editable packages that are present as top-level uv-tool receipt
  requirements.

`sase-core-rs` is a runtime package with role `core`, but it is normally a dependency of `sase`, not a top-level uv-tool
requirement. In an editable/dev install it can therefore appear in the runtime inventory while not appearing in the
uv-tool receipt. The CLI route omits it, so the Telegram worker can update `sase` and editable plugins while leaving the
sibling `sase-core` checkout untouched.

## Implementation Plan

1. Update the CLI dev-update target selection so `sase update` includes editable runtime core packages in addition to
   editable receipt requirements.
   - Keep receipt order for receipt-listed packages.
   - Append editable `role == "core"` records discovered in the runtime inventory when they are not already included.
   - Preserve the existing error for receipts that contain editable packages but no matching runtime records, but do not
     require core records to be present.
   - Leave managed-package routing unchanged: the uv-tool receipt still controls which non-editable requirements require
     a managed `uv tool upgrade` pass.

2. Add focused CLI routing tests.
   - Cover a dev receipt containing editable `sase` and plugins plus a runtime editable `sase-core-rs` record, and
     assert `plan_dev_update` receives `sase`, the plugins, and `sase-core-rs`.
   - Assert the JSON/update result reports the core package as an updated dev package when included.
   - Add a lower-level `dev_route()` test if needed to pin ordering and deduplication without exercising the full
     command handler.

3. Add a Telegram/mobile bridge regression test at the worker boundary.
   - The bridge should continue launching the shared worker, but the worker’s subprocess output parsing should recognize
     dev JSON containing `sase-core-rs` as an updated package.
   - This keeps the test focused on the contract Telegram depends on without requiring the external Telegram plugin
     repo.

4. Verify with targeted tests first, then the repo check required by project instructions.
   - Run `just install` if the workspace environment needs setup.
   - Run targeted tests covering update routing and chat install worker behavior.
   - Run `just check` before finishing because production/test files in this repo will be changed.

## Expected Result

Telegram `/update`, the mobile helper update bridge, and direct `sase update` all use the same comprehensive dev-update
target set as the TUI full SASE update path: editable `sase`, editable `sase-core-rs`, and editable installed plugins
are planned, fast-forwarded, reconciled, and reported together.
