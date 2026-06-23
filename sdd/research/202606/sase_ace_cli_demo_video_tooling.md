---
create_time: 2026-06-23
status: research
---

# SASE ACE CLI Demo Video Tooling

## Question

What tooling and workflow should Bryan use to make high-quality demo videos of himself using `sase ace` from the
command line?

## Recommendation

Use a hybrid workflow:

1. **Flagship narrated videos:** record a real terminal session with **OBS Studio** on Linux/Windows, or **Screen Studio**
   on macOS if available. Edit the result in **Descript** for fast narration cleanup, or **DaVinci Resolve** when the
   video needs more precise editing, audio, zooms, or branding.
2. **Repeatable product clips:** use **Charm VHS** for scripted terminal demos that can be regenerated from `.tape`
   files. This is the best path for README loops, docs clips, launch-page snippets, and regression-friendly demo assets.
3. **Text-native technical casts:** use **asciinema CLI 3.x** for long-form terminal walkthroughs that should remain
   selectable text. Render GIF fallbacks with **agg** when a site cannot embed the asciinema player.
4. **Thumbnails and stills:** reuse the existing ACE/Textual screenshot machinery documented in
   `sdd/research/202606/tui_screenshots_and_demo_videos.md`. Static ACE shots should come from deterministic fixtures,
   not paused frames from a lossy video export.

The practical default stack for the first serious public demos is:

- **Capture:** OBS Studio, terminal window capture, 1920x1080 canvas, 30 fps, H.264 output.
- **Terminal:** fixed-size terminal at about 120x36 to 132x40 cells, Fira Code or JetBrains Mono, 20-24 pt for 1080p,
  high-contrast opaque theme, no desktop chrome beyond the terminal window.
- **Data:** fresh demo `SASE_HOME` and throwaway project state. Do not record the live home server state.
- **Editing:** Descript for spoken walkthroughs under about 10 minutes; DaVinci Resolve for launch-quality cuts.
- **Distribution:** MP4 H.264 for YouTube/docs, GIF only for short loops and GitHub fallback, asciinema for technical
  docs where selectable text matters.

## Tooling Matrix

| Tool | Best use | Strengths | Limitations | Recommendation |
|---|---|---|---|---|
| OBS Studio | Narrated screen recordings and live walkthroughs | Free, open source, cross-platform, window capture, scenes, webcam, mic, audio filters | Manual and not reproducible; needs setup discipline | Primary tool when the video should feel like Bryan using the product |
| Screen Studio | Polished macOS product demos | Automatic zooms, cursor smoothing, keyboard shortcut display, fast social/video exports | macOS-only and paid | Best quality-per-hour if recording on a Mac |
| VHS | Reproducible CLI/TUI clips | Demos as code; outputs GIF, MP4, WebM, PNG frames; good for committed assets | Scripted, not ad-libbed; uses ttyd/xterm.js so TUI rendering needs inspection | Use for docs/README/social loops and B-roll |
| asciinema CLI | Technical terminal casts | Tiny text-native recordings, selectable text, embeddable player, local or hosted playback | Not a normal video; full-screen TUIs need fixed geometry; GitHub README cannot embed JS player | Use for longer docs walkthroughs and developer-facing recordings |
| agg | GIF rendering from asciinema casts | Good GIF renderer, theme/font/idle-time controls, supports selecting excerpts | GIFs get large; not for narrated videos | Use as asciinema's GIF fallback |
| Descript | Narrated video editing | Text-based editing, transcription, screen recorder, captions, filler-word cleanup | Cloud/product dependency; less precise than timeline-first editors | Fastest path from raw voice recording to publishable tutorial |
| DaVinci Resolve | Polished post-production | Professional editor with video, color, effects, and Fairlight audio in one app; free version is strong | More setup and learning curve | Use for launch-quality videos, multi-clip edits, audio polish, and reusable branded exports |
| FFmpeg/gifsicle | Compression and transcodes | Scriptable, repeatable, useful for final size checks | CLI knobs are easy to overdo | Use at the end of the pipeline, not as the creative editor |

Avoid **terminalizer**, **ttygif**, **svg-term-cli**, and **termtosvg** for this job. The earlier TUI media research found
them stale or dormant relative to VHS/asciinema/agg. They do not solve the hard parts for `sase ace`: current TUI
rendering, reproducibility, narration, and polished exports.

