# Email Reading for Sase Agents — Lumberjack Chop Research

**Date:** 2026-04-28
**Goal:** Let sase agents read the user's email by adding a periodic email-reading chop to a lumberjack.
**Prior art surveyed:** `sase-telegram` (inbound/outbound chops), `sase-gchat` (CLI-backed chops),
`research/202602/telegram_integration.md`, `research/202604/gchat_integration_review.md`,
`docs/axe.md`, `src/sase/axe/lumberjack.py`, `src/sase/scripts/sase_chop_*.py`.

## 1. What "agents read email" can mean

These are three meaningfully different products. Pick one before designing — the chop, state layout, and
notification model are different in each case.

| Mode | What the chop does | Who consumes it | Closest existing analog |
|---|---|---|---|
| **A. Email → notifications** | Poll inbox, render new messages as sase notifications (`~/.sase/notifications/notifications.jsonl`). User sees them in ACE / telegram / gchat. | The user (and indirectly, agents that read the notification log). | `sase_chop_error_digest.py` + telegram outbound. |
| **B. Email → agent inbound (commands)** | Poll a designated label/sender, parse the body as a sase command or xprompt, launch agents. | The user emailing themselves or trusted senders. | `sase-telegram/.../sase_tg_inbound.py`, `sase_gc_inbound.py`. |
| **C. Email-as-tool for in-flight agents** | Provide a CLI / xprompt tool an agent can invoke during its run to search/fetch email. No periodic chop strictly required. | Agents working a task that needs context from email. | Any sase CLI subcommand (`sase axe`, `sase bead`, …). |

The user said *"agents to be able to read my email"* + *"create a lumberjack chop with us"*. That points at
**Mode A** as the primary target (a periodic poller surfacing new mail), with **Mode C** as a likely
follow-on (let an agent grep email on demand). **Mode B** is the most powerful but also the riskiest
(arbitrary inbound takes commands), and isn't required by the stated goal.

This research focuses on Mode A and Mode C, with Mode B sketched as a stretch.

## 2. Where the integration lives

### 2.1 Two viable homes

1. **New plugin `sase-gmail`** — mirrors `sase-telegram` and `sase-gchat`. Own repo at
   `~/projects/github/sase-org/sase-gmail`, own `pyproject.toml`, registers chops via
   `[project.entry-points."sase_xprompts"]` / scripts. Cleanest separation; matches the established
   pattern documented in `memory/long/external_repos.md`.
2. **Existing `sase-google` plugin** — already lives at `~/projects/github/sase-org/sase-google` and
   already aggregates Google-flavored functionality (Mercurial VCS, Jetski LLM). Adding a `gmail/`
   submodule there avoids spinning up a new repo.

**Recommendation: new `sase-gmail` repo.** `sase-google` is a Mercurial-VCS-and-internal-LLM plugin —
the only thing it shares with Gmail is the word "Google." Bundling unrelated capabilities under one
plugin makes versioning and the dependency surface harder. The cost of a new repo is one-time
(`pyproject.toml`, CI, `Justfile`) and matches what was done for telegram and gchat.

### 2.2 Lumberjack placement

The closest fit to this workload in `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml` is
the `telegram` lumberjack (5s interval) — a comm-channel pump. Email doesn't need 5s; new mail
typically lands every minute or longer.

Two options:

- Add a new `gmail` lumberjack (e.g. interval `30`, chop `run_every: 5m`).
- Reuse the `comments` lumberjack (1m default in `docs/axe.md`) for the outbound poll.

A dedicated lumberjack is cheaper to reason about and lets us tune polling without affecting unrelated
chops. Pick interval **30s with `run_every: 5m`** to give us low-jitter scheduling without hammering
the Gmail API; for a heavier user, drop `run_every` to 2m.

## 3. Chop design (Mode A: email → notifications)

### 3.1 Skeleton

Following the `sase_chop_*.py` contract (`src/sase/axe/chop_script_runner.py` discovers the script,
hands it `--context <ctx.json>`, reads stdout into the lumberjack log):

