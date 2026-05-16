# Live Introspection of a Running `sase ace` Process

**Date:** 2026-05-16
**Symptom in scope:** `j`/`k` (and other keymaps) feel laggy — keystrokes are
visibly queued for several seconds before navigation happens. The user wants an
agent to be able to **attach to a live, already-running `sase ace`** and tell
them *why it is slow right now*, without restarting it.

This document is the live-introspection companion to existing static and
snapshot-aggregate work:

- `sdd/research/202605/tui_blocking_audit.md` — code-level audit of sync I/O in
  the TUI.
- `sdd/research/202605/tui_main_thread_blocking_v2.md` — fresh re-grep of
  blocking patterns by hot-path tier.
- `sdd/research/202605/ace_profile_20260515_responsiveness.md` and
  `sdd/research/202605/ace_profile_20260515_131509_responsiveness.md` —
  pyinstrument captures of full sessions.
- `sdd/research/202605/ace_progressive_slowdown_debugging.md` — heartbeat /
  comparative-snapshot strategy for sessions that *start* fast and *become*
  slow.
- `sdd/research/202604/tui_profiling_strategies.md` — tool-selection background
  from before the responsiveness work landed.

Those documents answer *what is expensive on average* and *what grows over
time*. This document answers a different question: **what is the running
process doing in the second that just blocked you?**

---

## Why a New Document

Re-reading the prior research, every existing approach requires one of:

1. A re-run of `sase ace --profile` (restart loses the live state that
   reproduced the lag).
2. An always-on telemetry shim (`SASE_TUI_PERF=1`, `SASE_HEARTBEAT=1`) that
   has to have been enabled *before* the slowness happened.
3. A code change followed by a redeploy of the TUI (e.g. adding heartbeat
   emission, SIGUSR1 dump handlers, frame-time histograms).

None of those help when the user is staring at a stuck TUI right now and wants
an agent to walk over, look at the live process, and report. That capability is
the gap this document fills.

Critical constraint: `sase ace` is a Textual app on a TTY. Attaching cannot
disturb the terminal, should not pause the loop for visible time, and ideally
shouldn't require root or sudo. The default tools below meet that bar in
development practice; use `py-spy --nonblocking` when even a tiny sampling
pause is unacceptable.

---

## TL;DR Recommendation

For an agent to debug a live laggy `sase ace`:

1. **First reach: `py-spy dump --idle --pid <PID>`.** No code changes, no
   restart, and very low perturbation. `--idle` is important for hangs because
   py-spy otherwise hides threads it believes are sleeping; for a TUI freeze,
   the "idle" stack may be exactly the blocked `poll`, `read`, or `wait4` you
   need. If the main thread is parked deep inside `subprocess.run` /
   `socket.recv` / `Path.read_text` / a `Syntax._get_syntax` call, you have the
   answer in one shot.
2. **Second reach: `py-spy record --idle --format speedscope --pid <PID>
   --duration 30`.** Capture ~30 seconds of stack samples while the user
   reproduces the lag, open in <https://speedscope.app/>. The time-ordered
   speedscope views localise the freeze to a specific call tree without
   restarting the process. Add `--nonblocking` if even short ptrace pauses are
   unacceptable, knowing that samples may contain occasional partial frames.
3. **Third reach: `py-spy top --pid <PID>`.** Live `htop`-style view of which
   Python functions are burning CPU right now. Best when the lag is
   *intermittent* and you want to watch it happen.
4. **If the freeze is *blocking syscalls* (not CPU):** `strace -p <PID> -f -tt
   -T -e trace=read,write,openat,poll,futex,recvfrom -s 0` shows what the
   kernel is waiting on. Useful when py-spy shows the interpreter parked in C
   code without obvious context (typically a stuck `poll` on a slow pipe).
5. **For long-lived sessions where the user wants the agent to "just check
   periodically":** combine `py-spy dump` with a structured artifact written
   to `~/.sase/perf/` so the next agent session can see history.

