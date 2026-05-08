---
create_time: 2026-05-08
status: research
---

# Textual Serve Access For `sase ace`

## Question

How should SASE integrate `textual serve "sase ace"` so a user can easily access the Ace Textual UI from a browser when
they want it?

## Executive Summary

Add this as an **optional local web access mode for the existing Ace TUI**, not as the primary SASE web architecture.

Recommended product shape:

- Add a first-class SASE command, preferably `sase ace web`, that wraps Textual's serve mode for Ace.
- Bind to loopback by default, choose an available port by default, print the URL, and optionally open the browser.
- Treat LAN/public exposure as an explicit advanced mode with warnings and stronger access controls.
- Use Textual's browser-aware APIs (`App.open_url`, `App.deliver_text`, `App.deliver_binary`) for actions that currently
  assume the user is sitting at the host terminal.
- Keep the previous local-first Rust/REST web-client direction intact. `textual serve` is a fast path to remote Ace
  parity; it is not a substitute for web-native artifact viewing, mobile APIs, or shared backend contracts.

This is a high-leverage near-term feature because it reuses the existing Ace UI, keymaps, query logic, scheduler panels,
agent panels, and action model. It should be implemented as a small integration layer around Textual's server rather
than by asking users to remember `textual serve "sase ace"` and install the right extras themselves.

## Current SASE State

Relevant local facts:

- `pyproject.toml` depends on `textual[syntax]>=0.45.0`, but does not currently declare `textual-serve`.
- The CLI entry point is `sase = "sase.main.entry:main"`.
- `sase ace` is registered in `src/sase/main/parser_ace.py` and handled by `src/sase/main/ace_handler.py`.
- `handle_ace_command()` creates `AceApp(...)` and calls `app.run()`.
- `AceApp` lives in `src/sase/ace/tui/app.py`; its constructor already accepts the main user-facing launch knobs:
  query, model-tier override, refresh interval, axe autostart, and axe restart.
- Ace currently contains many host-terminal assumptions: external editor launches, terminal/tmux opens, clipboard helper
  commands, inline terminal image paths, and file-path notifications. Those are fine in the terminal, but need browser
  equivalents or graceful fallback in serve mode.

The CLI integration is therefore straightforward. The hard parts are not rendering Ace in the browser; Textual already
does that. The hard parts are lifecycle, security, packaging, and auditing host-terminal affordances.

## External Findings

### `textual serve` Is The Official Browser Path

Textual's README says any Textual app may be served with `textual serve`, for example:

```bash
textual serve "python -m textual"
```

The devtools docs describe `textual serve` as similar to `textual run`: it can serve a Python file or a command, and
`textual serve --help` exposes switches for host, port, title, public URL, debug/devtools, and command mode.

Local help for the installed `textual` command in this workspace showed:

```text
textual serve [OPTIONS] FILE or FILE:APP [EXTRA_ARGS]...
  -h, --host TEXT
  -p, --port INTEGER
  -t, --title TEXT
  -u, --url TEXT
  --dev
  -c, --command
```

Sources:

- Textual README, "Textual Web": https://github.com/Textualize/textual
- Textual devtools guide, Serve section: https://textual.textualize.io/guide/devtools/

### `textual-serve` Is A Subprocess/WebSocket Bridge

The `textual-serve` README says `Server(command)` accepts any shell command that launches a Textual app. On browser
visit, the server launches one app instance in a subprocess and communicates with it through a websocket.

The current `textual-serve` source confirms the important details:

- `Server` is an `aiohttp` app with routes for `/`, `/ws`, `/download/{key}`, and static assets.
- Each websocket connection creates an `AppService`.
- `AppService` launches the command with `asyncio.create_subprocess_shell()`.
- The child environment sets `TEXTUAL_DRIVER=textual.drivers.web_driver:WebDriver`, `TEXTUAL_FPS=60`,
  `TEXTUAL_COLOR_SYSTEM=truecolor`, `TERM_PROGRAM=textual`, `COLUMNS`, and `ROWS`.
- The browser sends stdin/resize/focus/blur messages over the websocket.
- The app sends rendered output and metadata back over stdout using Textual's web-driver protocol.

This means `sase ace web` can either shell out to `textual serve -c "sase ace ..."` or call
`textual_serve.server.Server(...)` directly. Direct API use is nicer for lifecycle and URL printing; shelling out is
less code but weaker for validation and future embedding.

Sources:

