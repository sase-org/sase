# `py-spy` for Debugging `sase ace` TUI Performance

## Scope of this document

`py-spy` is already mentioned in prior research as one option among many:

- `sdd/research/202604/tui_profiling_strategies.md` §2 — generic tool
  comparison (py-spy vs pyinstrument vs Scalene vs viztracer).
- `sdd/research/202605/ace_progressive_slowdown_debugging.md` §2 Option B
  (time-sliced recording) and §9 (live-attach diagnostics).

This file is the **focused, sase-specific** companion: why `py-spy` solves
problems the current tooling (`sase ace --profile` and `SASE_TUI_PERF=1`)
cannot, and exactly how to drive it against the bottlenecks that the May 15
responsiveness captures and the progressive-slowdown debugging notes already
identified.

It is **not** a generic py-spy tutorial. Read py-spy's README for that. The
value here is the mapping from "this is what hurts in `sase ace`" to "this is
the py-spy invocation that proves or disproves it."

## TL;DR

Reach for `py-spy` when one of these is true:

1. **The TUI feels frozen right now** and you want a stack trace of every
   thread without killing the process. → `py-spy dump --pid <pid>`.
2. **The TUI is fast at minute 1 and crawling at minute 10**, and you want to
   compare flame graphs of the first 30s vs. the last 30s. →
   `py-spy record --format speedscope`, then scrub time ranges in
   speedscope.app.
3. **You want to profile a real interactive session** (Slack pasted into the
   prompt bar, scrolling 40 agents, opening modals) without modifying
   `ace_handler.py`, restarting, or accepting `pyinstrument`'s aggregation. →
   `py-spy record` attached to a running pid.
4. **You suspect non-Python time** (subprocess waits, native extensions,
   blocking syscalls). py-spy samples the kernel stack via `--native`,
   pyinstrument does not.

Reach for the existing `--profile` flag (pyinstrument) when you want a single
aggregate report over a known run, or async-aware bucketing that py-spy
doesn't give you. The two tools complement each other; they are not
interchangeable.

## What `py-spy` actually is

A sampling profiler written in Rust. It reads the target process's memory
out-of-process via `ptrace`/`process_vm_readv` and reconstructs Python frames
from the interpreter state. Consequences for sase:

- **Zero code changes.** Nothing to import, no env var to set inside `AceApp`,
  no harness wiring. This is the only profiler in the toolbox that can be
  applied to an already-running TUI session the user did not start with the
  intent of profiling.
- **Low overhead, ~1–2 %.** Safe to attach during real work; the user does not
  have to "set up a profiling session."
- **Sampling, not tracing.** It cannot see sub-millisecond functions that
  happen rarely. For "what fires per keystroke?" use pyinstrument; for
  "where does steady-state time go?" use py-spy.
- **No asyncio task labels.** py-spy sees OS thread stacks, not coroutine
  identities. The May 15 captures use `pyinstrument(async_mode="enabled")`
  precisely so they can label coroutine frames; py-spy will not give you that.

## Why this matters specifically for `sase ace`

The existing instrumentation has known shape:

- `sase ace --profile` (`src/sase/main/ace_handler.py:62`) wraps the *entire*
  session in one `pyinstrument.Profiler`. Aggregation hides drift — the
  central frustration identified in
  `sdd/research/202605/ace_progressive_slowdown_debugging.md`.
- `SASE_TUI_PERF=1` (`src/sase/ace/tui/util/perf.py`) records only key-to-
  paint latency for `j`/`k` navigation. It tells you that *something* is
  slow; it does not tell you what.
- Both require the user to *opt in before launch*. If you only learn the
  session is slow at minute 8, you cannot retroactively turn either on.

`py-spy` covers exactly the gap those leave:

| Question                                  | Best tool                    |
|-------------------------------------------|------------------------------|
| "What's slow on average?"                 | `sase ace --profile`         |
| "What's slow when I press `j`?"           | `SASE_TUI_PERF=1`            |
| "What's slow *right now* in this live session I forgot to instrument?" | `py-spy record --pid`        |
| "Is it slower at minute 10 than minute 1?" | `py-spy record --format speedscope` (scrub time ranges) |
| "It's hanging — what's it doing this instant?" | `py-spy dump --pid`          |
| "Is the time inside Python or in C/syscalls?" | `py-spy record --native`     |

## Prerequisites on Linux

`py-spy` uses `ptrace` to read the target. On most Linux distros the kernel
restricts ptrace to the same uid *and* requires `CAP_SYS_PTRACE` for
unprivileged attach. Two practical paths:

```bash
# Option A: run py-spy as root (simplest for one-off debugging)
sudo py-spy record -o /tmp/ace.svg --pid $(pgrep -f "sase ace")

# Option B: give the py-spy binary the ptrace capability once, then attach as user
sudo setcap cap_sys_ptrace=eip $(which py-spy)
py-spy record -o /tmp/ace.svg --pid $(pgrep -f "sase ace")
```

If you cannot get ptrace, add `--nonblocking`. It samples without pausing
the target so the read can be torn (occasional missing frames) but it works
without elevated capability. For a TUI being debugged interactively, the
trade-off is fine.

Install (this repo already uses uv-style management; py-spy is a binary, not
a Python lib):

```bash
pipx install py-spy           # preferred, isolates the binary
# or
cargo install py-spy          # if you have a Rust toolchain
# or
uv tool install py-spy
```

## Finding the right PID

`sase ace` shells out frequently, and there is often more than one Python
process under `sase`. Match strictly:

```bash
# Most reliable: the actual TUI app
pgrep -af "python.*sase.*ace"

# If multiple workspaces are open
pgrep -af "sase_[0-9]+.*ace"

# Cross-check: pick the one with TTY attached and highest RSS
ps -o pid,rss,tty,args -C python --sort=-rss | head
```

Pick the PID whose argv matches the TUI you're actually using. Attaching to a
spawned helper subprocess (e.g., a worker launched by `AgentList`) wastes the
session.

## Recipe 1: "It feels frozen right now"

This is the single most valuable py-spy invocation for sase work and the one
the current toolbox cannot reproduce. The TUI is unresponsive; you want to
know what call is blocking the event loop *without restarting*:

```bash
py-spy dump --pid $(pgrep -f "python.*sase.*ace")
```

Output is the current Python stack of every thread. Expected suspects, based
on the May 15 captures
(`sdd/research/202605/ace_profile_20260515_131509_responsiveness.md`):

- `_ring_tmux_bell` → `subprocess.run` → `_communicate` → `poll`. Synchronous
  tmux call on the UI thread.
- `_save_prompt_history` → file write on submit.
- `compute_diff_cache_key` → `get_vcs_provider` → workspace scan.
- `find_all_changespecs` via `_refresh_axe_display`.
- `_apply_loaded_agents_prepared` → `_finalize_agent_list`.

If the dump catches a stack rooted at one of those frames, you've reproduced
the finding without needing a pyinstrument capture, and you have *this
specific* instance, not an aggregate.

The dump is one shot. Run it 3–5 times in a row if the freeze persists, to
confirm the call is sticky rather than transient.

## Recipe 2: Confirm the May 15 findings on a fresh session

The May 15 captures are old enough that a few fixes have landed. Quickly
re-confirm where time actually goes today:

```bash
# Attach to a running sase ace and record for 5 minutes of normal use
py-spy record \
  --pid $(pgrep -f "python.*sase.*ace") \
  --duration 300 \
  --format speedscope \
  --output /tmp/ace.speedscope
```

Open `/tmp/ace.speedscope` at https://speedscope.app/. Three views to consult:

- **Left Heavy** — equivalent to pyinstrument's aggregated tree. Confirm the
  big buckets: `_render_chops`, `AgentList.render_lines`,
  `AgentInfoPanel.render_lines`, `Compositor.reflow`. If those have shrunk
  relative to the May 15 capture, the in-flight fixes are working.
- **Time Order** — flame graph painted along the wall-clock axis. The
  workhorse view for "is the second half worse than the first half?"
- **Sandwich** — caller/callee breakdown for a single function. Use to ask
  "who is still calling `Syntax._get_syntax`?" after the `_CachedSyntaxRenderable`
  fix.

Run with `--rate 250` (samples/sec) for higher resolution; default is 100.

## Recipe 3: Time-sliced flame for progressive slowdown

This is the workflow `ace_progressive_slowdown_debugging.md` §2 Option B
sketched. Concretely:

```bash
# Launch sase ace normally in terminal 1
sase ace

# In terminal 2, immediately attach with a long duration
py-spy record \
  --pid $(pgrep -f "python.*sase.*ace") \
  --duration 1200 \
  --format speedscope \
  --rate 200 \
  --output /tmp/ace-20min.speedscope
```

Use the TUI for the full 20 minutes — launch 5–10 agents, scroll, interact.
After the recording ends, open in speedscope and switch to **Time Order**.
Zoom the first 60 s on the left and the last 60 s on the right (two browser
tabs, side-by-side). The frames that are visibly wider in the right tab are
your degraders.

This is the cheapest way to answer the question the §1 heartbeat telemetry
also targets, *without* writing any code.

## Recipe 4: Native stacks for subprocess / syscall stalls

`_ring_tmux_bell` and the VCS resolution path are dominated by waits in C
land (subprocess `poll`, `git` invocations). pyinstrument shows the Python
frame that initiated the call but not the kernel wait. To see kernel-side
time:

```bash
sudo py-spy record \
  --native \
  --pid $(pgrep -f "python.*sase.*ace") \
  --duration 120 \
  --output /tmp/ace-native.svg
```

`--native` requires root. The resulting SVG shows native C frames inline with
Python frames; you can see `read`, `poll`, `wait4` etc. attributed to the
Python caller. Useful for distinguishing "the Python code is slow" from "we
are blocked on `git status` for 800 ms."

## Recipe 5: `py-spy top` for live exploration

When you don't yet have a hypothesis and want a quick "where is time going
*right now*":

```bash
py-spy top --pid $(pgrep -f "python.*sase.*ace")
```

htop-style live ranking of hot functions, updated every second. Lower
fidelity than a recording but immediate. Useful before deciding whether a
full record is worth doing.

## Mapping py-spy findings back to current sase hot spots

When you see one of these in a py-spy flame, the prior research has already
characterised it; jump to the cited section rather than re-investigating:

| py-spy frame                                | Already characterised in                                                                                       |
|---------------------------------------------|----------------------------------------------------------------------------------------------------------------|
| `_ring_tmux_bell` → `subprocess.*`          | `ace_profile_20260515_131509_responsiveness.md` finding #1                                                     |
| `AgentList.render_lines`                    | same, finding #2 (Textual per-strip render, not `format_agent_option`)                                         |
| `AgentInfoPanel.render_lines` (per second)  | same, finding #5 (countdown defeats the exact-state cache)                                                     |
| `Compositor.reflow` → `Syntax._get_syntax`  | same, finding #3 (`_CachedSyntaxRenderable` scoping problem)                                                   |
| `_save_prompt_history` on submit            | same, finding #6 (`_finish_agent_launch` → `_unmount_prompt_bar` → `_save_bar_text_as_cancelled`)              |
| `find_all_changespecs` from `_refresh_axe_display` | same, finding #7                                                                                          |
| `_refresh_xprompt_arg_hint_from_cursor` on keystroke | same, finding #8                                                                                       |
| `compute_diff_cache_key` / `get_vcs_provider` | same, finding #9                                                                                              |
| Frames in `_apply_loaded_agents_prepared`   | same, finding #10                                                                                              |