## Current State Checked

Verified on 2026-06-23:

- VHS latest GitHub release: `v0.11.0`, released 2026-03-10. Its README documents `ttyd` and `ffmpeg` as required PATH
  dependencies, Docker as an all-dependencies option, `vhs record > cassette.tape`, and output formats including GIF,
  MP4, WebM, and PNG frame directories.
- asciinema CLI latest GitHub release: `v3.2.1`, released 2026-06-16. The docs cover `asciinema rec demo.cast`,
  `asciinema rec -c <command>`, `--idle-time-limit`, local/remote streaming, web embedding, and self-hosting.
- agg latest GitHub release: `v1.9.0`, released 2026-05-29. The docs cover themes, font selection, font size, line
  height, idle-time limiting, FPS caps, GIF optimization with gifsicle, terminal size overrides, and frame selection.
- OBS Studio latest GitHub release checked: `32.1.2`, released 2026-04-21. OBS remains the standard free recorder for
  scenes, window capture, mic input, and audio filters.
- GitHub upload constraints: images/GIFs are capped at 10 MB; videos are 10 MB on free plans or 100 MB on paid plans;
  GitHub recommends H.264 for broad video compatibility.
- YouTube's recommended upload settings include MP4, H.264 video, AAC-LC or Opus audio, 48 kHz sample rate, and Fast
  Start metadata.

## Best Workflow for Bryan-on-Camera / Narrated Demos

Use this for YouTube, launch posts, landing pages, and "watch me use SASE" demos.

### 1. Prepare a Clean Demo Environment

Create a fresh profile before every public capture:

```bash
export SASE_HOME="$(mktemp -d)"
export SASE_TMPDIR="$(mktemp -d)"
export PS1='$ '
```

Then seed a small but realistic project state. The seed should include:

- 4-8 ChangeSpecs across states such as Draft, WIP, Ready, Mailed, and Done.
- 2-4 agent runs with readable prompts, non-sensitive file paths, and plausible outcomes.
- At least one queued/running item if the video is about supervision.
- One clean "launch an agent" example that is safe to run live.

Longer-term, add a repo-owned `demos/seed_sase_ace_demo` helper so every recording starts from the same state. The seed
helper matters more than the capture tool. Without deterministic demo data, every tool produces fragile output.

### 2. Pick One Story per Video

Do not make the first video a full feature tour. Better demo shapes:

- **30-45 second teaser:** `sase ace` opens, Agents tab shows multiple runs, Bryan jumps through one agent's prompt,
  files, and result, then exits on the "SASE lets one developer supervise many agents" idea.
- **90 second workflow:** open `sase ace --tab agents`, inspect a running agent, jump to the related ChangeSpec, approve
  or adjust a plan, and show the resulting workspace/agent state.
- **5-7 minute walkthrough:** explain the mental model, then use ACE to monitor agents, launch one new task, handle a
  plan proposal, inspect output, and close with where durable state lives.

Keep each clip anchored in one concrete user promise. For SASE, the strongest public promise is not "a TUI exists"; it
is "agent work becomes observable, resumable, and coordinated."

### 3. Capture Settings

OBS baseline:

- Canvas/output: `1920x1080`, `30 fps`.
- Source: capture only the terminal window. Avoid full-display capture unless showing desktop integration.
- Audio: external mic if available. Record mic on its own track. Add light noise suppression and a noise gate only after
  testing that they do not clip quiet words.
- File container: record locally in a resilient format such as MKV if that is your normal OBS setup, then remux/export
  MP4 H.264 for publishing.
- Hotkeys: bind start/stop recording and pause/resume. Do a 10-second test recording before the real take.

Terminal profile:

- Use a fixed window size before launching `sase ace`; do not resize after the TUI starts.
- Use font size 20-24 pt at 1080p. If text is not readable at 50% playback size, it is too small.
- Disable transparency, background images, ligatures if they hurt alignment, desktop notifications, and shell prompt
  clutter.
- Use terminal padding large enough that cropped video does not put glyphs flush against the frame.
- Prefer `sase ace --tab agents --refresh-interval 0` for stable recorded state. Turn refresh back on only when the demo
  specifically needs live updates.

Screen Studio baseline on macOS:

- Use it when the recording should look like a modern product demo quickly.
- Let automatic zoom handle cursor-focused desktop actions, but manually add zooms for terminal text because TUI
  changes often happen without mouse movement.
- Use its keyboard shortcut display sparingly. ACE shortcuts are meaningful, but a constant keystroke overlay can
  distract from the UI.

### 4. Editing Standards

Cut aggressively:

- Remove terminal startup delays, login shell noise, and visible setup commands.
- Keep the first meaningful ACE screen within the first 5 seconds.
- Use zooms only to focus attention on a prompt pane, agent row, status marker, or detail panel. Do not zoom every
  navigation step.
- Add short title cards or lower-thirds only when the spoken narration cannot carry the context.
- Keep music absent or nearly inaudible. For technical product demos, clean voice and readable text matter more.
- Caption the final export. Captions help on social feeds and compensate for dense terminal text.

Export standards:

- Master: 1080p or 1440p MP4 H.264, 30 fps, AAC audio at 48 kHz.
- YouTube: MP4 H.264 with Fast Start. YouTube accepts higher resolutions, but terminal text usually benefits more from
  larger font and clean composition than from 4K.
- Docs/blog: MP4/WebM plus a static poster image.
- GitHub README: prefer an optimized GIF under 10 MB for autoplay loops, or a poster image linking to YouTube/docs for
  longer video.

## VHS Workflow for Repeatable Clips

Use VHS for demo assets that should live next to the code and be regenerated when ACE changes.

Proposed repo layout:

```text
demos/
  README.md
  scripts/
    seed_sase_ace_demo
  tapes/
    sase_ace_agents.tape
    sase_ace_prompt_launch.tape
  out/
    .gitignore
```

Example tape skeleton:

```tape
Output demos/out/sase_ace_agents.mp4
Output demos/out/sase_ace_agents.gif

Require bash
Require sase
Require ffmpeg
Require ttyd

Set Shell "bash"
Set FontFamily "Fira Code"
Set FontSize 22
Set Width 1280
Set Height 720
Set Theme "github-dark"
Set TypingSpeed 70ms
Set Framerate 30

Hide
Type "export SASE_HOME=$(mktemp -d)"
Enter
Type "export SASE_TMPDIR=$(mktemp -d)"
Enter
Type "./demos/scripts/seed_sase_ace_demo"
Enter
Type "clear"
Enter
Show

Type "sase ace --tab agents --refresh-interval 0"
Enter
Sleep 3s
Wait+Screen /Agents/
Type "L"
Sleep 1s
Type "j"
Sleep 700ms
Screenshot demos/out/sase_ace_agents.png
Sleep 1s
Type "q"
```

VHS tips:

- Use `Hide`/`Show` to keep setup out of the rendered clip.
- Use `Require` for `sase`, `bash`, `ffmpeg`, or any demo helper so broken render machines fail early.
- Prefer `Wait+Screen /regex/` to blind sleeps once the TUI has painted.
- Still include a short `Sleep` after launching ACE; full-screen TUI startup often needs a beat before the first clean
  frame.
- Render both MP4 and GIF. Use MP4 for quality and GIF only where autoplay or Markdown constraints make it useful.
- Inspect every VHS output for TUI rendering differences. VHS uses a browser terminal layer, not the exact terminal
  emulator Bryan records manually.

## asciinema + agg Workflow

Use this when the audience benefits from terminal text being copyable or when the recording is more like a developer log
than a polished product video.

Recommended command:

```bash
asciinema rec -i 2 -c 'sase ace --tab agents --refresh-interval 0' demos/casts/sase_ace_agents.cast
```

Render a GIF excerpt:

```bash
agg \
  --theme github-dark \
  --text-font-family "Fira Code,JetBrains Mono" \
  --font-size 20 \
  --line-height 1.4 \
  --idle-time-limit 1 \
  --fps-cap 20 \
  demos/casts/sase_ace_agents.cast \
  demos/out/sase_ace_agents.gif
```

Notes:

- Record at a fixed terminal size and document the `cols`/`rows`. Full-screen TUIs replay poorly when the player size is
  smaller than the recorded terminal.
