Output demos/out/sase_ace_agents_observability.mp4
Output demos/out/sase_ace_agents_observability.gif

Require bash
Require ttyd
Require ffmpeg
Require sase

Set Shell "bash"
Set FontFamily "Fira Code"
Set FontSize 20
Set Width 1920
Set Height 1080
Set Padding 20
Set LineHeight 1.2
Set Theme "GitHub Dark"
Set TypingSpeed 75ms
Set Framerate 30
Set CursorBlink false
Set WaitTimeout 15s

Hide
Type "repo_root=$PWD"
Enter
Type "export PATH=$repo_root/.venv/bin:$PATH"
Enter
Type "eval $(./demos/scripts/seed_sase_ace_demo)"
Enter
Type "sase agent index rebuild --json >/dev/null"
Enter
Type "cd $SASE_DEMO_WORKSPACE"
Enter
Type "clear"
Enter
Show

Type "sase ace --refresh-interval 0 --tab agents -x"
Enter
Wait+Screen /Agents/
Wait+Screen /nova--code/
Wait+Screen /nova--review/
Sleep 1.5s

Type "j"
Wait+Screen /claude-sonnet-4-6/
Sleep 900ms
Type "j"
Wait+Screen /nova--code/
Wait+Screen /gpt-5-codex/
Sleep 900ms
Type "j"
Wait+Screen /nova--review/
Wait+Screen /gemini-2.5-pro/
Sleep 1.2s

Type "h"
Wait+Screen /nova_cli_refresh/
Sleep 900ms
Type "l"
Wait+Screen /nova--review/
Sleep 1s

Wait+Screen /diff --git/
Sleep 1s
Type "]"
Wait+Screen /TOOLS/
Wait+Screen /python -m nova.cli --help/
Sleep 1.2s

Type "z"
Wait+Screen /ZOOM - TOOLS/
Sleep 1.5s
Type "j"
Sleep 600ms
Type "q"
Wait+Screen /TOOLS/
Sleep 700ms

Type "q"
Sleep 700ms
Type "exit"
Enter
