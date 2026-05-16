# `py-spy` for Debugging `sase ace` TUI Performance

**Updated:** 2026-05-16. Command examples were checked against `py-spy 0.4.2`.

## Scope of this document

`py-spy` is already mentioned in prior research as one option among many:

- `sdd/research/202604/tui_profiling_strategies.md` §2 — generic tool
  comparison (py-spy vs pyinstrument vs Scalene vs viztracer).
- `sdd/research/202605/ace_progressive_slowdown_debugging.md` §2 Option B
  (time-sliced recording) and §9 (live-attach diagnostics).
- `sdd/research/202605/ace_live_introspection_tooling.md` — broader live
  attach workflow with `strace`, in-process diagnostics, and capture bundles.

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
   blocking syscalls). py-spy identifies the Python caller and can include
   native extension frames with `--native`; pair it with `strace` when the
   question is which syscall or child process is blocking.

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
- **Current command surface.** As of `py-spy 0.4.2`, `record` and `top`
  support `--idle` to include sleeping/I/O-waiting threads; `dump` does not
  expose `--idle` and should be run as plain `py-spy dump --pid <pid>`.
- **Privacy boundary.** `py-spy dump --locals` can print prompt text, paths,
  environment-derived values, and other session data. Do not use it in default
  capture recipes; reserve it for a targeted follow-up after deciding the extra
  visibility is worth the exposure.

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
| "Is time inside Python or a native extension?" | `py-spy record --native`     |
| "Which syscall or child command is blocking?" | `py-spy dump`, then `strace -p <pid>` |

## Prerequisites on Linux

`py-spy` reads the target's memory out of process. On Linux, attaching to an
already-running process by PID is commonly blocked by `kernel.yama.ptrace_scope`
unless you run as root, grant the binary `CAP_SYS_PTRACE`, or relax the sysctl.
Launching the process through py-spy (`py-spy record -- python ...`) is less
restricted, but that loses the main benefit for `sase ace`: attaching to the
live TUI after it has become slow.

Two practical paths for live attach:

```bash
# Option A: run py-spy as root (simplest for one-off debugging)
sudo py-spy record -o /tmp/ace.svg --pid "$PID"

# Option B: give the py-spy binary the ptrace capability once, then attach as user
sudo setcap cap_sys_ptrace+ep "$(which py-spy)"
py-spy record -o /tmp/ace.svg --pid "$PID"
```

`--nonblocking` is not a permissions workaround. It avoids pausing the target
while py-spy samples, but py-spy still needs permission to read the process.
Use `--nonblocking` only when the tiny sampling pause is itself a concern, and
expect occasional partial frames or sampling errors.

If `py-spy` runs inside Docker or a similarly restricted container, the
container usually needs `SYS_PTRACE`; root inside the container is not enough
when `process_vm_readv` is blocked by the runtime profile.

If `pipx`, `uv tool`, or `pip` replaces the `py-spy` binary during an upgrade,
re-run `setcap`; Linux file capabilities are attached to the binary file.

Install (this repo already uses uv-style management; py-spy is a binary, not
a Python lib):

```bash
pipx install py-spy           # preferred, isolates the binary
# or
cargo install py-spy          # if you have a Rust toolchain
# or
uv tool install py-spy
# or
pip install py-spy
```

## Finding the right PID

`sase ace` shells out frequently, and there is often more than one Python
process under `sase`. Match strictly:

```bash
# List candidates with full argv
pgrep -fa "python.*sase.*ace"

# If multiple workspaces are open
pgrep -fa "sase_[0-9]+.*ace"

# Pick one PID and cross-check its TTY, cwd, and RSS before attaching
PID="$(pgrep -nf "python.*sase.*ace")"
ps -o pid,ppid,stat,etime,rss,tty,args -p "$PID"
readlink "/proc/$PID/cwd"
```

Pick the PID whose argv matches the TUI you're actually using. Attaching to a
spawned helper subprocess (e.g., a worker launched by `AgentList`) wastes the
session. Avoid passing raw `$(pgrep -f ...)` into `py-spy` when more than one
line may match; `py-spy --pid` expects a single PID.

## Recipe 1: "It feels frozen right now"

This is the single most valuable py-spy invocation for sase work and the one
the current toolbox cannot reproduce. The TUI is unresponsive; you want to
know what call is blocking the event loop *without restarting*:

```bash
PID="$(pgrep -nf "python.*sase.*ace")"
py-spy dump --pid "$PID"
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
PID="$(pgrep -nf "python.*sase.*ace")"
py-spy record \
  --pid "$PID" \
  --duration 300 \
  --format speedscope \
  --idle \
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
Keep `--idle` in this recipe because a TUI slowdown often includes time spent
waiting in `poll`, `read`, `wait4`, or terminal I/O, and otherwise py-spy may
filter out exactly the stack you care about.

## Recipe 3: Time-sliced flame for progressive slowdown

This is the workflow `ace_progressive_slowdown_debugging.md` §2 Option B
sketched. Concretely:

```bash
# Launch sase ace normally in terminal 1
sase ace

