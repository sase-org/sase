---
create_time: 2026-05-07 21:06:57
status: done
prompt: sdd/prompts/202605/vcs_xprompt_mru_test_history.md
---
# Stop VCS XPrompt MRU Test Writes From Polluting User History

## Problem

Tests can write VCS xprompt workflow references such as `#cd:/tmp/pytest-of-bryan/...` into the real prompt-input VCS
MRU history. Those entries later show up in the prompt input widget via the `ctrl+p` / `ctrl+n` MRU cycling keymap.

The leaked state is not normal prompt history. The prompt input widget cycles
`sase.history.vcs_xprompt_mru.load_launchable_vcs_xprompt_mru()`, which reads `~/.sase/vcs_xprompt_mru.json`. The launch
path records entries through `_record_resolved_vcs_xprompt_usage()` in
`src/sase/ace/tui/actions/agent_workflow/_agent_launch.py`.

## Root Cause

The test suite has an autouse fixture in `tests/conftest.py` that redirects `~/.sase/...` expansions into a per-test
temp directory. That fixture patches `Path.expanduser()` and `os.path.expanduser()`.

`src/sase/history/vcs_xprompt_mru.py` bypasses that isolation by defining
`_MRU_FILE = Path.home() / ".sase" / "vcs_xprompt_mru.json"` at import time. This path does not go through
`expanduser()`, so tests that do not explicitly patch `_MRU_FILE` can write to the developer's real `~/.sase` directory.

The observed `#cd:/tmp/pytest-...` entry is plausibly produced by
`tests/ace/tui/test_agent_launch_non_blocking.py::test_run_agent_launch_body_cd_keeps_home_mode_and_uses_target_dir`,
which patches normal prompt history but does not patch VCS MRU recording.

## Implementation Plan

1. Update `src/sase/history/vcs_xprompt_mru.py` so all file access resolves the MRU path at operation time via a small
   helper like `_mru_file()` returning `Path("~/.sase/vcs_xprompt_mru.json").expanduser()`.

2. Preserve test override ergonomics by keeping `_MRU_FILE` as the default path object if useful, but make it use the
   `~/.sase/...` form so existing tests that patch `_MRU_FILE` still work.

3. Update reads, writes, and parent directory creation in `load_vcs_xprompt_mru()` and `_save_vcs_xprompt_mru()` to use
   the resolved helper path. Leave the MRU semantics unchanged: load filters bad data, record moves prefixes to the
   front, stale known projects are pruned, and the list is capped.

4. Keep `record_vcs_xprompt_usage("#cd:/tmp/...")` valid in production. The issue is test isolation, not that users
   should be unable to MRU-cycle a real directory launch they intentionally used.

5. Add a regression test that uses the suite's `redirect_sase_home()` helper, records a `#cd:<tmp_path>` prefix without
   patching `_MRU_FILE`, and asserts: the isolated fake SASE home receives `vcs_xprompt_mru.json`; the real home path is
   not the target path under the patched expansion.

6. Add or adjust an agent-launch regression test around the `#cd:<tmp_path>` path only if needed after the lower-level
   MRU test. The lower-level test is preferred because it directly protects the filesystem isolation boundary.

7. Verify with targeted tests first:
   `pytest tests/test_vcs_xprompt_mru.py tests/ace/tui/test_agent_launch_non_blocking.py::test_run_agent_launch_body_cd_keeps_home_mode_and_uses_target_dir`

8. Because this repo requires it after file changes, run `just install` if needed and then `just check` before reporting
   back.

## Risks

- Other history modules still have import-time `Path.home()` constants. This plan intentionally scopes the change to the
  VCS MRU leak that affects `ctrl+p` cycling. A broader history-path cleanup can be a separate pass.
- Tests that patch `_MRU_FILE` with concrete temp paths should continue to pass if the helper respects patched absolute
  paths.