The highest-leverage gap in the previous draft was not a missing profiler; it
was the lack of a **repeatable agent capture bundle**. A single py-spy command
answers many hangs, but an agent should always leave a timestamped directory
with the stack, process metadata, fd census, and, when needed, a short profile:

```bash
PID="$(pgrep -nf 'sase ace')"
OUT="$HOME/.sase/perf/ace_live_$(date +%Y%m%d_%H%M%S)_$PID"
mkdir -p "$OUT"

ps -o pid,ppid,stat,etime,%cpu,%mem,rss,vsz,nlwp,wchan:32,cmd -p "$PID" > "$OUT/ps.txt"
cat "/proc/$PID/status" > "$OUT/proc_status.txt" 2>/dev/null || true
ls -l "/proc/$PID/fd" > "$OUT/fds.txt" 2>/dev/null || true
py-spy dump --idle --pid "$PID" > "$OUT/py_spy_dump.txt"
py-spy record --idle --format speedscope --pid "$PID" --duration 30 \
  --rate 250 -o "$OUT/profile.speedscope"
```

Do not use `py-spy dump --locals` in the default agent workflow. It can expose
prompt text, paths, tokens, or other user data. Use it only after a targeted
privacy tradeoff.

The next two sections detail each tool, what it sees and doesn't see, and the
exact commands an agent should run. The section after that proposes a small
SASE-side addition (`sase ace debug attach` and an in-process diagnostics
endpoint) that would make the agent workflow turnkey, but is not blocking — the
external tools work today.

---

## What "the TUI is blocked" actually means

Three different conditions all show up to the user as "`j`/`k` doesn't
respond":

| Condition | Where time is spent | Right tool |
|---|---|---|
| Main thread parked in a blocking syscall (file read, subprocess.run, socket.recv, tmux Popen) | Kernel, with Python stack frozen in C extension | `py-spy dump --idle` (sees the Python frame holding the syscall) + `strace -p` (sees the syscall) |
| Main thread in CPU-bound Python (large `Syntax._get_syntax`, `Compositor._render_chops`, render fan-out) | Python interpreter | `py-spy top` / `py-spy record` |
| Asyncio event loop scheduled work piled up but the loop itself is fine | Coroutines awaiting on each other | `py-spy dump --idle` shows `asyncio.run_until_complete` idle; need in-process introspection (`asyncio.all_tasks()`, `loop._scheduled`) |
| Tons of small per-frame work, no single offender | Spread across many frames | `py-spy record` — the time-ordered view aggregates the spread |

The prior audits (`tui_blocking_audit.md`, `tui_main_thread_blocking_v2.md`)
catalogued *every code path that could cause* each condition. Live
introspection's job is to pick the one that *did* cause it this time.

---

## Tier 1: Tools That Work Today, No Code Changes

### 1.1 py-spy (primary recommendation)

`py-spy` is a sampling profiler that reads another process's memory via
`process_vm_readv` (Linux) or `task_for_pid` (macOS). It does not inject code
into the target and does not pause it perceptibly. On Linux without root, it
typically needs `CAP_SYS_PTRACE` — the install docs cover this; once granted,
no further setup is required.

Three commands cover every case relevant to TUI lag:

**Stack dump (instant snapshot, the "what is it doing right now" answer):**

```bash
py-spy dump --idle --pid "$(pgrep -nf 'sase ace')"
```

Output is one stack per thread, with Python frames interleaved with the
native frames only when native sampling is enabled and symbols are available.
For the first pass, read the Python stack. The main-thread top frame answers
the question the user is asking. Typical things to look for:

- `subprocess.Popen._communicate` → blocked on subprocess pipe; look up the
  call stack for the caller (e.g. `_ring_tmux_bell`, `compute_diff_cache_key`).
- `pathlib.Path.read_text` / `json.load` from a `compose()` or
  `__init__` of a modal → modal load on main thread (B2/B3/B4 family from
  `tui_main_thread_blocking_v2.md`).
- `Syntax._get_syntax` from a `Compositor` frame → Pygments lex during a
  layout pass (the still-open issue from §3 of
  `ace_profile_20260515_131509_responsiveness.md`).