- For docs pages, prefer the asciinema player over GIF when possible. It can pause, rewind, and preserve sharp text.
- For GitHub READMEs, use the asciinema SVG-preview-link pattern rather than trying to embed the JS player.
- Use `agg --select` to render only the useful part of a long cast.

## Demo Content Recommendations for `sase ace`

Strong demo beats:

- **Start from the shell:** type `sase ace` or `sase ace --tab agents`, then let the TUI take over. Viewers should see
  that ACE is a command-line-native control surface.
- **Show agent observability:** navigate an agent row, open its prompt/details, show changed files or status.
- **Show coordination:** move from an agent to a ChangeSpec or plan state. This is the product's differentiator.
- **Show launch ergonomics:** use the prompt input or quick-launch flow to start a new agent with project context.
- **Show durable state:** exit and re-open ACE, or briefly show that `sase agent list` / `sase plan` agrees with ACE.

Avoid first-video distractions:

- Deep configuration panels unless the video is specifically about config.
- Long waits for real LLM output. Use seeded output or cut the wait.
- Personal project names, local paths, notification text, mail/PR metadata, or real prompts.
- Tiny text. Terminal demos fail more often from unreadability than from weak tooling.

## Recording Checklist

Before capture:

- Fresh `SASE_HOME` and seeded demo data.
- Terminal geometry fixed and tested.
- Font, theme, and prompt profile selected.
- Notifications disabled.
- Secrets, real paths, and personal project state absent.
- Mic levels tested with a 10-second sample.
- Dry run completed without narration.

During capture:

- Move deliberately. TUI keyboard navigation can be fast, but video comprehension is slower than actual use.
- Pause half a second after each important screen change.
- If you make a small mistake, pause, restate the sentence, and continue. Remove the mistake in edit.
- Keep hands off unrelated windows.

After capture:

- Watch at 50% size with audio off to test text readability.
- Watch with eyes off-screen to test narration clarity.
- Check the first 10 seconds. If it does not show the product and the point, recut.
- Export one master MP4, one compressed web MP4, one poster PNG, and GIF/asciinema only when the channel needs them.

## Related Implementation Recommendations

1. Add a committed demo seeder. This is the highest-leverage improvement because it supports OBS, VHS, asciinema, docs
   screenshots, and future release media.
2. Add `just demo-video` recipes after the first tape exists:

   ```make
   demo-video-agents:
       vhs demos/tapes/sase_ace_agents.tape

   demo-cast-agents:
       asciinema rec -i 2 -c 'sase ace --tab agents --refresh-interval 0' demos/casts/sase_ace_agents.cast
   ```

3. Keep source media in repo when small: `.tape`, `.cast`, seed scripts, thumbnail source images, and notes. Keep large
   rendered MP4s in release assets, docs hosting, or external video platforms unless they are intentionally part of the
   docs site.
4. Create a short `demos/README.md` style guide with font, terminal size, theme, clip naming, export targets, and data
   hygiene rules.
5. Use the deterministic Textual screenshot path for thumbnails/posters so still images stay sharp and private.

## Source Links

- Prior local research: `sdd/research/202606/tui_screenshots_and_demo_videos.md`
- VHS README and command reference: <https://github.com/charmbracelet/vhs>
- VHS latest release: <https://github.com/charmbracelet/vhs/releases/latest>
- asciinema getting started: <https://docs.asciinema.org/getting-started/>
- asciinema CLI quick start: <https://docs.asciinema.org/manual/cli/quick-start/>
- asciinema CLI latest release: <https://github.com/asciinema/asciinema/releases/latest>
- agg usage: <https://docs.asciinema.org/manual/agg/usage/>
- agg latest release: <https://github.com/asciinema/agg/releases/latest>
- OBS Studio site/features: <https://obsproject.com/>
- OBS latest release: <https://github.com/obsproject/obs-studio/releases/latest>
- OBS noise suppression filter: <https://obsproject.com/kb/noise-suppression-filter>
- OBS noise gate filter: <https://obsproject.com/kb/noise-gate-filter>
- Screen Studio: <https://screen.studio/>
- Descript: <https://www.descript.com/>
- DaVinci Resolve: <https://www.blackmagicdesign.com/products/davinciresolve>
- GitHub file attachment limits and supported media: <https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/attaching-files>
- YouTube recommended upload encoding settings: <https://support.google.com/youtube/answer/1722171?hl=en>
