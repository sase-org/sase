---
create_time: 2026-04-27 10:20:04
status: planned
prompt: sdd/prompts/202604/fix_keymaps_e2e_flake.md
---

# SASE Plan: Stabilize `test_keymaps_e2e.py::test_default_keys_still_work` flake

## Context

GitHub Actions has been failing on `master` since commit `001ddc1f` ("perf(ace): cut ~230ms off `sase ace` TUI
startup"), and again on the follow-up `2ec92fa1`. The failure is always the same test:

```
FAILED tests/test_keymaps_e2e.py::test_default_keys_still_work
  - AssertionError: expect_state('idx', 1) timed out after 2.0s — last value was 0
```

The test:

```python
async def test_default_keys_still_work() -> None:
    with _patch_config():
        async with AcePage() as page:
            await page.press("j")
            await page.expect_state("idx", 1)
```

### Investigation findings

- The test passes locally — 20+ consecutive runs in isolation, and 5 consecutive runs of the file under
  `pytest -n auto --dist=loadfile --cov=src/sase --cov-branch` all pass.
- CI logs (runs `24999402183` on Py 3.12 and `24999512598` on Py 3.14) show total call time 3.06s and 2.56s
  respectively. With the harness's 2.0s `expect_state` timeout, that leaves **~0.5–1.0s for AcePage setup + the first
  keypress** before polling begins.
- It is the **first** test in `tests/test_keymaps_e2e.py`. Under `--dist=loadfile`, all tests in a file run on the same
  xdist worker; the first test absorbs cold-import cost (textual, `AceApp`, the keymap loader) plus coverage
  instrumentation overhead. The second test in the file (`test_remapped_navigation_key`) reuses warm imports and has not
  failed.
- The flake started exactly at `001ddc1f`. That commit is correctness-preserving but redistributes work during/after
  `on_mount`:
  - `_poll_agent_completions` is now async via `asyncio.to_thread`.
  - `KeybindingFooter._registry` is lazy (`None` → loaded on demand via `_kr()`).
  - `load_builtin_app_defaults` is wrapped in `@functools.cache`.
  - `_read_notifications_for_startup` returns a 4-tuple in one pass.
  - Process-local cache for `load_notifications`.

  None of these change the behavior of `j` → `action_next_changespec`; they shift the _timing_ of the first paint and
  the post-mount tick on a slow worker by enough to push past the harness's 2.0s polling window.

### What this is and isn't

- **It is**: a too-tight test-harness timeout exposed by cold-worker CI under coverage. The 2.0s default in
  `AcePage.expect_state` was set when typical setup was ~0.2s; with cold imports + coverage on CI, headroom evaporates.
- **It is not**: a regression in production startup or in `action_next_changespec`. The perf commit's intent was to
  _reduce_ startup cost (and it does for warm runs); we should not chase a cold-start "fix" here.

## Goals & Non-goals

**Goals**

- Make `tests/test_keymaps_e2e.py::test_default_keys_still_work` deterministic on CI without weakening signal.
- Give the rest of the `expect_state` callers the same headroom, so the next harness-timeout flake is one we actually
  want to investigate (not just "CI was slow today").

**Non-goals**

- Do not modify production startup code (`startup.py`, `lifecycle.py`, `keybinding_footer.py`, `_notifications.py`,
  etc.).
- Do not add a "wait until app is ready" handshake to AcePage. The polling exits as soon as state matches, so a generous
  timeout is functionally equivalent to a readiness signal but smaller in scope.
- Do not retry the test (no `flaky` plugin, no `pytest-rerunfailures`).

## Decision: raise the default `expect_state` timeout

Three options were considered:

| Option                                                                                         | Pros                                                                                                                                                    | Cons                                                                                                                   |
| ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| (a) Raise the default `timeout` in `AcePage.expect_state` (and the other two `expect_*` polls) | Single edit fixes this flake and any other `expect_state` caller running cold-first; polling is exit-fast on success so green-path runtime is unchanged | Slower failure mode for genuinely-broken tests (a stuck idx will report failure after the new timeout instead of 2.0s) |
| (b) Pass `timeout=` only at the failing test's call site                                       | Minimal blast radius                                                                                                                                    | Doesn't help the next caller that hits the same cold-worker condition; we'd be playing whack-a-mole                    |
| (c) Both: raise default _and_ override at this site                                            | Belt-and-braces                                                                                                                                         | Mostly redundant given (a)                                                                                             |

**Choosing (a).** The case for it:

- `expect_state` already polls in a tight loop yielding via `pilot.pause()`; on the green path it returns microseconds
  after state matches. Raising the timeout costs nothing when the test passes.
- All three `expect_*` helpers (`expect_state`, `expect_screen_contains`, `expect_screen_not_contains`) and `wait_for`
  use the same 2.0s default. A single bump keeps them consistent.
- Failure reporting time grows from 2s → 5s (proposed). For tests that _should_ pass, this is invisible. For tests that
  genuinely break, an extra 3s is a small cost vs. the recurring "rerun CI" tax of flakes.
- Other current callers (`tests/test_ace_tui_app.py`, `tests/test_ace_testing.py`, `tests/test_keymaps_e2e.py`) all
  benefit from the same headroom.

Proposed new default: **`timeout: float = 5.0`**. Rationale: CI failure was at 3.06s total call time, meaning ~1s
setup + 2s polling. Doubling the polling budget to ~4s gives ~2× headroom over the observed worst case; rounding to 5s
leaves comfortable margin for slower runners (Windows, ARM, future Python versions) without making genuine failures
painful to wait for.

`tests/test_ace_testing.py::test_expect_state_fails_on_timeout` deliberately calls `expect_state(..., timeout=0.1)`, so
the default change does not affect that test's intentional fast-fail.

## Plan

### Phase 1 — Bump the default `expect_state` timeout

1. Edit `src/sase/ace/testing.py`:
   - `expect_state`: `timeout: float = 2.0` → `timeout: float = 5.0` (line ~211).
   - `expect_modal`: same (line ~233).
   - `expect_no_modal`: same (line ~237).
   - `expect_screen_contains`: same (line ~241).
   - `expect_screen_not_contains`: same (line ~256).
   - `wait_for`: same (line ~277).

   Six identical literal changes in one file. No call-site changes required.

2. No changes to `tests/test_keymaps_e2e.py` itself — it inherits the new default.

3. No changes to production code.

### Phase 2 — Validate

1. `just check` (lint + mypy + tests) on the workspace.
2. Targeted soak test:
   ```bash
   for i in $(seq 1 50); do
     .venv/bin/python -m pytest -n auto --dist=loadfile \
       --cov=src/sase --cov-branch tests/test_keymaps_e2e.py 2>&1 \
       | tail -1
   done
   ```
   Expect 50/50 passes.
3. Confirm `tests/test_ace_testing.py::test_expect_state_fails_on_timeout` still passes (it uses an explicit
   `timeout=0.1` and is unaffected).

### Phase 3 — Commit & push

Single commit, `fix(ace)` scope, message along the lines of:

> fix(ace): raise AcePage poll-timeout default to 5s
>
> Stabilizes `test_keymaps_e2e.py::test_default_keys_still_work`, which was flaking on CI with
> `expect_state('idx', 1) timed out after 2.0s — last value was 0`. Total CI call time was 2.56–3.06s, leaving the
> harness only the 2s polling window after cold-worker setup. Polling exits as soon as state matches, so the green-path
> cost is unchanged.

## Change set summary

- **Files touched**: 1 (`src/sase/ace/testing.py`).
- **Diff size**: ~6 lines (timeout literal in default arguments).
- **Production code touched**: none.
- **Test code touched**: none.
- **Risk**: minimal — only effect is that genuinely-broken tests fail 3s slower; no behavior change on success.

## Open questions

- Should we also add a `SASE_TEST_TIMEOUT_MULT` env var to let CI multiply timeouts globally? Out of scope for this fix;
  mention in commit body if useful for future, but don't implement here.