```python
# sase-gmail/src/sase_gmail/scripts/sase_chop_gm_inbound.py
def main():
    args = _parse_args()  # --context, --dry-run
    read_chop_context(args.context)              # validate
    if not _try_acquire_lock():                  # cross-process
        return 0
    try:
        last_seen = _read_last_seen()            # ~/.sase/gmail/last_seen.json
        new_msgs = gmail_client.list_messages(   # see §4 for transport
            query=f"-in:chats after:{last_seen}",
            max_results=50,
        )
        for msg in sorted(new_msgs, key=lambda m: m["internalDate"]):
            if _is_filtered(msg):                # by label allow/deny list
                continue
            notify_email_received(               # writes to notifications.jsonl
                subject=msg["subject"],
                sender=msg["from"],
                snippet=msg["snippet"],
                thread_id=msg["threadId"],
                msg_id=msg["id"],
            )
            _advance_last_seen(msg["internalDate"])
    finally:
        _release_lock()
```

State directory mirrors gchat/telegram — `~/.sase/gmail/`:
- `last_seen.json` — high-water-mark (epoch ms, advanced per-message; learn from gchat's per-msg
  advance per `research/202604/gchat_integration_review.md` §2).
- `outbound.lock` — `fcntl.flock` lock so two ticks can't double-deliver.
- `rate_limit.json` — sliding window if we worry about Gmail quota (default unit: 250 quota units/user/sec).
- `gmail_debug.log` — append captured API errors for post-mortem (gchat pattern).

### 3.2 Notification surface

Add `notify_email_received(...)` to `src/sase/notifications/senders.py` alongside the existing
`notify_*` functions (`notify_workflow_complete`, `notify_user_question`, …). The action type can be
`"EmailReceived"` with payload `{thread_id, msg_id, subject, sender}`. Telegram and gchat formatters
already render unknown action types via the generic path (`research/202604/gchat_integration_review.md`
§2 lists the supported types and notes the generic fallback), so it propagates for free.

If we want the user to *act* on the email from telegram/gchat (reply, archive, snooze), add the
formatters and pending-action wiring later — out of scope for v1.

### 3.3 What counts as "new"?

Three filtering layers, configurable in `sase.yml`:

```yaml
gmail:
  query: "is:unread -category:promotions -category:social"
  allow_labels: ["INBOX", "IMPORTANT"]
  deny_senders: ["noreply@*"]
  max_per_tick: 50
```

Pass these through `chop.env` (`SASE_GMAIL_QUERY=...`) the way telegram threads `SASE_TELEGRAM_BOT_*`
into `sase_athena.yml`.

## 4. Transport: how to actually fetch mail

This is the most important architectural choice. Four candidates, in increasing build cost and
decreasing footgun risk:

### 4.1 Option A — Gmail API via `google-api-python-client` (recommended)

- Library: `google-api-python-client` + `google-auth-oauthlib` (both well-maintained).
- Auth: OAuth2 with offline access. One-time `gcloud auth application-default login` *or* a Google
  Cloud project with a desktop OAuth client + token cached at `~/.sase/gmail/token.json`.
- Quota: 1 billion units/day per project; `messages.list` = 5 units, `messages.get` = 5 units. For 5m
  polling and 50 messages/tick that's ~150k units/day. Far below the limit.
- Pros: Server-side filtering (`q="is:unread after:..."`), label support, batch get, attachment
  download, mark-as-read mutation, incremental sync via `historyId` once warmed up.
- Cons: First-time auth flow needs a browser. Refresh tokens can expire after 7 days if the OAuth
  consent screen is in "Testing" status — must publish or whitelist the user.

### 4.2 Option B — IMAP via `imaplib` (stdlib)

- Auth: App Password (since Google disabled "less secure apps"). Stored in `pass` like the telegram
  bot token (`get_bot_token()` already uses `pass show telegram_sase_bot_token` —
  `sase-telegram/.../credentials.py`).
- Pros: Zero new dependencies (stdlib). No OAuth dance.
- Cons: IMAP idle/poll is clunky for high-frequency polling; label support is mapped to folders;
  marking-as-read semantics are quirky; no thread-level API.