- `epoll.poll` alone → loop is idle; the lag is not main-thread CPU and not a
  blocking syscall in Python. Look at `asyncio.all_tasks()` instead (see §2.1
  below).

The dump is text — perfect for piping to a markdown report, attaching to a
SASE artifact, or copy-pasting into a chat.

**Live top (best when the user can re-trigger the lag):**

```bash
py-spy top --pid "$(pgrep -nf 'sase ace')"
```

Refreshes every second. The user mashes `j` or opens a modal; whichever
function jumps to the top is the answer. Especially good for the "feels
slow during typing" case where a single dump is too small a sample.

**Record + speedscope (best for the "few-second freeze" case):**

```bash
PID="$(pgrep -nf 'sase ace')"
mkdir -p ~/.sase/perf
OUT="$HOME/.sase/perf/ace_live_$(date +%Y%m%d_%H%M%S).speedscope"
py-spy record --idle --format speedscope --pid "$PID" --duration 30 --rate 250 -o "$OUT"
echo "Open in https://speedscope.app/ — drag $OUT in"
```

`--rate 250` (250 samples/s) is enough resolution to see individual ~10ms
frames without being heavy. The user opens the file in speedscope's
left-heavy or time-order view and identifies what dominated those 30s.
`--duration 30` is a reasonable default; bump it for slower-developing
freezes.

**Notes / caveats:**

- On Linux distros that ship with `kernel.yama.ptrace_scope=1` (Ubuntu
  default), `py-spy` needs `sudo` or `setcap cap_sys_ptrace+ep
  "$(which py-spy)"`. Document this clearly so the user does it once.
- On macOS, codesigning is required; `py-spy` ships signed builds.
- `py-spy --native` can sample native extension frames on supported platforms,
  but the result depends on symbols and can be noisier. For `sase_core_rs`,
  expect the normal Python-mode dump to show the Python call site first; use
  `--native` or `perf` only after that call site points at the Rust boundary.
- `py-spy --subprocesses` is useful only for Python child processes. It will
  not explain a slow `tmux`, `git`, or shell command; use `strace` for those.
- Sampling is statistical — `py-spy top` rate-of-sampling defaults to 100
  Hz, so anything faster than ~10ms can be missed. For TUI freezes that
  matter (≥50 ms), this is fine.
- `--nonblocking` avoids even brief sampling pauses, but because py-spy reads
  interpreter memory while the process is moving, the tradeoff is less precise
  or partial frames. Use it for repeated `record`/`top` captures, not as a
  reflex for the first `dump`.

### 1.2 strace (when the freeze is in a syscall py-spy can't name)

When `py-spy dump` shows the main thread parked in something like
`<built-in method poll of select.epoll>` or
`<built-in method recv of _socket.socket>` and you want to know *what
descriptor* or *what command*, attach strace:

```bash
strace -p "$(pgrep -nf 'sase ace')" -f -tt -T -e trace=read,write,openat,poll,futex,recvfrom,wait4,clone -s 0
```

- `-f` follows forked subprocesses (catches the `tmux` invocations).
- `-tt` adds microsecond timestamps; `-T` adds syscall durations in `<...>`.
- `-e trace=...` keeps the firehose to the syscalls relevant to TUI blocking.
- `-s 0` suppresses string payloads (avoids dumping prompt text or file
  contents to logs).

If the freeze is a 3s `tmux display-message` invocation, strace will show a
`wait4` of that long duration; you can confirm without inspecting code. If the
freeze is a slow NFS open of a `*.log`, you see the `openat`+`read` pair with
a long `<duration>` and the path is in the strace output.

`strace -c -p <PID>` (counted summary) is useful for "the TUI has felt slow
for the last hour; what has the kernel been doing on its behalf?"

Caveats:

- `strace` slows the traced process. For a backgrounded `sase ace` it is fine
  to attach for 30 s; do not leave it attached for hours.
- Same `ptrace_scope` caveat as py-spy.

### 1.3 lsof / proc inspection (for the leaked-FDs / leaked-pipe hypothesis)

