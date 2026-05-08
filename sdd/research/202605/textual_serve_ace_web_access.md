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

Relevant local facts (verified at the time of writing):

- `pyproject.toml` declares `textual[syntax]>=0.45.0`. Resolved version in this workspace is `textual==8.0.0`. There is
  no `textual-serve` dependency. (`pyproject.toml:24`)
- `textual-serve>=1.1.3` requires `textual>=0.66.0`, so adopting it requires raising SASE's Textual lower bound.
- The CLI entry point is `sase = "sase.main.entry:main"`. (`pyproject.toml:44`)
- `sase ace` is registered in `src/sase/main/parser_ace.py:8` and dispatched by
  `src/sase/main/ace_handler.py:12 (handle_ace_command)`.
- `handle_ace_command()` builds an `AceApp(...)` and calls `app.run()`. (`src/sase/main/ace_handler.py:49`)
- `AceApp` lives in `src/sase/ace/tui/app.py`; its constructor already accepts the main user-facing launch knobs:
  query, model-tier override, refresh interval, axe autostart, and axe restart. The same arg set therefore needs to be
  re-forwarded into the served subprocess command.
- Host-terminal assumptions in Ace are concrete and numerous, not hypothetical:
  - `os.environ.get("EDITOR") or "nvim"` is invoked from at least **13 distinct Ace action/modal sites** (e.g.
    `src/sase/ace/tui/actions/changespec/_core.py:96`,
    `src/sase/ace/tui/actions/agent_workflow/_editor.py:44`,
    `src/sase/ace/tui/modals/agent_run_log_modal.py:516`,
    `src/sase/ace/tui/modals/xprompt_browser_actions.py:48`).
  - The artifact viewer is tmux-pane-based: `view_artifact_files_in_tmux_pane()` and friends in
    `src/sase/ace/tui/graphics/viewer.py:171`, gated by `is_tmux_session()` at line 155, with `open_tmux` /
    `start_tmux_mode` keymap entries (`src/sase/ace/tui/keymaps/types.py:54`).
  - The `App.open_url`, `App.deliver_text`, and `App.deliver_binary` Textual APIs are **not used anywhere in `src/`
    today** (grep returns zero hits in `src/sase/ace/`). All browser-aware adaptations are net-new work.

The CLI integration itself is straightforward — Textual already renders Ace in a browser. The hard parts are
lifecycle, security, packaging, and auditing host-terminal affordances. The audit work is non-trivial because of the
13× `$EDITOR` callsite footprint and the tmux-only artifact viewer.

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

The `textual-serve` README says `Server(command)` accepts any shell command that launches a Textual app. On each
browser visit, the server launches **a new app instance per websocket connection** in a subprocess and communicates
with it through a websocket. There is **no session pooling**: every browser tab spawns its own Ace process.

The current `textual-serve` source confirms the important details:

- `Server` is an `aiohttp` app with routes for `/`, `/ws`, `/download/{key}`, and static assets.
- Each websocket connection creates an `AppService` which calls `start()`/`stop()` on its own subprocess.
- `AppService` launches the command with `asyncio.create_subprocess_shell()`.
- The child environment sets `TEXTUAL_DRIVER=textual.drivers.web_driver:WebDriver`, `TEXTUAL_FPS=60`,
  `TEXTUAL_COLOR_SYSTEM=truecolor`, `TERM_PROGRAM=textual`, `COLUMNS`, and `ROWS`.
- The browser sends stdin/resize/focus/blur messages over the websocket.
- The app sends rendered output and metadata back over stdout using Textual's web-driver protocol.

`Server.__init__` constructor signature (v1.1.3):

```python
Server(command, host="localhost", port=8000, title=None, public_url=None,
       statics_path="./static", templates_path="./templates")
```

Public methods are limited to `serve(debug=False)`, `request_exit()`, `initialize_logging()`, plus the three handlers.

Embedding limitations to know before designing `sase ace web`:

- **No port-zero discovery.** `serve()` calls `aiohttp.web.run_app(...)` directly; there is no `AppRunner`/`TCPSite`
  exposure to recover the bound port when `port=0`. SASE must either bind a port up front (with collision handling) or
  subclass and intercept the aiohttp lifecycle.
- **No middleware hook.** The `aiohttp.web.Application` is constructed inside `serve()` and not exposed; SASE cannot
  attach token-auth or `Origin`-check middleware without forking or subclassing.