- `textual-serve` README: https://github.com/Textualize/textual-serve
- `textual-serve` `Server` source: https://github.com/Textualize/textual-serve/blob/main/src/textual_serve/server.py
- `textual-serve` `AppService` source:
  https://github.com/Textualize/textual-serve/blob/main/src/textual_serve/app_service.py

### Textual Has Browser-Aware Escape Hatches

Textual added APIs that matter for SASE's browser mode:

- `App.open_url(url, new_tab=True)` opens a URL in the user's browser. When served, `textual-serve` forwards that intent
  to the browser instead of trying to open a browser on the host.
- `App.deliver_binary(...)` and `App.deliver_text(...)` deliver files to the end user. In a terminal, delivery writes to
  a local downloads directory; in a browser, it uses a single-use download URL.

These APIs are the right way to adapt Ace actions that currently assume "open host editor", "write file and show path",
or "open this link from the terminal".

Sources:

- Textual blog, "Towards Textual Web Applications":
  https://textual.textualize.io/blog/2024/09/08/towards-textual-web-applications/
- Textual `App.open_url` / `App.deliver_binary` API docs: https://textual.textualize.io/api/app/

### Packaging Is Small But Not Free

`textual-serve` 1.1.3 is MIT licensed, requires Python >=3.9, and depends on `aiohttp`, `aiohttp-jinja2`, `jinja2`,
`rich`, and `textual>=0.66.0`.

SASE already depends on Textual and Jinja2, so the new dependency weight is mostly `aiohttp` plus `aiohttp-jinja2`.
Since browser serving is optional, there are two reasonable packaging choices:

- Put `textual-serve` in the main dependency set so `sase ace web` always works.
- Add an optional extra, for example `sase[web]`, and make `sase ace web` print a precise install hint when missing.

Given the feature is user-facing and low dependency risk, main dependencies are acceptable. If public release size or
dependency minimalism matters more, make it an extra but keep the command stub installed.

Sources:

- `textual-serve` PyPI: https://pypi.org/project/textual-serve/
- `textual-serve` `pyproject.toml`:
  https://github.com/Textualize/textual-serve/blob/main/pyproject.toml

## Security Model

`textual-serve` does not expose a raw shell, but it does expose the running Ace application. That distinction matters:
Ace can launch agents, edit project state, kill processes, open artifacts, and invoke configured workflows. Anyone who
can use the served Ace UI can perform the actions Ace permits.

Default mode should therefore be local-only:

- Bind to `127.0.0.1`, not `0.0.0.0`.
- Prefer an ephemeral free port or a SASE-owned default with collision handling.
- Print a clear URL and keep the foreground process lifetime obvious.
- Do not advertise public sharing as the primary path.

LAN/public mode should be explicit:

- Require `--host 0.0.0.0` or `--public`.
- Print a warning that the browser session can operate SASE on the host machine.
- Prefer a random access token in the URL before documenting LAN sharing. `textual-serve` itself does not appear to
  provide authentication in the routes shown by its source, so SASE should not imply that binding beyond loopback is
  access-controlled.
- If a reverse proxy is supported, document that TLS and authentication belong at the proxy layer unless SASE adds its
  own wrapper middleware.

For a first implementation, avoid Textual Web's public URL product for SASE. It may be useful later, but SASE's UI is a
privileged local control plane. The safe first boundary is "same user, same machine, browser instead of terminal".

## Integration Options

### Option A: Document The Raw Command

Document:

```bash
textual serve "sase ace"
```

Pros:

- Zero SASE code.
- Useful immediately for power users.

Cons:

- Requires users to know whether `textual-serve` / devtools are installed.
- No SASE-owned defaults for host, port, browser opening, title, query forwarding, or warnings.
- No place to add a token, singleton behavior, or serve-mode smoke tests.
- Does not help future users discover the feature from `sase --help`.

This is fine as documentation, not as the product integration.

### Option B: Add `sase ace --web`

Make `sase ace --web [query]` serve Ace instead of running it directly in the terminal.

Pros:

- Discoverable where users already launch Ace.
- Reuses the existing Ace parser options.

Cons:

- Harder parser ergonomics: `sase ace "query" --web --port 8000` mixes app options with serving options.
- The handler must avoid recursively serving `sase ace --web`.
- `--web` is a mode switch on an already large command.

This is acceptable, but it makes the command surface slightly muddy.

### Option C: Add `sase ace web`

Add a nested subcommand:

```bash
sase ace web [query] [--host 127.0.0.1] [--port 0] [--open] [--no-open] [--dev] [--url URL]
```

Internally it serves:

```bash
sase ace [query] [--model-tier ...] [--refresh-interval ...] [--no-axe] [--restart-axe] [--vcs-provider ...]
```

Pros:

- Cleanly separates "run Ace" from "serve Ace".
- Gives serving its own help text and safety defaults.
- Leaves room for `sase ace web status` / `stop` later if SASE adds singleton background servers.
- Keeps `sase ace` terminal behavior untouched.

Cons:

- Requires changing `ace` from a pure positional parser to a command with a possible nested subcommand.
- Existing query strings like `sase ace web` could be ambiguous. That is probably acceptable, but it should be called
  out in release notes; users can still quote or use a `--query` option if one is added.

This is the best Ace-specific shape.

### Option D: Add `sase web ace`

Add a top-level web command:

```bash
sase web ace [query]
```

Pros:

- Aligns with the longer-term `sase web` local server/client direction from
  `sdd/research/202604/sase_web_client_research.md`.
- Leaves `sase ace` parser mostly unchanged.
- Can later host multiple browser experiences under one web namespace.

Cons:

- Users who just discovered `textual serve "sase ace"` may look under `ace`, not `web`.
- "Web client" and "served TUI" are different architectures, so a shared namespace could blur the distinction.

This is a strong alternative if SASE wants all browser entry points under one command. If chosen, name the subcommand
clearly, for example `sase web ace-tui`, to avoid confusing it with the future web-native client.

## Recommended Design

Prefer `sase ace web` unless there is a strong CLI taxonomy preference for `sase web ace-tui`.

Recommended first CLI:

```bash
sase ace web [query]
  -h, --host HOST              default: 127.0.0.1
  -p, --port PORT              default: 0 or first available SASE port
  -o, --open                  open browser after server starts
  -O, --no-open               do not open browser
  -t, --title TITLE            default: "SASE Ace"
  -u, --url URL                public URL when behind a proxy
  -d, --dev                   enable Textual devtools
  -m, --model-tier {large,small}
  -r, --refresh-interval SEC
  -R, --restart-axe
  -x, --no-axe
  -v, --vcs-provider {git,hg,auto}
```

Implementation approach:

1. Add `textual-serve` as either a main dependency or `web` extra.
2. Refactor the Ace parser so the existing terminal form remains supported and `web` becomes a nested subcommand.
3. Build the served command with `shlex.join()` from the current Python executable or `sase` executable plus Ace args.
4. Use `textual_serve.server.Server(command, host=..., port=..., title=..., public_url=...)` directly if available.
5. If the import is missing, print a precise install hint and exit non-zero.
6. Open the URL with Python `webbrowser` only after the server has bound successfully. If direct `Server.serve()` does
   not expose a post-bind callback, either keep first implementation print-only or wrap `aiohttp` later.

Serving command detail:

- Avoid using `asyncio.create_subprocess_shell()` with manually concatenated user input. `textual-serve` ultimately
  accepts a shell command string, so SASE should construct that string from a list with `shlex.join()` and never splice
  raw query text into it.
- Consider setting an environment marker such as `SASE_ACE_WEB=1` for served Ace sessions. That makes it easy to gate
  browser-specific behavior inside the TUI without relying only on `TERM_PROGRAM=textual` or `TEXTUAL_DRIVER`.

## Serve-Mode Behavior Audit

The first version can work without perfect browser-native handling everywhere, but these areas should be audited before
calling the feature polished:

| Area | Current shape | Browser-mode recommendation |
| --- | --- | --- |
| Open URLs | Host-side commands or terminal assumptions may exist in action code. | Prefer `self.open_url(url)` inside Ace actions. |
| File/artifact delivery | Many actions show or open local paths. | Add `deliver_text` / `deliver_binary` paths for browser mode. |
| External editor actions | Several actions invoke `$EDITOR` or editor commands. | In browser mode, show read-only text or deliver a temp file first; later add an edit modal. |
| Clipboard | SASE has shell clipboard helpers; Textual has `copy_to_clipboard`. | Prefer Textual API where possible; notify if unsupported. |
| Terminal/tmux open | Some actions launch `tm`, terminal commands, or shell tools. | Disable with clear notification or replace with link/download/log panel behavior. |
| Inline images | Terminal graphics protocols are irrelevant under xterm.js. | Use browser download/open flows for binary artifacts; do not rely on Kitty/iTerm protocols. |
| Multiple browser tabs | Each websocket connection launches a fresh Ace subprocess. | Document this, and avoid assuming singleton in the first cut. |
| Axe autostart | Each Ace process can auto-start/observe axe. | Keep existing behavior, but test two browser sessions and `--no-axe`. |