When the user reports the TUI has been getting slower for an hour (the
progressive-slowdown class from `ace_progressive_slowdown_debugging.md` §1),
the cheapest first check is:

```bash
PID="$(pgrep -nf 'sase ace')"
ls -la /proc/$PID/fd | wc -l
ls -la /proc/$PID/fd | awk '{print $11}' | sort | uniq -c | sort -nr | head -20
cat /proc/$PID/status | grep -E '^(Vm|Threads|FDSize)'
```

A steadily climbing fd count strongly suggests a leaked subprocess pipe (the
tmux bell, the VCS resolution) or a leaked file handle (prompt history,
agent_meta.json). Cross-reference against
`ace_progressive_slowdown_debugging.md`'s hypothesis #4.

On macOS use `lsof -p $PID | wc -l` and `vmmap $PID` for the equivalent.

### 1.4 gdb (last resort, when Python introspection isn't enough)

For pathological hangs — e.g. the GIL is held but the holding thread isn't
visible in py-spy — attach gdb with the CPython helper:

```bash
gdb -p "$(pgrep -nf 'sase ace')" \
  -ex 'set pagination off' \
  -ex 'py-bt' \
  -ex 'thread apply all py-bt' \
  -ex 'detach' -ex 'quit'
```

`py-bt` is provided by the cpython gdb helper (`python3-dbg` package on
Debian/Ubuntu). It prints Python tracebacks from C-level frames. Use this if
py-spy fails to attach or reports stale frames.

---

## Tier 2: Tools That Need a Tiny Code Addition (~½ day of work)

These move "what is the agent looking at?" from "external sampling of the
process" to "structured data the process is willing to surface." Add them when
the Tier 1 tools have been used enough times that you want a turnkey
experience.

### 2.1 Async-task / `call_later` census via in-process endpoint

`py-spy` cannot directly enumerate Python objects in the target process. The
single most useful piece of information it *can't* give is "what is the asyncio
event loop currently scheduling?" — and that is exactly the answer for the
"loop is idle but TUI doesn't respond to keys" case.

The cheapest way to surface it: a Unix-domain socket the TUI listens on,
gated on `SASE_DEBUG_SOCKET=1`, that emits one JSONL message per request.

```python
# src/sase/ace/tui/debug/endpoint.py (proposed)
import asyncio, gc, json, os, sys
from collections import Counter
from pathlib import Path

async def handle(reader, writer):
    cmd = (await reader.readline()).decode().strip()
    payload: dict = {"cmd": cmd}
    if cmd == "tasks":
        tasks = asyncio.all_tasks()
        payload["count"] = len(tasks)
        payload["by_name"] = dict(Counter(t.get_name() for t in tasks))
        payload["stacks"] = [_task_top_frame(t) for t in list(tasks)[:20]]
    elif cmd == "loop":
        loop = asyncio.get_running_loop()
        payload["debug"] = loop.get_debug()
        payload["slow_callback_duration"] = loop.slow_callback_duration
        payload["ready_count"] = len(getattr(loop, "_ready", ()))
        payload["scheduled_count"] = len(getattr(loop, "_scheduled", ()))
    elif cmd == "gc":
        payload["counts"] = list(gc.get_count())
        payload["objects"] = len(gc.get_objects())
        payload["types"] = dict(Counter(type(o).__name__ for o in gc.get_objects()).most_common(30))
    elif cmd == "dom":
        # injected at construction
        payload["widget_count"] = endpoint.app.query("*").__len__()
        payload["workers"] = _worker_census(endpoint.app)
        payload["timers"] = _timer_census(endpoint.app)
    elif cmd == "perf":
        payload["timer"] = endpoint.app._jk_perf.summary()
    writer.write((json.dumps(payload) + "\n").encode())
    await writer.drain()
    writer.close()

def install(app) -> None:
    if os.environ.get("SASE_DEBUG_SOCKET") != "1":
        return
    sock_path = Path.home() / ".sase" / "perf" / f"ace-debug-{os.getpid()}.sock"
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    endpoint.app = app
    app.run_worker(asyncio.start_unix_server(handle, str(sock_path)),
                   name="debug-endpoint", thread=False, exclusive=True)
```