### 4.3 Option C — Reuse the claude.ai Gmail MCP server

- The active Claude environment already has `mcp__claude_ai_Gmail__search_threads`,
  `mcp__claude_ai_Gmail__get_thread`, `mcp__claude_ai_Gmail__list_drafts`, etc. (visible in tool
  inventory). Authentication is already done at the claude.ai side.
- Pros: Zero auth setup for the user.
- Cons: Only available *inside* a Claude agent run — not from a chop subprocess. The chop runs as a
  separate process under the lumberjack, with no MCP client wired in. We'd have to either (a) ship a
  wrapper that talks to the user's claude.ai MCP endpoint outside an agent (likely impossible — it's
  agent-scoped), or (b) launch a tiny agent on each tick whose only job is to call the MCP and write
  results — wasteful and slow. Reject for the chop. **However, see Mode C below — this is exactly the
  right tool for in-agent email access.**

### 4.4 Option D — `himalaya` / `notmuch` / `mbsync` CLI

- Wrap an existing local-mail CLI in a Python subprocess (mirrors how `sase-gchat` wraps the `gchat`
  CLI; see `gchat_client.py` `_with_retry`).
- Pros: Local cache, offline-friendly, mature filtering.
- Cons: Adds a system-level dep the user must install and configure separately. Slower to set up than
  Option A for a single-machine user.

**Recommendation for v1:** Option A (Gmail API). Option C is the right answer for **Mode C**
(see §6).

## 5. Concrete config addition

What the user adds to `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`:

```yaml
axe:
  lumberjacks:
    gmail:
      interval: 30
      chops:
        - name: gm_inbound
          description: "Surface new Gmail messages as sase notifications"
          run_every: 5m
          env:
            SASE_GMAIL_QUERY: "is:unread -category:promotions"
            SASE_GMAIL_MAX_PER_TICK: "50"
```

The chop script itself is discovered by name (`sase_chop_gm_inbound`) — the `chop_script_dirs` setting
(see `docs/axe.md` "Global Settings") lets us add the `sase-gmail` package's scripts dir, or we ship
the script as an installed entry point so it's on `$PATH` (telegram does this — see
`pyproject.toml` `[project.scripts]` in `sase-google`).

## 6. Mode C — in-agent email access (parallel work item)

For agents that need to *query* email mid-task ("summarize what my advisor sent yesterday"), the right
hook is **not** a chop — it's a sase CLI subcommand or xprompt tool the agent can invoke.

Two paths:

1. **`sase gmail search -q <query>` CLI** — thin wrapper over the same `gmail_client` from §4.1.
   Returns JSON. Agents call it via `Bash` like they call `sase bead show`, etc.
2. **Wire the Claude MCP Gmail server through to agent runtimes that support MCP.** For Claude Code
   specifically, this is configured per-project in `.mcp.json` or per-user in `~/.claude.json`. The
   MCP tools listed at session start (`mcp__claude_ai_Gmail__*`) are already there for the *current*
   session — meaning the user already has the integration enabled at the claude.ai side. We just
   need to make sure spawned sase agents inherit it, which depends on the runtime
   (Claude Code: yes via `~/.claude.json`; Codex/Gemini: no MCP equivalent yet, would need a CLI).

The CLI approach is **runtime-agnostic** and matches the gotcha in `memory/short/gotchas.md`:
*"All supported agent runtimes (Claude, Gemini, Codex, etc.) have the same capabilities … Treat all
runtimes uniformly."* Don't gate the feature on Claude-only MCP.

## 7. Auth & secrets

- Gmail API token: store the cached refresh token at `~/.sase/gmail/token.json` with `0600`. The
  initial OAuth flow runs on the user's machine via `google-auth-oauthlib`'s
  `InstalledAppFlow.run_local_server()`.
- Optional: stash the *client secret* JSON (from the Google Cloud project) in `pass` similarly to
  `pass show telegram_sase_bot_token`. Add a setup script `sase gmail setup` analogous to
  `sase_gchat_setup` (referenced in `plans/202604/sase_gchat_setup.md`).
- Secret rotation: refresh-token revocation goes via Google Account → Security → Third-party access.
  Document it in the README.