- **No "ready" signal.** `serve()` is blocking; `run_app` does not yield a post-bind callback. To open the browser
  *after* bind, SASE either has to monkey-patch `Application.on_startup` before `serve()` runs or wrap aiohttp itself.

Practical consequence: shelling out to `textual serve -c "sase ace ..."` and calling `textual_serve.server.Server(...)`
directly are roughly equivalent in capability today. The direct path is still preferred for argv hygiene and
forward-compatibility, but it does **not** unlock middleware or ready-signaling without subclassing.

Sources:

- `textual-serve` README: https://github.com/Textualize/textual-serve
- `textual-serve` PyPI (v1.1.3, 2025-11-01): https://pypi.org/project/textual-serve/
- `textual-serve` `Server` source: https://github.com/Textualize/textual-serve/blob/main/src/textual_serve/server.py
- `textual-serve` `AppService` source:
  https://github.com/Textualize/textual-serve/blob/main/src/textual_serve/app_service.py

### `textual-serve` vs Textual Web (the hosted product)

These are two separate products and conflating them is a common mistake:

- **`textual-serve`** (the dependency this note is about) is a **local, self-hosted** aiohttp bridge. It has **no auth,
  no TLS, no token, no cookie, and no basic-auth** in v1.1.3. The only "security" claim in its README is the
  custom-protocol argument that the websocket transport is not a raw shell. SASE must not assume any built-in access
  control.
- **Textual Web** (`textual-web`, `pip install textual-web`) is the **hosted public-URL** product Textualize operates.
  It uses an account/API-key model: `textual-web --signup` issues an `api_key` stored in `ganglion.toml`; without an
  account, public URLs are random and rotate per run; with an account, URLs are namespaced under your account slug.
  This is the right product *only* if SASE wants Textualize-hosted public sharing — a different threat model from
  local-only loopback serving and out of scope for the first integration.

Source: https://github.com/Textualize/textual-web

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
can reach the served Ace UI can perform the actions Ace permits.

`textual-serve` v1.1.3 ships with **no authentication, no TLS, and no Origin/Host validation** in its aiohttp routes.
SASE cannot rely on the dependency for any access control.

Default mode should therefore be local-only:

- Bind to `127.0.0.1`, not `0.0.0.0`.
- Prefer an ephemeral free port (chosen by SASE before construction, since `Server` cannot report a `port=0` bind back)
  or a SASE-owned default with collision handling.
- Print a clear URL and keep the foreground process lifetime obvious.
- Do not advertise public sharing as the primary path.
- Add a `Host`-header allowlist (against DNS-rebinding) and an `Origin` check before any non-loopback exposure.
  Implementing either requires SASE to subclass `Server` and intercept the aiohttp app, since the upstream class does
  not expose middleware. The first release should simply refuse non-loopback binds rather than ship middleware that
  must immediately be revisited.

LAN/public mode should be explicit and gated:

- Require `--host 0.0.0.0` or `--public`.
- Print a warning that the browser session can operate SASE on the host machine.
- Document that **TLS termination must happen at a reverse proxy** (Caddy/nginx/Cloudflare Tunnel). `textual-serve`
  does not provide TLS and its README does not discuss it; the only proxy hook is the `public_url` constructor arg.
- Be aware of upstream issue **textual-serve#28**: static asset URLs are constructed from the bound `host:port` and
  break behind a reverse proxy unless `public_url` is set explicitly. Any LAN/public guidance must mention this.
- Be aware of **textual-serve#29**: the `/download/{key}` flow is reported flaky behind reverse proxies (nginx, frp).
  Artifact delivery in browser mode should be tested against whatever proxy SASE recommends.
- Prefer a random access token in the URL before documenting LAN sharing. SASE owns this; the dependency does not.

For a first implementation, avoid Textual's hosted product (`textual-web`) for SASE. It may be useful later, but SASE's
UI is a privileged local control plane and `textual-web`'s account-namespaced URLs are still public. The safe first
boundary is "same user, same machine, browser instead of terminal".

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

1. Add `textual-serve` as either a main dependency or `web` extra. Either way, **raise the Textual lower bound** in
   `pyproject.toml` from `textual[syntax]>=0.45.0` to at least `textual[syntax]>=0.66.0` (`textual-serve>=1.1.3`'s
   stated minimum); pinning to the resolved-today `>=8.0.0` is safer if no other consumer needs the older floor.
2. Refactor the Ace parser so the existing terminal form remains supported and `web` becomes a nested subcommand.
3. Build the served command with `shlex.join()` over `[sys.executable, "-m", "sase", "ace", ...args]` (or the resolved
   `sase` script path). Never splice raw query text into the shell string.