Client side (the agent calls this):

```bash
PID="$(pgrep -nf 'sase ace')"
SOCK="$HOME/.sase/perf/ace-debug-$PID.sock"
printf 'tasks\n' | nc -U "$SOCK"
printf 'loop\n'  | nc -U "$SOCK"
printf 'gc\n'    | nc -U "$SOCK"
```

Why a socket and not SIGUSR1 (which `ace_progressive_slowdown_debugging.md`
proposed): a socket is queryable, returns structured data, and lets the
agent ask a series of questions without re-triggering the user's terminal
each time. SIGUSR1 is still a fine backup but is one-shot per signal.

Cost: ~120 lines of code plus an env-gate. Risk: a unix socket left exposed
needs `0600` permissions and a per-PID name (already in the snippet). Also add
a schema version to every payload; agents will otherwise become brittle as the
diagnostic shape evolves.

### 2.2 Asyncio slow-callback logging

The prior draft skipped the best built-in event-loop diagnostic. Python's
asyncio debug mode logs callbacks that exceed
`loop.slow_callback_duration`. That maps directly to "a keypress action or
Textual message handler blocked the loop long enough for `j`/`k` to queue."

Add a dev-only gate during ACE startup:

```python
def install_asyncio_debug(*, threshold_s: float = 0.05) -> None:
    if os.environ.get("SASE_ACE_ASYNCIO_DEBUG") != "1":
        return
    loop = asyncio.get_running_loop()
    loop.set_debug(True)
    loop.slow_callback_duration = threshold_s
    logging.getLogger("asyncio").setLevel(logging.DEBUG)
```

Run it from `AceApp.on_mount` or the startup mixin, and route logs to
`~/.sase/perf/ace_asyncio_debug_<pid>.log` rather than the TUI terminal. Start
with 50ms for navigation work; raise to 100ms if the log is noisy. This does
require launching with the env var before the slowdown, but the payoff is high:
it names the actual slow callback instead of forcing an agent to infer it from
samples.

### 2.3 In-process pyinstrument toggle

Add a debug action (default unbound; user can bind to a chord) that
starts/stops a `pyinstrument.Profiler` and writes the output to
`~/.sase/perf/ace_live_<ts>.txt`. The mechanic:

```python
def action_perf_capture_toggle(self):
    if self._live_profiler is None:
        self._live_profiler = pyinstrument.Profiler(async_mode="enabled")
        self._live_profiler.start()
        self.notify("Perf capture started")
    else:
        self._live_profiler.stop()
        path = Path.home() / ".sase" / "perf" / f"ace_live_{datetime.now():%Y%m%d_%H%M%S}.txt"
        path.write_text(self._live_profiler.output_text(unicode=True, color=False, show_all=True))
        self._live_profiler = None
        self.notify(f"Perf capture written: {path}")
```

This solves the "I felt the slowdown for the last 30 seconds; I'd like a
profile of exactly that" case. The current `sase ace --profile` captures the
entire session and dilutes the spike. Tier 1's `py-spy record` is the
external equivalent, but this is faster to invoke from inside the TUI and
already has `async_mode="enabled"` for free.

Cost: ~40 lines and one keymap. `pyinstrument` is already a runtime dependency
because `sase ace --profile` uses it today.

### 2.4 Frame-time histogram piggybacking on JKPerfTimer

`src/sase/ace/tui/util/perf.py:49` already records key-to-paint latency for
`j`/`k`. Extending it to record *every* frame (or every action handler) gives
a continuous timeline. Combined with the heartbeat from
`ace_progressive_slowdown_debugging.md` §1, this lets an attached agent ask
"when did the last p95 spike happen?" by reading
`~/.sase/perf/heartbeat.jsonl`.

The frame-time half is sketched in `ace_progressive_slowdown_debugging.md` §5
and §1. Calling it out here because a live-introspection agent benefits from
this *retroactive* signal: if the user says "it was slow about a minute ago,"
the agent reads heartbeat history rather than asking the user to reproduce.

