# TUI startup-adjacent freeze from external editor wait - 2026-06-26

## Scope

Investigate the report that the ACE TUI became unresponsive for about a
minute shortly after startup on Friday, June 26, 2026, and end with a
recommended solution.

I reviewed the required TUI performance memory via:

```bash
sase memory read tui_perf.md --reason "Investigating a startup TUI freeze and need required performance/responsiveness guidance"
```

I then checked the current watchdog logs, TUI source, runtime version, and prior
June TUI performance research.

## Short answer

The best match for the reported minute-long freeze is not the historical
startup artifact-index problem. The matching stall on June 26, 2026 at
10:18:02 EDT was a synchronous external editor wait from the Agents tab:

```text
Textual key handling
  -> AgentPanelDetailMixin.action_edit_spec
  -> AgentPanelDetailMixin._open_agent_chat
  -> AgentPanelDetailMixin._open_agent_chat_paths
  -> subprocess.run([editor, *chat_paths], check=False)
  -> os.waitpid(...)
```

The watchdog recovered after 73.020s, which matches "about a minute."

The same TUI process produced a second startup-adjacent stall at 10:28:43 EDT,
recovered after 15.005s. That one was the terminal artifact viewer waiting in a
blocking `os.read()` loop, not startup data loading.

## Evidence

Runtime inventory from `sase version`:

| Package | Version | Code directory |
| --- | --- | --- |
| `sase` | `0.5.0+167.g2479fbd4b` | `/home/bryan/projects/github/sase-org/sase/src/sase` |
| `sase-core-rs` | `0.2.0+7.g2edfc8541` | `/home/bryan/projects/github/sase-org/sase-core` |

This research workspace is `5af9b3810`, while the user-level runtime is
`2479fbd4b`. The relevant external-editor lines are identical between them.

The exact recovery records in `~/.sase/logs/tui.log`:

```text
2026-06-26 10:18:02 WARNING ... TUI event loop stall detected: 5.001s pid=739822
2026-06-26 10:19:10 WARNING ... TUI event loop recovered after 73.020s
2026-06-26 10:28:43 WARNING ... TUI event loop stall detected: 5.001s pid=739822
2026-06-26 10:28:53 WARNING ... TUI event loop recovered after 15.005s
```

The watchdog JSONL context for PID 739822:

| Time UTC | Local EDT | PID | Tab | Row | Activity | Last action | Class |
| --- | --- | ---: | --- | ---: | --- | --- | --- |
| 2026-06-26T14:18:02Z | 10:18:02 | 739822 | agents | 2 | session_start | bob-cli | external editor wait |
| 2026-06-26T14:28:43Z | 10:28:43 | 739822 | agents | 8 | session_start | bob-cli | artifact viewer wait |

The June 25-26 stall class counts after the older artifact-index incident:

| Class | Count |
| --- | ---: |
| synchronous `subprocess.run` wait | 7 |
| artifact viewer blocking read | 1 |
| other | 1 |

No June 25-26 stall record contains
`sync_dismissed_agent_artifact_index`,
`terminalize_stale_active_agent_artifact_index_rows`, or `_on_auto_refresh`.
Those stacks ended on June 23 in the current log set.

## Source path

The `e` key is bound globally to `edit_spec` in
`src/sase/ace/tui/bindings.py`:

```text
Binding("e", "edit_spec", "Edit Spec", show=False)
```

On the Agents tab, `edit_spec` opens the selected completed agent's chat file:

```text
src/sase/ace/tui/actions/agents/_panel_detail.py
47: def action_edit_spec(self) -> None:
49:     if self.current_tab == "agents":
50:         self._open_agent_chat()
...
119: def _open_agent_chat_paths(self, chat_paths: list[str]) -> None:
121:     editor = os.environ.get("EDITOR") or "nvim"
122:     with self.suspend():
123:         subprocess.run([editor, *chat_paths], check=False)
```

