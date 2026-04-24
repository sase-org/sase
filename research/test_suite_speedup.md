# Speeding up `just test`

## Current state (measured 2026-04-23, 64-core host, Python 3.14)

| Configuration                                                                 | Wall time   | Notes                                              |
| ----------------------------------------------------------------------------- | ----------- | -------------------------------------------------- |
| Serial, no coverage (`pytest --no-cov`)                                       | **~261 s**  | 4462 tests, 4457 passed, 6 skipped                 |
| Parallel `-n auto`, no coverage                                               | **~49 s**   | ~5.4× speedup                                      |
| Parallel `-n auto`, **with** coverage (current `just test` addopts + `-n auto`) | **~74 s**   | Coverage adds ~25 s (~50 %)                        |
| Serial + coverage (what `just test` actually runs today)                      | **~390 s estimate** | 261 s × ~1.5 coverage tax; not measured end-to-end |
| `pytest --collect-only --no-cov`                                              | ~1.7 s      | Collection itself is cheap                         |
| `pytest --collect-only` (with coverage)                                       | ~26 s       | Coverage dominates even bare collection            |

Observations that shape the recommendation:

- `pyproject.toml` `addopts` includes `--cov=src/sase --cov-branch --cov-report=html --cov-report=xml --cov-report=term-missing --cov-fail-under=50 -v`. Every `just test` invocation pays the full coverage bill — even when running a single test file during iteration.
- `pytest-xdist` is **already a dev dependency**, but the `test` Justfile target does not pass `-n auto`, so day-to-day runs are serial.
- No tests are marked `@pytest.mark.slow` / `integration` / `e2e` (0 matches). There is no way to scope down the suite.
- Almost no session-scoped / module-scoped fixtures (0 hits for `scope="session|module|class"`). Fixtures are built per-test.
- 167 `subprocess.*` call sites across 20 files; some tests genuinely shell out to `git`, which is legitimately slow.
- Three tests in `tests/test_agent_launch_repeat.py` (`test_spawns_n_agents_with_repeat_envs`, `test_prompt_has_repeat_stripped_and_name_injected`, `test_name_collision_surfaces_as_error_notification`) take **40 s each** serially — together they are ~46 % of the serial no-cov runtime. They spawn background threads and `join(timeout=5)` each; something in the spawned code path is blocking on real retries/waits even though `_launch_background_agent` is mocked.
- The TUI tests in `tests/test_ace_tui_app.py`, `tests/test_ace_tui_widgets.py`, `tests/test_ace_testing.py`, and `tests/test_keymaps_e2e.py` contribute a long tail of 4–8 s tests using Textual `Pilot`.
- `-v` is in `addopts`, which prints 4462 test ids — not a perf issue but ~100 KB of output per run (wastes terminal + agent context).

---

## Avenues

### A. Turn on `pytest-xdist` by default — **~5× speedup, zero code changes**

The package is already installed. Append `-n auto --dist=loadfile` to `addopts`, or (safer for local iteration) add it to the Justfile `test` recipe.

- **Pros**: single biggest win; free; 64 cores available.
- **Cons**:
  - `xdist` doesn't preserve test order (fine — tests should be order-independent; `-v` with captured stderr is the current "order") .
  - A few tests rely on process-global state like `Path.expanduser` monkeypatch (`tests/conftest.py:38-ish`) — already per-test, so safe.
  - `--dist=loadfile` groups same-file tests onto one worker, minimizing per-worker module import duplication (important: each worker re-imports `textual`, `rich`, `sase.ace.*` ≈ 60 ms of cold imports × N workers).
  - Worker startup dominates on tiny selections — `-n auto` on a 22-test file made a 0.6 s run into 3.5 s. Mitigation: keep `-n 0` for single-file dev runs, use `-n auto` for full suite. The Justfile should expose both.

### B. Make coverage opt-in — **~35 % speedup on top of xdist**

Coverage on Python 3.14 uses `sys.monitoring` (PEP 669) by default in coverage 7.13 — I confirmed `COVERAGE_CORE=sysmon` does not measurably improve over the default. `--cov-branch` is the remaining overhead; combined with HTML+XML report generation, coverage adds ~25 s to a 49 s parallel run.