### 2.5 SIGUSR1 dump as a low-tech fallback

If the socket endpoint feels too heavy, the simpler version is a signal
handler that writes a one-shot dump:

```python
import signal, faulthandler

_fault_file = open(Path.home() / ".sase" / "perf" / f"ace-faulthandler-{os.getpid()}.log", "a")
faulthandler.register(signal.SIGUSR1, file=_fault_file, all_threads=True, chain=False)

# Optional: use a normal Python signal handler for structured data, but do not
# rely on it when the main thread is blocked in C.
```

The agent triggers it with `kill -USR1 $(pgrep -nf 'sase ace')` and reads
the log. `faulthandler.register` is preferable to a normal
`signal.signal(..., python_callback)` handler for the traceback itself because
Python-level signal handlers run later on the main interpreter thread. If the
main thread is stuck inside a long C call, that "later" may be after the freeze
has ended. Use the debug socket for structured payloads (`asyncio.all_tasks()`,
GC counts, cache census); use `faulthandler` for the emergency traceback.

### 2.6 `faulthandler` watchdog for the "stuck for >N seconds" case

`faulthandler.dump_traceback_later(timeout=5, repeat=True, file=...)`
registers a wall-clock watchdog thread. By itself it does **not** mean "the
event loop has been blocked for five seconds"; it means "five seconds elapsed
since this watchdog was armed." To turn it into an event-loop stall detector,
re-arm it from the loop on every heartbeat:

```python
def _arm_loop_stall_watchdog() -> None:
    faulthandler.cancel_dump_traceback_later()
    faulthandler.dump_traceback_later(2.0, repeat=False, file=_fault_file)

self.set_interval(0.5, _arm_loop_stall_watchdog)
```

If the loop keeps turning, the timer is canceled and re-armed before it fires.
If the loop stops turning for >2s, the watchdog thread dumps the stack. Enable
behind `SASE_FAULTHANDLER=1` and write to
`~/.sase/perf/faulthandler_<pid>.log`. Keep the file object open for the
lifetime of the handler; `faulthandler` stores the file descriptor.

This is a strong complement to the on-demand tooling: an agent can later
attach, read the log, and report "the TUI was blocked at <timestamp>; here
is the traceback at that moment."

Cost: 5 lines plus a log-rotation policy.

---

## Tier 3: External Power Tools (Worth Knowing, Rarely Needed)

These cost more to set up and produce more data than is usually necessary
for the j/k lag. Reach for them when Tier 1 and Tier 2 don't converge on an
answer.

### 3.1 viztracer

`viztracer` produces a Chrome-trace timeline showing every function call.
Attach with:

```bash
viztracer --attach "$(pgrep -nf 'sase ace')" --output_file /tmp/ace.json --duration 10
vizviewer /tmp/ace.json
```

The timeline view makes per-frame work visible in a way pyinstrument cannot
(pyinstrument aggregates; viztracer preserves order). Overhead is 5–10× on
the traced process, so attach briefly. Current VizTracer attach mode also
requires `viztracer` to be importable in the target process's Python
environment, which makes it less safe as a default live-agent tool than
py-spy.

### 3.2 perf + Rust frames

For investigating `sase_core_rs` hotspots:

```bash
perf record -p "$(pgrep -nf 'sase ace')" -g --call-graph=dwarf sleep 30
perf report --no-children
```

Requires the kernel `perf_event_paranoid` to allow user perf events. Cross-
reference with the Rust core repo for symbol resolution.

### 3.3 austin / austin-tui

Austin is an alternative sampler with a built-in TUI viewer. Useful when
running headless and you don't want to round-trip through speedscope:

```bash
austin -p "$(pgrep -nf 'sase ace')" -o /tmp/ace.austin -i 1ms -d 30
austin-tui /tmp/ace.austin
```

Comparable to py-spy. Pick one and stick with it.

### 3.4 memray attach

For the "RSS keeps growing" case (memory leak surfaced by heartbeat):

```bash
PID="$(pgrep -nf 'sase ace')"
memray attach -o "/tmp/ace_memray_$PID.bin" --duration 30 "$PID"
memray flamegraph "/tmp/ace_memray_$PID.bin"
```