That call runs on the Textual event-loop thread. `self.suspend()` gives the
terminal to the editor, but it does not keep the Textual loop processing input.
While the editor process is alive, the TUI appears unresponsive and the
watchdog records a stall.

The later 15s stall is the same intentional-suspension shape, but through the
artifact viewer:

```text
src/sase/ace/tui/actions/hints/_files.py
146: with self.suspend():
147:     result = view_artifact_files(specs)

src/sase/ace/tui/graphics/_viewer_loop.py
351: while (key := read()) not in available_keys:
352:     pass
...
623: return os.read(fd, 1).decode(errors="ignore")
```

## Ruled out

### Artifact-index startup maintenance

The older June 20-23 startup freeze was real and had a clear stack through
`sync_dismissed_agent_artifact_index()` and active-tier terminalization. The
prior consolidated note
`sdd/research/202606/tui_startup_agents_tab_freeze_consolidated_20260623.md`
identified that path.

Current source has already changed the Agents apply path:

```text
src/sase/ace/tui/actions/agents/_loading_apply.py
310: if save_dismissed_agents(self._dismissed_agents):
311:     self._schedule_artifact_index_maintenance(...)
```

The maintenance mixin now coalesces work and runs it in a worker thread:

```text
src/sase/ace/tui/actions/agents/_index_maintenance.py
95: await asyncio.to_thread(
96:     sync_dismissed_agent_artifact_index_report,
...
100:    run_active_tier_maintenance=run_terminalize,
)
```

That does not prove the artifact-index pipeline is perfect, but it rules it out
for the June 26 minute-long stall because the watchdog stack did not pass
through the index code.

### Detail-header live diff

The June 25 slowdown note identified synchronous live `git diff` from
`build_detail_header_summary()` as another hard-freeze class. The June 26
minute-long stall did not include that stack. It went directly through the
external editor wait.

### j/k navigation model cost

The freeze was not caused by selection mutation or row navigation. The watchdog
stack was inside a blocking process wait, not the navigation path. This matches
the TUI performance memory warning that event-loop stalls usually come from
synchronous work on the Textual loop.

## Interpretation

The wording "when I just started it up" is consistent with the watchdog context
showing `activity_state=session_start`, but the captured stack says startup
itself was not doing the blocking work. A key action or command during the
early session invoked the Agents tab edit-chat path, which launched `$EDITOR`
or `nvim` and waited for it to exit.

That behavior may be expected when the editor visibly takes over the terminal.
It becomes a user-visible freeze when the editor process is hidden, delayed,
launched in an unexpected context, or when the user expected `e` to do an
in-TUI action. The current watchdog also cannot distinguish "TUI suspended for
an external tool" from accidental event-loop blockage, so the logs classify it
as a generic stall.

## Recommended solution

Create an explicit "external terminal owner" path and route all suspend-bound
editor/viewer actions through it.

Minimum viable fix:

1. Add a small `ExternalToolGuard` or `suspend_external_tool(...)` helper that
   wraps `with self.suspend(): subprocess.run(...)` and the artifact viewer
   loop.
2. While the guard is active, pause or annotate the stall watchdog so it records
   `external_tool_wait` with tool name, action, args count, and elapsed time,
   instead of a generic event-loop stall.
3. Show a clear pre-suspend status/notification such as "Opening editor for
   agent chat..." and restore focus/refresh state after return.
4. Add tests for the Agents `edit_spec` path and artifact viewer path proving
   these waits are classified as external-tool suspension, not accidental TUI
   freezes.

Follow-up hardening:

- For GUI-capable editors, support a nonblocking launch mode when the editor
  command is known not to need terminal ownership.
- Add a short confirm or different binding for `e` on Agents if accidental
  early-session editor launches keep happening.
- Keep the older artifact-index and detail-header fixes in place, but do not
  treat them as the root cause of the June 26 minute-scale startup-adjacent
  freeze.