- Move `--cov=...` / `--cov-report=...` / `--cov-fail-under=50` out of `addopts` and into a dedicated recipe (`just test-cov` or `just test-ci`).
- Keep `just test` lean for the dev loop.
- CI and pre-push keep full coverage.
- Risk: easy to forget coverage locally and merge a PR that drops coverage below 50 %. Guard this in CI (already happens) — do not guard it by making every local run slow.

### C. Fix the 3 × 40 s tests in `tests/test_agent_launch_repeat.py` — **reclaim ~120 s serial / ~40 s parallel tail**

These are a bigger deal than they look. Under `-n auto` the three tests land on one worker and run serially; they form the **critical path** that every parallel run waits for. 40 s is bigger than the "fast" runs I measured because those runs' tail was also pinned by these same tests. If we fix them the parallel run likely drops from 49 s → ~15 s.

Root cause to investigate: `_launch_repeat_agents` starts daemon threads that call into `sase.agent.repeat_launcher`. Even though `_launch_background_agent` is mocked on the fake app, something inside the spawned thread (likely artifact discovery, workspace allocation, or a retry loop in `agent_loader`) still blocks. `_join_threads()` joins each thread with `timeout=5`; if `N` threads each hit real timeouts, 3 agents × multiple threads each × 5 s per join ≈ observed 40 s.

Fix direction: inject the mock at a lower boundary, or patch the retry/timeout inside the spawned code path, or replace threads with inline callbacks in tests.

### D. Split into `unit` / `integration` markers with a default fast lane — **qualitative win for dev loop**

Mark genuinely slow / subprocess-heavy tests (git integration, Textual Pilot app tests, anything that sleeps) `@pytest.mark.slow`. Default `just test` runs `-m "not slow"`; `just test-all` runs everything. Pair with a `filterwarnings` entry in `pyproject.toml` so the markers are declared under `markers = ["slow: …", "integration: …"]`.

- Pros: fast default feedback loop; eventually the slow suite only runs in CI.
- Cons: requires actually auditing and tagging 4462 tests. Could be done incrementally — tag the 20 slowest first (`--durations=20` already prints them) for an 80/20 win.

### E. Drop `-v` from `addopts`

`-v` prints one line per test × 4462 = ~100 KB of output per run. Not a CPU cost, but it's noise that makes the agent harness (and humans) slower. Keep `--durations=20` instead — that's the useful signal.

### F. Textual tests: use `--headless` app timeouts

`tests/test_ace_tui_app.py` etc. use `Pilot`. Textual has a `Pilot(wait_for_idle=True)` idiom; several tests appear to use fixed `sleep()` or short timeouts that add up. Review the top 10 slowest Pilot tests and see if they can use `pilot.pause()` instead of `asyncio.sleep`. Lower confidence on impact without per-test profiling, maybe 3–5 s total.

### G. Coverage-context reduction

If coverage stays mandatory locally, reduce its surface area:

- Drop `--cov-branch` for local (~15–25 % of the coverage cost).
- Drop `--cov-report=html` + `--cov-report=xml` for local (disk I/O + report-assembly). Keep for CI.
- Consider `--cov-report=` (empty) locally — only enforces `--cov-fail-under` without writing files.

### H. Things I looked at and ruled out

- **`sys.monitoring` / `COVERAGE_CORE=sysmon`**: already active on Python 3.14 / coverage 7.13. Re-measured; no delta.
- **Parallel coverage merging (`parallel=True`)**: already enabled in `[tool.coverage.run]`.
- **Session-scoped fixtures**: nothing obvious to hoist. `make_changespec` is a class-factory; no expensive fixtures to promote. Worth revisiting after profiling, not a headline win.
- **`tempfile.NamedTemporaryFile(delete=False)` in `_ChangeSpecFactory.create_with_file`**: leaves tmp files, but a separate cleanliness issue, not a perf one.
- **Replacing pytest with something else (nose2, ward, unittest)**: loses `xdist`, `cov`, and the 4462 existing tests' fixtures. Not worth it.

---

## Recommendation

Do **A + B + C** in that order. These are independent and compounding:

1. **Ship A immediately** (~5 min of work). Edit `Justfile`:

   ```
   test *args: _setup (_header "test")
       {{ venv_bin }}/pytest -n auto --dist=loadfile {{ args }}

   test-cov *args: _setup (_header "test-cov")
       {{ venv_bin }}/pytest -n auto --dist=loadfile --cov=src/sase --cov-branch \
           --cov-report=term-missing:skip-covered --cov-report=html --cov-report=xml \
           --cov-fail-under=50 {{ args }}
   ```

   And remove `--cov*` / `-v` from `[tool.pytest.ini_options].addopts` in `pyproject.toml`. Keep `--strict-markers --strict-config --import-mode=importlib`. Point `just check` and CI at `test-cov`.

   Expected: `just test` drops from ~6 minutes to **~50 seconds**.

2. **Then B is already done** by the split above — `just test` has no coverage, `just test-cov` keeps the full 50 % gate for CI and `just check`.

3. **Then C**: fix `tests/test_agent_launch_repeat.py`. Investigate why the mocked launch still blocks for ~13 s per agent in the spawned thread. Likely either (a) `agent_loader` retries reading artifacts with backoff, or (b) a workspace allocation path not stubbed by `is_home_mode=True`. Fix at whichever layer is leaking a real sleep/retry into tests. Expected: parallel run drops further to **~15 s**.

Skip D, E, F, G, H for now — they are smaller wins and carry more risk/effort. Revisit D (slow markers) once the suite feels fast but we want to tighten CI turnaround further.

**Net expected outcome**: `just test` goes from ~6 minutes to ~15 seconds — a ~24× speedup — with a Justfile edit, a `pyproject.toml` edit, and one test file rewrite.

---

## Outcome (appended 2026-04-23 after Phase 3, bead `sase-l.3`)

### What shipped

- Phase 1 (`sase-l.1`, commit `361257d7`): `-n auto --dist=loadfile` default.
- Phase 2 (`sase-l.2`, commit `a2bb0bc8`): coverage moved out of `addopts` into a dedicated `just test-cov`; `just check` / CI re-pointed at `test-cov`.
- Phase 3 (`sase-l.3`, this change): `sleep_between=1.0` in `spawn_repeat_batch` is now injected from `_launch_repeat` via the module-level `_REPEAT_SPAWN_SLEEP` constant, and the three repeat-agent tests zero it out via an autouse `monkeypatch` fixture. Production default unchanged.

### Measured timings (post-Phase-3, 64-core host, Python 3.14, no coverage)

| Command                                                   | Before Phase 3 | After Phase 3 |
| --------------------------------------------------------- | -------------- | ------------- |
| `just test tests/test_agent_launch_repeat.py -n 0`        | 3.50 s         | **0.52 s**    |
| `just test tests/test_agent_launch_repeat.py` (parallel)  | 8.37 s         | ~7 s          |
| `just test` (full suite, `-n auto --dist=loadfile`)       | 50.34 s        | **50.32 s**   |

`--durations=20` no longer lists any test from `test_agent_launch_repeat.py`. The three tests that used to accumulate 3 s of real `time.sleep` now complete effectively instantly.

### Why the full-suite wall time didn't drop to ~15 s

The research doc's "40 s per test" figure for `test_agent_launch_repeat.py` was stale by the time Phase 3 ran — on the current workspace it was already ~1–2 s per test from the single `sleep_between=1.0` accumulation, not a retry/backoff loop. So fixing it cleanly removes that file from the slow list but recovers only ~3 s of sequential time, not the ~35 s the research doc implied.

The remaining ~50 s floor is dominated by Textual `Pilot`-based tests in `tests/test_ace_tui_app.py`, `tests/test_ace_tui_widgets.py`, `tests/test_ace_testing.py`, and `tests/test_keymaps_e2e.py` — 4–8 s each in the top-20 `--durations` list. These are options D/F/G in the avenues section above and were explicitly deferred for Phase 3; getting past 50 s will require that follow-up work.

### Net

Across Phases 1–3 the dev loop went from ~6 min → ~50 s (~7× faster) with coverage still enforced on `just check` / CI. The further ~3× to reach the ~15 s headline number is a follow-up on Textual `Pilot` test tiering.