Heavier than tracemalloc but produces a flamegraph of allocation sites over
time. Useful when tracemalloc diff isn't enough. Caveat: unlike py-spy,
`memray attach` injects code into the target process and requires `memray` to
be installed in that process's environment. Treat it as a development-machine
tool, not the first thing an agent should run against a valuable live TUI.

### 3.5 Textual devtools

Textual's own devtools are not a live attach path for an already-running
`sase ace`; they require launching in development mode:

```bash
textual console
textual run --dev -c sase ace
```

That makes them a **reproduction** tool, not a rescue tool. They are still
worth adding to the workflow when the profiler points at Textual message
routing, worker churn, CSS reload/layout, or widget lifecycle behavior. Use
`textual console -v` only for short runs; verbose event logging can itself
change the feel of an interactive TUI.

---

## Proposed Agent Workflow

The end state — what we'd want an agent to be able to do when asked "the TUI is
slow, find out why":

1. **Detect the process.** `pgrep -nf 'sase ace'`; if multiple, ask the user
   to pick or use the foreground tty.
2. **One-shot snapshot.** `py-spy dump --idle --pid <PID>` and inspect the
   main-thread stack.
3. **Classify.**
   - If main thread is in a known sync I/O path → cross-reference
     `tui_main_thread_blocking_v2.md` for the corresponding finding (B1–B19);
     present the finding tag, file:line, and suggested fix to the user.
   - If main thread is in `Compositor` / `render_lines` / `Syntax._get_syntax`
     → reference `ace_profile_20260515_131509_responsiveness.md` §2/§3.
   - If main thread is idle (`epoll.poll`) → the lag is upstream of the loop;
     check the debug socket (if running) or fall back to strace for the actual
     syscall.
4. **Confirm with a short record.** If a single dump isn't decisive, run a
   30-second `py-spy record --idle --format speedscope` and produce a
   speedscope link or summary.
5. **Write the capture bundle** under `~/.sase/perf/ace_live_<ts>_<pid>/`
   with `ps.txt`, `proc_status.txt`, `fds.txt`, `py_spy_dump.txt`, and the
   optional speedscope profile so the next agent session can build on it.

The first three steps require no code changes. Steps 4–5 are pure agent
behavior. The optional Tier 2 additions (especially the debug socket §2.1,
asyncio slow-callback logging §2.2, and faulthandler watchdog §2.6) turn step 3
into a richer classification that includes asyncio task census and recent
freeze history.

---

## Decision Matrix

| Need | First reach | Setup cost | Code change? |
|---|---|---|---|
| "What is the TUI doing right now?" | `py-spy dump --idle` | None (cap once) | No |
| "Why is typing/`j`/`k` slow?" | `py-spy top` while the user mashes keys | None | No |
| "Capture a 30s freeze for review" | `py-spy record --idle --format speedscope` | None | No |
| "Is the lag a syscall I can't see?" | `strace -p` filtered | None | No |
| "Has the process leaked fds?" | `ls /proc/<PID>/fd` | None | No |
| "What are the asyncio tasks?" | Debug socket (§2.1) | ½ day | Yes |
| "Which callback blocked the loop?" | Asyncio slow-callback logging (§2.2) | 1 hour | Yes |
| "Get a profile of just this freeze" | In-process toggle (§2.3) | 2 hours | Yes |
| "When did the last freeze happen?" | Frame-time histogram + heartbeat (§2.4) | 1 day | Yes |
| "Auto-capture any freeze >2s" | `faulthandler` watchdog (§2.6) | 1 hour | Yes |
| "Where are the bytes accumulating?" | `memray attach` | None (install) | No |
| "What is Textual doing?" | `textual console` + dev-mode repro (§3.5) | Restart in dev mode | No SASE code |

---

## What Not To Do

- **Don't restart `sase ace` before capturing.** The whole point of this
  document is to avoid losing the live state. `py-spy` attaches in
  milliseconds; restart loses everything.