## 8. Failure modes & gotchas

- **Quota exhaustion** — unlikely at sane intervals, but guard: catch `HttpError 429` and back off
  (mirror gchat's `_with_retry`). Don't advance `last_seen` on failure.
- **Clock skew on resumed laptops** — Gmail's `internalDate` is server time, which is what we should
  store. Don't compare against local `time.time()`.
- **Refresh-token expiry in OAuth "Testing" mode** — explicit setup-doc warning.
- **Notification spam on first run** — if `last_seen.json` is missing, the chop should *not* dump the
  whole inbox. Bootstrap by writing `now()` to `last_seen.json` and starting from there. (Telegram has
  the same first-run problem and solves it the same way.)
- **Deduplication on lumberjack restart** — the `~/.sase/axe/lumberjacks/gmail/agent_chops.json`
  registry (see `docs/axe.md` "Chop-Agent Registry") doesn't help here because we're a script chop,
  not an agent chop. The `last_seen.json` HWM is what protects against re-delivery.
- **Cross-machine** — if the user runs sase on multiple machines (sase-gchat has explicit
  cross-machine self-message filtering — see `sase_gchat/self_messages.py`), each machine will deliver
  notifications independently. Either (a) shard by hostname in `last_seen.json`, or (b) accept the
  duplication. Pick (a) only if it's actually an issue in practice.

## 9. Scope for v1

A minimal first PR set, in order:

1. **`sase-gmail` repo skeleton** — `pyproject.toml`, `Justfile`, `README.md`, `src/sase_gmail/`
   layout, CI config. Mirror `sase-gchat`.
2. **`gmail_client.py`** — Gmail API wrapper with `_with_retry`, `list_messages`, `get_message`,
   debug-log append. ~150 LOC.
3. **`sase_chop_gm_inbound.py`** — outbound chop script (Mode A). ~150 LOC.
4. **`notify_email_received` in `sase_100/src/sase/notifications/senders.py`** — one new function
   following the existing pattern.
5. **Setup script `sase gmail setup`** — OAuth client config + first-time consent + token cache.
6. **Docs:** `sase-gmail/README.md`, plus a one-line note in `docs/axe.md` next to `error_digest`.
7. **Chezmoi config update** — add the `gmail` lumberjack stanza to `sase_athena.yml`.

Mode C (in-agent CLI / MCP) ships as a follow-on PR.

## 10. Recommendation summary

- New repo `sase-gmail`, sibling to `sase-telegram` / `sase-gchat`.
- Gmail API (Option A in §4) for the chop transport.
- One new lumberjack `gmail` (interval 30s, `run_every 5m`) with one chop `gm_inbound`.
- One new notification action `EmailReceived` plumbed through the existing senders module.
- Reuse existing telegram/gchat patterns: HWM file, outbound lock, debug log, secrets in `pass`.
- Defer email-as-inbound-command (Mode B) until there's a clear use case; surface email-search-as-tool
  (Mode C) as a separate `sase gmail` CLI in a follow-up.

## Appendix — file references

- `src/sase/axe/lumberjack.py` — main loop, `_run_tick`, `_run_single_chop`, `_chop_launch_env`.
- `src/sase/axe/chop_script_runner.py` — `discover_chop_script`, `run_chop_script`.
- `src/sase/axe/chop_script_context.py` — context schema passed to script chops.
- `src/sase/notifications/senders.py:13-191` — existing `notify_*` functions to model after.
- `src/sase/scripts/sase_chop_error_digest.py` — minimal script-chop reference.
- `~/projects/github/sase-org/sase-gchat/src/sase_gchat/scripts/sase_gc_outbound.py` — modern
  outbound-pump example (per-msg HWM advance, lock, dry-run flag).
- `~/projects/github/sase-org/sase-gchat/src/sase_gchat/gchat_client.py` — `_with_retry` pattern, debug
  log append.
- `~/projects/github/sase-org/sase-telegram/src/sase_telegram/credentials.py` — `pass`-backed secret
  retrieval pattern.
- `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml` — where the user adds the `gmail`
  lumberjack stanza.