4. Use `textual_serve.server.Server(command, host=..., port=..., title=..., public_url=...)` directly. Pre-resolve the
   port (e.g. via `socket.socket().bind((host, 0))` then `getsockname()[1]` and close) since `Server` cannot report a
   `port=0` bind back.
5. If the import is missing, print a precise install hint and exit non-zero.
6. Open the URL with Python `webbrowser`. Because `Server.serve()` does not expose a post-bind callback, either:
   - **Print-only** in the first release (simplest, safest). User clicks the link.
   - Or schedule the `webbrowser.open(url)` call from `Application.on_startup` by subclassing `Server` and patching
     before `serve()` constructs `web.run_app(...)`. Defer this to phase 2 to keep the first implementation small.

Serving command detail:

- Avoid using `asyncio.create_subprocess_shell()` with manually concatenated user input. `textual-serve` ultimately
  accepts a shell command string, so SASE should construct that string from a list with `shlex.join()` and never splice
  raw query text into it.
- Consider setting an environment marker such as `SASE_ACE_WEB=1` for served Ace sessions. That makes it easy to gate
  browser-specific behavior inside the TUI without relying only on `TERM_PROGRAM=textual` or `TEXTUAL_DRIVER`.
- The child env will already contain `TEXTUAL_DRIVER=textual.drivers.web_driver:WebDriver`; Ace can detect web mode
  from that as a fallback if the SASE-specific marker is absent.

## Serve-Mode Behavior Audit

The first version can work without perfect browser-native handling everywhere, but these areas should be audited before
calling the feature polished:

| Area | Current shape | Browser-mode recommendation |
| --- | --- | --- |
| Open URLs | No `App.open_url` usage in `src/sase/ace/` today (grep is empty). | Adopt `self.open_url(url)` for any URL-opening action; it forwards over the websocket in served mode. |
| File/artifact delivery | Action code references local paths and the host filesystem. No `deliver_text`/`deliver_binary` usage today. | Add `deliver_text`/`deliver_binary` paths (browser gets a single-use download URL via `/download/{key}`). |
| External editor actions | `os.environ.get("EDITOR") or "nvim"` appears at **13+ Ace sites** (changespecs, agent workflow, hints, modals, agent run log, xprompt browser, task queue, notification attachments). | None of these can launch a host editor over the websocket. First cut: detect web mode and surface a "edit unavailable in web — download / view-only" path; phase 3 adds an in-browser modal editor. |
| Clipboard | SASE shell helpers (`pbcopy`/`xclip`/`wl-copy`) live in `src/sase/ace/tui/actions/clipboard/`. Textual's `copy_to_clipboard` works over the websocket since v0.81. | Prefer Textual's API where possible; explicit notify-and-fallback for actions that still shell out. |
| Terminal/tmux open | Artifact viewer is tmux-pane-based: `view_artifact_files_in_tmux_pane()` (`src/sase/ace/tui/graphics/viewer.py:171`), gated by `is_tmux_session()`. `open_tmux`/`start_tmux_mode` are real keymap entries. | Hard block in web mode (the host tmux is meaningless to a remote browser). Fall back to `deliver_text`/`deliver_binary` for the artifact, or a Textual-rendered viewer modal. |
| Inline images | Terminal graphics protocols (Kitty/iTerm/Sixel) are irrelevant under xterm.js. Note upstream textual-serve#34 (Sixel) and #31 (Nerd Font) are open. | Use browser download/open flows for binary artifacts; do not rely on host graphics protocols. |
| Paste | Pasting from outside the browser into Textual inputs is partially broken (textual-serve#32, paste behavior was only added in v1.1.2, 2025-04-16). | Document the limitation; avoid assuming paste-driven workflows in browser mode. |
| Multiple browser tabs | Each websocket connection launches a fresh Ace subprocess (no pooling, confirmed via `app_service.py`). | Document this prominently. Two tabs = two independent Ace processes touching the same `~/.sase/...` state. |
| Axe autostart | Each Ace process can auto-start/observe axe. | With multi-tab subprocess fan-out, test that two browser sessions do not race on axe startup. Default web mode to `--no-axe` for the first release if a cheap singleton lock is not available. |
| Assets behind proxy | textual-serve#28: static asset URLs hard-code the bound `host:port`. | If SASE ever recommends a reverse proxy, require setting `public_url` on `Server(...)`. |

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
  surface. The dependency itself ships zero auth in v1.1.3; non-loopback serving requires SASE-owned token middleware
  (which requires subclassing `Server`) or a reverse proxy with auth. Do not promise either without shipping it.
- **Ambiguous CLI parsing**: `sase ace web` consumes a word that could previously be a query. This is manageable, but
  needs tests and release-note mention. Power users with the literal query `web` will need to quote or use `--query`.
- **Subprocess multiplication**: every browser connection creates a separate Ace process (no pooling — confirmed in
  `textual_serve/app_service.py`). This affects axe startup, refresh polling, file-lock contention on `~/.sase/...`,
  and user expectations.
- **Host action mismatch**: editor (13× `$EDITOR`/`nvim` callsites), clipboard, tmux artifact viewer, and inline
  graphics will all behave oddly or break from a browser until audited.
- **Dependency drift**: SASE currently has `textual[syntax]>=0.45.0`. `textual-serve>=1.1.3` requires
  `textual>=0.66.0`, so the lower bound must be raised when `textual-serve` is added — coordinate with anything else
  that depends on the older floor.
- **Embedding gaps**: `textual_serve.server.Server` does not expose port-zero discovery, middleware, or a ready-signal
  callback. Any feature that needs those (auth tokens, Origin checks, post-bind browser open) requires subclassing
  `Server` or wrapping aiohttp ourselves. First release should avoid features that need any of these.
- **Reverse-proxy footguns**: open upstream issues textual-serve#28 (static asset host:port hardcoding) and #29
  (download-manager flakiness) directly affect any "put nginx in front" recipe. Mention both wherever SASE documents
  proxy fronting.

## Open Questions

- Should the command be `sase ace web` or `sase web ace-tui`?
- Should `--open` be default on local desktop machines, or should the first implementation print only? (See `Server.serve()`
  ready-signal limitation above — print-only is the conservative default.)
- Is an optional `sase[web]` extra worth the support burden, or should `textual-serve` be a normal dependency?
- Do we need access-token middleware before supporting `--host 0.0.0.0`, or is an explicit refusal-with-warning enough
  for the first release? Adding a token requires subclassing `Server` to attach aiohttp middleware; the dependency does
  not expose it.
- Which Ace actions should be browser-polished before announcing the feature broadly? (Top candidates by callsite count
  and friction: `$EDITOR` flows, the tmux-pane artifact viewer, clipboard helpers.)
- Should web mode default to `--no-axe` for the first release, given each browser tab spawns its own Ace subprocess and
  there is no built-in singleton lock?
- If we ship a reverse-proxy recipe, do we set `public_url` automatically and document the textual-serve#28/#29 caveats,
  or wait until upstream lands fixes?

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
- Textual devtools guide (verified, includes "Serve" section):
  https://textual.textualize.io/guide/devtools/
- Textual `App` API docs (`open_url`, `deliver_text`, `deliver_binary`): https://textual.textualize.io/api/app/
- Textual blog, "Towards Textual Web Applications" (Darren Burns, 2024-09-08):
  https://textual.textualize.io/blog/2024/09/08/towards-textual-web-applications/
- `textual-serve` GitHub (v1.1.3, 2025-11-01): https://github.com/Textualize/textual-serve
- `textual-serve` PyPI: https://pypi.org/project/textual-serve/
- `textual-serve` `server.py`: https://github.com/Textualize/textual-serve/blob/main/src/textual_serve/server.py
- `textual-serve` `app_service.py`:
  https://github.com/Textualize/textual-serve/blob/main/src/textual_serve/app_service.py
- `textual-serve` open issues referenced (#28 host:port in static URLs, #29 reverse-proxy download flakiness, #32 paste,
  #34 Sixel, #31 Nerd Font): https://github.com/Textualize/textual-serve/issues
- `textual-web` (the distinct hosted product): https://github.com/Textualize/textual-web
- Prior SASE web-client research: `sdd/research/202604/sase_web_client_research.md`
- Prior SASE Textual image-rendering research: `sdd/research/202605/textual_image_rendering_research.md`
- Local-codebase grounding: `pyproject.toml:24` (Textual lower bound), `src/sase/main/parser_ace.py:8`,
  `src/sase/main/ace_handler.py:12`, `src/sase/ace/tui/graphics/viewer.py:171`,
  `src/sase/ace/tui/keymaps/types.py:54`, and the 13 `os.environ.get("EDITOR")` callsites listed in "Current SASE
  State".