- **Don't pause the loop from inside the TUI.** Adding a "debug, sleep 1s,
  inspect" path is exactly the kind of UI-thread blocking we're trying to
  diagnose. All proposed in-process tooling (§2) runs on workers or signals.
- **Don't pipe `py-spy dump` into the TUI's terminal.** `py-spy` writes to
  stderr, which on the TUI's tty corrupts the Textual render. Always pipe to
  a file or run from a separate terminal.
- **Don't run `strace` on the prompt-input or modal-open paths and then
  blame what you see.** `strace` slows the traced process enough to make
  other phenomena look like the bug; use it for syscall confirmation, not
  primary attribution.
- **Don't conflate "py-spy shows X" with "X is the cause".** A sampling
  profiler shows what's on stack *at sample time*; for sub-100ms freezes,
  capture more samples (longer `--duration`) before drawing conclusions.
- **Don't leave `memray attach`, `viztracer --attach`, or verbose Textual
  devtools running by default.** They are useful second-line tools, but they
  import/inject or produce enough overhead to change the symptom.

---

## Open Questions

- Should the debug socket (§2.1) be on by default in dev installs and off in
  release? The minor security cost (per-PID socket in `~/.sase/perf/`) vs the
  major usability win argues "on by default for now."
- Where should the per-PID socket live? `~/.sase/perf/ace-debug-<pid>.sock`
  keeps it next to existing perf data; `$XDG_RUNTIME_DIR/sase/ace-<pid>.sock`
  is cleaner on systemd systems. Pick one before implementation.
- Should `sase ace debug` become a sibling subcommand that wraps `py-spy`
  invocation + speedscope upload + artifact write, so users don't need to
  remember the flags? Likely yes — listed as future work, not blocking.
- For `faulthandler` watchdog: what timeout? 1s catches every j/k stutter (too
  noisy); 5s catches the user-visible freezes; 10s loses small-but-perceptible
  hitches. Start at 2s with rotation.
- How does this interact with the Rust core (`sase_core_rs`) boundary
  (`memory/short/rust_core_backend_boundary.md`)? py-spy sees the Python
  caller of Rust code; `perf` (§3.2) sees inside Rust. If Rust becomes a
  hotspot, the Rust core repo needs its own profiling story, since attaching
  pyinstrument across the FFI boundary won't help.

---

## Cross-References

- `sdd/research/202605/tui_main_thread_blocking_v2.md` — static catalog of
  blocking sites; the file:line answers you point at after live introspection
  identifies the culprit.
- `sdd/research/202605/tui_blocking_audit.md` — earlier static audit; same
  role.
- `sdd/research/202605/ace_profile_20260515_131509_responsiveness.md` —
  aggregate pyinstrument analysis; cross-references for hot-path
  classification.
- `sdd/research/202605/ace_progressive_slowdown_debugging.md` — heartbeat
  telemetry / comparative-snapshot strategy; complement to live introspection
  for the slowness-over-time case.
- `sdd/research/202604/tui_profiling_strategies.md` — tool-selection
  background.
- `src/sase/ace/tui/util/perf.py` — existing perf primitive (JKPerfTimer) to
  extend with frame-time histogram (§2.4).
- `src/sase/main/ace_handler.py:62` — `--profile` flag wiring; natural home
  for a future `sase ace debug` subcommand or an `--attach-debug-socket`
  option.

## External Sources Checked

- py-spy README / CLI behavior: <https://github.com/benfred/py-spy>
- Python asyncio debug and `slow_callback_duration`:
  <https://docs.python.org/3/library/asyncio-dev.html>
- Python `faulthandler`: <https://docs.python.org/3/library/faulthandler.html>
- Python signal handler semantics: <https://docs.python.org/3/library/signal.html>
- Textual devtools: <https://textual.textualize.io/guide/devtools/>
- VizTracer remote attach:
  <https://viztracer.readthedocs.io/en/latest/remote_attach.html>
- Memray attach: <https://bloomberg.github.io/memray/attach.html>
- Pyinstrument 5.1 user/API docs:
  <https://pyinstrument.readthedocs.io/en/stable/guide.html>
