# Sharing MacBook Screenshots with Remote Agents

**Date:** 2026-06-12
**Status:** Final consolidated research. Merges two independent research runs: a broad option survey
and a deep-research run (19 sources, 25 claims adversarially verified by 3-vote panels; key tools
verified at code level).

## Request

I need a way to take screenshots on my MacBook and easily let agents on a remote machine view them.
The initial idea was a remote image hosting service; this memo covers the full option space and ends
with a recommended solution.

## TL;DR

**You don't need an image hosting service.** Agents like Claude Code officially accept local image
file paths as input — confirmed in Anthropic's docs and empirically tested during verification by an
agent on a remote Linux machine [high confidence, 3-0]. So the lowest-friction, most private, free,
and most reliable solution is a **file-sync pipeline**: one macOS hotkey runs `screencapture -i` and
`scp`/`rsync`s the result over your existing SSH keys to a predictable path on the remote agent
host; the agent then reads that path directly. At least four independent purpose-built tools
implement exactly this pattern for exactly this use case.

If an agent genuinely needs a fetchable URL (because it is not on your host or tailnet), the best
hosted option is a **private Cloudflare R2 (or S3) bucket with short-lived presigned URLs**, which
polished macOS capture apps (Shottr, Dropshare, macshot) can upload to directly.

**Avoid public anonymous image hosts** (Imgur, ImgBB, Postimages, 0x0.st) for work screenshots on
privacy, ToS, and bot-blocking grounds.

## Requirements

A good option should satisfy most of these:

- Low-friction capture on macOS — native screenshot hotkeys or a polished capture app.
- Agent-friendly access: a local file path on the agent host, or a direct `curl`-able image URL (no
  browser-only auth, JavaScript viewer page, CAPTCHA, or account cookie).
- Private by default — screenshots routinely capture terminals, tokens, email, and project context.
- Easy deletion or automatic expiration.
- Minimal cost at screenshot scale; simple enough to not become another service to babysit.

## Option Matrix

| Option | Agent access shape | Privacy | Mac friction | Ops load | Fit |
| --- | --- | --- | --- | --- | --- |
| `screencapture` + `scp`/`rsync` hotkey | Local path on agent host | Strong | One hotkey | Low (~50 lines of shell) | **Recommended primary** |
| Dropshare → SFTP/SCP to agent host | Remote path / URL on clipboard | Strong if server private | Low | Low | Best polished-app UX for your own host |
| Syncthing shared folder | Local path on agent host | Strong | Low after setup | Medium (daemons both sides) | Continuous mirrored inbox |
| Tailscale Serve over screenshot dir | Tailnet-private HTTPS URL | Strong | Medium | Low | URL layer on top of host-side directory |
| Cloudflare R2 (private + presigned) | Expiring HTTPS URL | Strong | Medium unless app wraps upload | Low | **Recommended URL fallback** |
| Backblaze B2 / AWS S3 | HTTPS or presigned URL | Medium–strong | Low–medium | Low–medium | R2 alternates |
| Cloudinary | CDN image URL | Medium | Medium | Low | Only if transforms/CDN needed |
| Dropbox/Drive/iCloud links | Share link (often a preview page) | Medium | Low | Low | Human sharing; unreliable for agents |
| Imgur/ImgBB/Postimages/0x0.st | Public image URL | Weak | Low | Low until limits/policy bite | Not recommended |

## Options

### 1. File-sync to the remote agent host (winner)

The agent reads the image as a local file (e.g. `Analyze this image: /tmp/screenshots/foo.png`).
This is the most reliable consumption mode: no URL fetch policies, no link expiry, and the
reference stays valid in long-lived conversation history as long as the file persists.

Workflow:

1. Point native macOS screenshots (`Shift-Command-5` → Options) at a dedicated folder, e.g.
   `~/Pictures/Agent Screenshots`.
2. A hotkey service, Folder Action/Shortcut, or `fswatch` watcher uploads each capture to the
   remote host with `scp`/`rsync` over existing SSH keys.
3. The uploader puts a prompt-ready reference (the host-local path) on the Mac clipboard.
4. Paste the path into the agent prompt; clean up host-side with an age-based cron delete.

Two proven path shapes:

- **Stable path:** always overwrite `~/screenshots/latest.png` on the remote. The agent instruction
  is simply "look at ~/screenshots/latest.png" — zero paste friction, but only the most recent
  capture is kept.