## Relationship To The Web-Native SASE Client

This feature should coexist with the web-native client plan rather than replace it.

`textual serve` is best for:

- Fast access to the real Ace UI from a browser.
- Same-machine or SSH-tunneled workflows.
- Testing browser access to existing TUI interactions.
- Preserving keyboard-first behavior and minimizing new UI work.

A web-native SASE client is still better for:

- Rich artifact/PDF/image rendering.
- Mobile-friendly flows.
- Structured API contracts shared with Android or editor integrations.
- Fine-grained HTTP authentication and future local daemon reuse.
- Multi-surface command schemas independent of Textual widgets.

The integration should therefore be named and documented as "Ace web TUI" or "served Ace", not "the SASE web client".

## Suggested Phases

### Phase 1: Thin Productized Wrapper

- Add dependency handling for `textual-serve`.
- Add `sase ace web`.
- Default to loopback.
- Forward the main Ace options.
- Print the URL and foreground lifecycle.
- Add unit tests for argument parsing and served-command construction.
- Add a manual smoke test recipe:

```bash
sase ace web --port 8000 --no-open
```

### Phase 2: Safety And Ergonomics

- Add `--open` / `--no-open` behavior.
- Add explicit warnings for non-loopback host values.
- Consider URL token middleware if SASE wraps the `aiohttp` app instead of only calling `Server.serve()`.
- Add serve-mode environment marker.
- Add docs under normal Ace usage.

### Phase 3: Browser-Mode Polish

- Audit host-terminal actions and replace the highest-friction ones with browser-aware Textual APIs.
- Prioritize artifact viewing, plan/log export, URL opens, and editor fallback.
- Add Playwright smoke coverage if practical: start `sase ace web`, connect, assert the top-level Ace UI renders, resize
  the browser, and close cleanly.

### Phase 4: Decide Whether To Share Infrastructure With `sase web`

- If the Rust/REST local web client lands, decide whether `sase web ace-tui` should be an alias for `sase ace web`.
- Keep served-Ace lifecycle independent unless a singleton local server needs to proxy both the native SPA and the
  served TUI.

## Risks

- **False sense of security**: `textual-serve` is safer than exposing a shell, but Ace is still a privileged control
  surface. Non-loopback serving needs strong warnings or authentication.
- **Ambiguous CLI parsing**: `sase ace web` consumes a word that could previously be a query. This is manageable, but
  needs tests and release-note mention.
- **Subprocess multiplication**: every browser connection can create a separate Ace process. This may be desirable, but
  it affects axe startup, refresh polling, and user expectations.
- **Host action mismatch**: editor, clipboard, terminal, and artifact actions may behave oddly from a browser until
  audited.
- **Dependency drift**: SASE currently has a very old lower bound for Textual. Since `textual-serve` requires
  `textual>=0.66.0`, the SASE Textual lower bound should be raised if `textual-serve` becomes a main dependency.

## Open Questions

- Should the command be `sase ace web` or `sase web ace-tui`?
- Should `--open` be default on local desktop machines, or should the first implementation print only?
- Is an optional `sase[web]` extra worth the support burden, or should `textual-serve` be a normal dependency?
- Do we need access-token middleware before supporting `--host 0.0.0.0`, or is an explicit warning enough for the first
  release?
- Which Ace actions should be browser-polished before announcing the feature broadly?

## Recommendation

Ship `sase ace web` in a narrow first phase:

1. Main dependency on `textual-serve` unless package-size concerns block it.
2. Loopback-only default with a clear foreground server URL.
3. No public/LAN convenience until token or proxy guidance exists.
4. Environment marker for served sessions.
5. Tests for parser behavior and command construction.

This gives users the workflow they just discovered, but makes it discoverable, safer, and easier to evolve.

## Sources

- Textual README: https://github.com/Textualize/textual
- Textual devtools guide: https://textual.textualize.io/guide/devtools/
- Textual `App` API docs: https://textual.textualize.io/api/app/
- Textual blog, "Towards Textual Web Applications":
  https://textual.textualize.io/blog/2024/09/08/towards-textual-web-applications/
- `textual-serve` GitHub: https://github.com/Textualize/textual-serve
- `textual-serve` PyPI: https://pypi.org/project/textual-serve/
- Prior SASE web-client research: `sdd/research/202604/sase_web_client_research.md`
- Prior SASE Textual image-rendering research: `sdd/research/202605/textual_image_rendering_research.md`