If py-spy shows something *not* in that table, that's the new lead worth
documenting.

## Things py-spy will *not* answer

Be honest about the boundary. py-spy is not the right tool for:

- **"Why is memory growing?"** Use `tracemalloc` or `memray` — see
  `ace_progressive_slowdown_debugging.md` §3. py-spy profiles CPU samples,
  not allocations.
- **"How many asyncio tasks are alive?"** py-spy sees OS threads. Use the
  task census in §6 of the progressive-slowdown doc.
- **"Which coroutine is awaiting which?"** Use
  `pyinstrument(async_mode="enabled")` — the existing `--profile` flag.
- **"How many widgets does `app.query('*')` return?"** Use the heartbeat
  telemetry proposal in §1 of the progressive-slowdown doc.
- **Sub-millisecond per-keystroke costs.** Sampling at 100–250 Hz cannot
  resolve a 0.5 ms call that runs once per keypress. `SASE_TUI_PERF=1` and
  pyinstrument's trace mode are the right tools for that scale.

## When to use py-spy vs. extend `--profile`

The progressive-slowdown doc proposes a `--profile-interval` extension to
rotate pyinstrument captures. py-spy's `--format speedscope` with time-range
scrubbing covers most of the same use case **without modifying
`ace_handler.py`**. Suggested heuristic:

- **One-off debugging session, no commit needed**: py-spy. Faster and lower
  friction. The investigation produces a `/tmp/*.speedscope` file you keep,
  not source changes.
- **You want every developer who hits the slowdown to capture the same data
  without learning a new tool**: extend `--profile`. The trade-off is
  maintenance burden in `ace_handler.py` against py-spy's ad-hoc nature.

Both paths can coexist; they target different audiences.

## Workspace-specific gotchas

The sase workspace conventions
(`memory/short/workspaces.md`) interact with py-spy in two ways:

- Each `sase_<N>` workspace has its own virtualenv. `py-spy` does *not* live
  inside those venvs; it should be installed once via `pipx` / `cargo` so it
  is available regardless of which workspace launched the TUI.
- `pgrep -f "sase.*ace"` will return processes from any workspace. If you
  have multiple workspaces open, narrow with the working-directory check:
  `ls -l /proc/<pid>/cwd` to confirm which workspace owns the pid.

## Recommended first action

You almost certainly already have a slow `sase ace` open right now. The
cheapest single action with the highest information yield is:

```bash
pipx install py-spy  # once
sudo setcap cap_sys_ptrace=eip $(which py-spy)  # once

# Then, against a live slow session:
py-spy record \
  --pid $(pgrep -f "python.*sase.*ace") \
  --duration 60 \
  --format speedscope \
  --rate 200 \
  --output /tmp/ace.speedscope
```

Open `/tmp/ace.speedscope` in speedscope.app. Switch to **Left Heavy**. The
top 5 frames are your candidates. Cross-reference with the table above. If
they match May 15's findings, you're confirming known-but-unfixed issues; if
they don't, you've found new ones.

## Cross-references

- `sdd/research/202604/tui_profiling_strategies.md` — generic tool selection
  (this doc is the sase-specific drilldown of Approach 2 there).
- `sdd/research/202605/ace_progressive_slowdown_debugging.md` — time-axis
  framing; py-spy is one of several tools listed there (§2 Option B, §9).
- `sdd/research/202605/ace_profile_20260515_131509_responsiveness.md` —
  current hot-spot findings, used as the lookup table above.
- `sdd/research/202605/ace_profile_20260515_responsiveness.md` — the May 15
  baseline whose dominant costs the 13:15 capture follows up on.
- `src/sase/main/ace_handler.py:62` — the existing `--profile` (pyinstrument)
  flag; py-spy is the no-source-change alternative.
- `src/sase/ace/tui/util/perf.py` — `SASE_TUI_PERF=1` JK timer.