- **Timestamped + clipboard:** write `/tmp/screenshots/<timestamp>.png` and `pbcopy` the remote
  path — keeps history and supports multiple screenshots per conversation.

Multiple independent tools were built specifically because terminal agents over SSH cannot receive
local clipboard image pastes. All were code-verified [high confidence, 3-0]:

| Tool | Pipeline |
|---|---|
| [jeitnier/claude-screenshot-workflow](https://github.com/jeitnier/claude-screenshot-workflow) | Automator hotkey → `screencapture -i` → `scp` to stable remote path (`~/screenshots/latest.png`) |
| [mdrzn/claude-screenshot-uploader](https://github.com/mdrzn/claude-screenshot-uploader) | `fswatch` on the Screenshots folder → `rsync -e ssh` → remote path to clipboard via `pbcopy` |
| [samuellawrentz/clipssh](https://github.com/samuellawrentz/clipssh) | Clipboard PNG → SSH upload to `/tmp/clipboard-<timestamp>.png` (umask 077) → path on clipboard |
| [Image Paste for Remote SSH (VS Code ext)](https://marketplace.visualstudio.com/items?itemName=asfeng.claude-code-image-paste) | Alt+I → clipboard image written to remote `/tmp/screenshots/` over the Remote SSH channel → path auto-inserted |

Evaluation:

- **Friction:** one hotkey (or one paste) per screenshot. The claim that the fswatch watcher runs
  fully unattended as a launchd login service was **refuted (1-2)** — treat zero-interaction
  background sync as configuration-dependent; the verified floor is one hotkey/paste per capture.
- **Privacy:** best in class — screenshots never leave machines you control; no third party, no URL.
- **Cost:** $0; only built-in macOS tooling (`screencapture`, `scp`/`rsync`, optionally `fswatch`).
- **Reliability:** no service to die. Caveat: the proving tools are tiny personal projects (1–35
  stars) — evidence the pattern works, not products. Expect to own your ~50 lines of shell.
- **Limitation:** only helps agents on that host (or hosts that can reach the directory).

Variants on the same model:

- **Syncthing**: continuously mirror the screenshot folder to the agent host — private peer-to-peer,
  encrypted, no external storage. More moving parts (a daemon on both sides, device trust), and you
  still need a "latest screenshot" convention. Attractive if screenshots are frequent and you want a
  persistent mirrored inbox.
- **Tailscale Taildrop**: fine for manual one-off transfers, but documented as alpha and limited to
  personal devices — not a good automation primitive.
- **Tailscale Serve**: expose the host-side screenshot directory privately to your tailnet when a
  normal HTTPS URL is more convenient than a path. (Tailscale Funnel makes it public — use only for
  deliberately public, temporary links.)

### 2. Mac capture apps as the front end

These reduce Mac-side friction; pick one if you'd rather not own a script:

- **[Shottr](https://shottr.cc/)** [high, 3-0]: free; uploads to any S3-compatible backend (R2,
  MinIO, …) and explicitly supports private buckets via auto-generated presigned URLs (up to 7
  days); images "never pass through Shottr server". Friction ≈ capture hotkey + upload hotkey.
- **[Dropshare](https://dropshare.app/)**: commercial; uploads to ~30+ user-configured targets —
  S3-compatible (R2, B2, MinIO) plus SFTP/FTP/SCP/WebDAV to your own server — with a CLI and Apple
  Shortcuts/hotkey automation. Best off-the-shelf UX for the "upload to my own host" model. Caveat:
  its presigned-URL support for private buckets carried only a 2-1 verification vote and all
  sourcing is vendor-authored; its R2 walkthrough demos a public-bucket flow by default.
- **[macshot](https://github.com/sw33tLie/macshot)** [high, 3-0]: open-source GPL-3.0 (~2k stars,
  actively released); ⌘⇧X capture + one-click upload to any S3-compatible endpoint, link copied
  instantly. **Warning:** link privacy semantics (presigned vs public) are undocumented — verify
  before trusting with sensitive content.
- **CleanShot X / CleanShot Cloud**: excellent capture/annotation UX and human sharing (expiring,
  password-protected links), but it's a hosted vendor cloud and links may resolve to viewer pages
  rather than raw image bytes. Fine as the capture tool; don't make CleanShot Cloud the agent
  backend unless direct-image-URL behavior is verified.

### 3. Object storage with presigned URLs (the URL fallback)

When an agent must fetch a URL (it isn't on your host or tailnet), use object storage you control —
not a consumer image host.

**Cloudflare R2** is the best-researched fit: S3-compatible, no egress fees, a free tier that
comfortably covers screenshot volume (10 GB-month storage, 1M class-A / 10M class-B ops; paid
storage $0.015/GB-month after), `rclone` support, public buckets via managed subdomain or custom
domain, and presigned URLs for private objects.

Presigned-URL mechanics and caveats [high, 3-0]:

- Buckets are private by default; presigned URLs grant temporary credential-free access with expiry
  configurable from **1 second to 7 days** (the SigV4 cap), so links to sensitive screenshots
  automatically die.
- Presigned URLs are bearer tokens — anyone holding one can fetch until expiry — and on R2 they only
  work on the S3 API domain (no custom domains). Expiry only protects an object if the bucket isn't
  separately exposed via r2.dev/custom-domain public access.
- The 7-day cap means URL-based workflows yield ephemeral references — unsuitable for long-lived
  conversation history (another reason file paths win as the primary).

Recommended R2 patterns: private bucket + short-lived presigned GET URLs for anything potentially
sensitive; public bucket + long random object names + 7–30-day lifecycle cleanup only for
explicitly low-risk captures.

Alternates:

- **Backblaze B2**: cheap, mature, S3-compatible, free egress up to 3x average monthly storage
  ($0.01/GB beyond), and a first-party Dropshare integration guide. Use it if you already trust
  Backblaze or Dropshare's B2 flow feels smoother.
- **AWS S3**: the conservative enterprise answer — mature IAM, lifecycle, audit; presigned URLs up
  to 7 days via CLI/SDK (console-generated ones cap at 12 hours). More IAM/billing surface than R2
  for a personal workflow.
- **Cloudinary**: only if image transforms/thumbnails/CDN delivery become real requirements;
  otherwise it's overbuilt and another third party holding sensitive screenshots.

### 4. Consumer cloud drives (Dropbox, Google Drive, iCloud)

Easy for humans, weak for agents: share links often resolve to preview pages, and direct raw-image
retrieval depends on URL forms (`dl=1` on Dropbox), access settings, and anti-abuse behavior.
Acceptable manual fallback, not a foundation.

### 5. Public image hosts — disqualified

- **Imgur / ImgBB / Postimages**: screenshots become public or effectively public; deletion,
  retention, and direct-link behavior are service-specific; rate limits and anti-abuse systems can
  break automation. Imgur mass-purged images not linked to accounts in 2023 — a longevity risk.
- **0x0.st** is actively hostile to this exact workflow [high, 3-0, observed live 2026-06-12]: it
  returns **HTTP 418 to automated fetchers** (an agent may not even be able to fetch the link), its
  ToS prohibits automated uploads with IP-blocking enforcement, and the operator states there are no
  privacy guarantees. A claim that it accepts simple scripted curl uploads was **refuted (0-3)**.
- "Unguessable URL" privacy is weak in general — URLs leak via logs, proxies, and link previews.

Treat these as disposable debugging tools only, never for work screenshots.

## Security Notes

Screenshots are high-risk because they capture surrounding context (terminals, tokens, email).
Assume some captures will include secrets:

- Prefer private transfer to the agent host over any hosting; if URLs are needed, prefer short-lived
  presigned URLs and random object names.
- Add automatic cleanup (7–30 days) on whatever stores the images.
- Keep the screenshot inbox outside the repo unless a capture is intentionally promoted to an
  artifact.
- Consider a redact-before-upload step for sensitive windows.

## Verification Notes & Open Questions

Refuted during adversarial verification:

| Claim | Vote |
|---|---|
| 0x0.st accepts file uploads via a single curl command, fully scriptable from macOS | 0-3 |
| mdrzn's uploader needs no interaction beyond the native screenshot hotkey (launchd login service) | 1-2 |

Caveats: the file-sync tools are code-verified proofs of pattern, not products; Dropshare's
private-bucket support is vendor-sourced (2-1 vote); macshot's link privacy is undocumented;
0x0.st findings reflect the live site as of 2026-06-12. Self-hosted image hosts (Chevereto,
Zipline) were not evaluated — on first principles they add a service to run/patch/back up while
offering little over a plain private R2/MinIO bucket here. Other open questions: whether the
fswatch/launchd watcher can be made reliably fully automatic on modern macOS (login persistence,
TCC permissions), and whether agent URL-fetch tools reliably handle long SigV4 presigned query
strings.

## Recommended Solution

Use a **private screenshot inbox on the remote agent host**, fed by a one-hotkey capture→upload
pipeline — not an image hosting service.

1. Point macOS screenshots (`Shift-Command-5`) at a dedicated folder.
2. **Primary pipeline:** bind one hotkey (Shortcuts/Automator service or Hammerspoon) that runs
   `screencapture -i` and `scp`s the result over existing SSH keys to a predictable remote path —
   ~50 lines of owned shell, $0, nothing leaves machines you control. If you want a polished app
   instead of a script, configure **Dropshare** with SFTP/SCP to the same host.
3. Pick a path shape: stable `~/screenshots/latest.png` (zero paste friction) or timestamped paths
   with `pbcopy` (keeps history). Hand the agent the host-local path.
4. Add an age-based cleanup (14–30 days) on the remote directory. If a browser-friendly link is
   occasionally useful, expose the directory privately with **Tailscale Serve**.
5. **URL fallback** for agents not on your host or tailnet: point **Shottr** (free, documented
   presigned support) at a **private Cloudflare R2 bucket** and share short-expiry presigned URLs
   (minutes to hours; 7-day max).
6. **Avoid** public anonymous hosts (Imgur-style, 0x0.st) for work screenshots — privacy by
   obscurity only, ToS/bot-blocking hostility to agents, and link rot.

This matches the real trust boundary (MacBook → your agent host), gives agents their most reliable
input mode (a local file path), and keeps a clean upgrade path to expiring URLs when a path isn't
enough.

## Sources

Primary (code-verified or official docs):

- [Claude Code image workflows](https://code.claude.com/docs/en/common-workflows) (local-path input)
- [jeitnier/claude-screenshot-workflow](https://github.com/jeitnier/claude-screenshot-workflow),
  [mdrzn/claude-screenshot-uploader](https://github.com/mdrzn/claude-screenshot-uploader),
  [samuellawrentz/clipssh](https://github.com/samuellawrentz/clipssh),
  [Image Paste for Remote SSH](https://marketplace.visualstudio.com/items?itemName=asfeng.claude-code-image-paste) (VSIX inspected)
- Apple: [Take a screenshot on Mac](https://support.apple.com/en-us/102646),
  [Automator shell scripts](https://support.apple.com/guide/automator/use-scripts-aut4bb6b2b4f/mac)
- Cloudflare R2: [pricing](https://developers.cloudflare.com/r2/pricing/),
  [presigned URLs](https://developers.cloudflare.com/r2/api/s3/presigned-urls/),
  [public buckets](https://developers.cloudflare.com/r2/buckets/public-buckets/),
  [rclone](https://developers.cloudflare.com/r2/examples/rclone/)
- [Shottr S3 KB](https://shottr.cc/kb/s3), [Dropshare](https://dropshare.app/),
  [macshot](https://github.com/sw33tLie/macshot)
- [Backblaze B2 pricing](https://www.backblaze.com/cloud-storage/pricing),
  [Backblaze Dropshare guide](https://www.backblaze.com/docs/cloud-storage-upload-files-to-backblaze-b2-with-dropshare)
- [AWS S3 presigned URLs](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html)
- [Tailscale Taildrop](https://tailscale.com/docs/features/taildrop),
  [Serve](https://tailscale.com/docs/features/tailscale-serve),
  [Funnel](https://tailscale.com/docs/features/tailscale-funnel)
- [Syncthing](https://syncthing.net/), [0x0.st](https://0x0.st/) (fetched live 2026-06-12),
  [Pulse Security on unguessable URLs](https://pulsesecurity.co.nz/articles/unguessable_url_issues)

Secondary: [CleanShot Cloud](https://cleanshot.com/product/cloud),
[Cloudinary](https://cloudinary.com/pricing), [Imgur API](https://apidocs.imgur.com/),
[ImgBB API](https://api.imgbb.com/), [Postimages](https://postimages.org/),
[Dropbox force-download links](https://help.dropbox.com/share/force-download),
PetaPixel on the 2023 Imgur purge.