# In terminal 2, immediately attach with a long duration
PID="$(pgrep -nf "python.*sase.*ace")"
py-spy record \
  --pid "$PID" \
  --duration 1200 \
  --format speedscope \
  --idle \
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

## Recipe 4: Separate native-extension time from syscall / subprocess stalls

`--native` is useful for C, C++, Cython, and Rust-extension frames inside the
Python process. In sase, that mostly means validating whether a hot Python
caller is spending time across the `sase_core_rs` boundary or another native
extension. It does **not** profile a child `git`, `tmux`, or shell process as
kernel time inside the parent.

```bash
PID="$(pgrep -nf "python.*sase.*ace")"
py-spy record \
  --native \
  --pid "$PID" \
  --duration 120 \
  --output /tmp/ace-native.svg
```

The resulting SVG can show native frames inline with Python frames when symbols
are available. If the normal dump shows `subprocess.run`, `_communicate`,
`poll`, or `wait4`, switch to `strace` to answer the syscall question:

```bash
strace -p "$PID" -f -tt -T \
  -e trace=read,write,openat,poll,ppoll,select,futex,recvfrom,wait4,clone \
  -s 0
```

Use this pairing to distinguish three cases:

- Python CPU: wide Python frames in py-spy, no long syscall in strace.
- Native extension CPU: Python caller plus native frames under `--native`.
- Blocking child process or syscall: py-spy shows the Python wait site; strace
  names the syscall duration or child wait.

## Recipe 5: `py-spy top` for live exploration

When you don't yet have a hypothesis and want a quick "where is time going
*right now*":

```bash
PID="$(pgrep -nf "python.*sase.*ace")"
py-spy top --idle --pid "$PID"
```

htop-style live ranking of hot functions, updated every second. Lower
fidelity than a recording but immediate. Useful before deciding whether a
full record is worth doing. Drop `--idle` when you want a CPU-only view, and
try `--gil` when the question is specifically "which Python thread is holding
the interpreter?" Be careful with `--gil` for native-extension work because it
can hide extension time that releases the GIL.

## Recipe 6: Leave a repeatable capture bundle

When an agent is helping debug a live slow session, the useful artifact is not
just one flame graph. Leave enough context that the next investigation can
compare process state, open descriptors, and a short profile:

```bash
PID="$(pgrep -nf "python.*sase.*ace")"
OUT="$HOME/.sase/perf/ace_live_$(date +%Y%m%d_%H%M%S)_$PID"
mkdir -p "$OUT"

ps -o pid,ppid,stat,etime,%cpu,%mem,rss,vsz,nlwp,wchan:32,tty,args \
  -p "$PID" > "$OUT/ps.txt"
cat "/proc/$PID/status" > "$OUT/proc_status.txt" 2>/dev/null || true
ls -l "/proc/$PID/fd" > "$OUT/fds.txt" 2>/dev/null || true
py-spy dump --pid "$PID" > "$OUT/py_spy_dump.txt"
py-spy record --idle --format speedscope --pid "$PID" --duration 30 \
  --rate 250 -o "$OUT/profile.speedscope"
```

Default this bundle to `~/.sase/perf/` rather than `/tmp` when the point is to
preserve the investigation. Keep `/tmp` for one-off local experiments.

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
- **Slow non-Python children.** `--subprocesses` follows Python child
  processes. It will not explain why `git`, `tmux`, or a shell helper is slow;
  use `strace -f` or direct command timing after py-spy points at the wait site.

## When to use py-spy vs. extend `--profile`

The progressive-slowdown doc proposes a `--profile-interval` extension to
rotate pyinstrument captures. py-spy's `--format speedscope` with time-range
scrubbing covers most of the same use case **without modifying
`ace_handler.py`**. Suggested heuristic:

- **One-off debugging session, no commit needed**: py-spy. Faster and lower
  friction. The investigation produces a `*.speedscope` file or
  `~/.sase/perf/ace_live_*` capture bundle, not source changes.
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
sudo setcap cap_sys_ptrace+ep "$(which py-spy)"  # once

# Then, against a live slow session:
PID="$(pgrep -nf "python.*sase.*ace")"
py-spy record \
  --pid "$PID" \
  --duration 60 \
  --format speedscope \
  --idle \
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
- Upstream py-spy README and CLI help — `record`, `top`, `dump`, native
  profiling, subprocess profiling, Linux/macOS/Docker permissions, and
  `--nonblocking`: <https://github.com/benfred/py-spy>.
- PyPI release metadata — latest checked version `0.4.2`, released
  2026-04-24: <https://pypi.org/project/py-spy/>.
