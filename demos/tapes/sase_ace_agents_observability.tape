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

Env COLORTERM "truecolor"
Env TERM "xterm-256color"

Hide
Type "repo_root=$PWD"
Enter
Type "export PATH=$repo_root/.venv/bin:$PATH"
Enter
Type "unset FORCE_COLOR NO_COLOR"
Enter
Type "export SASE_ACE_RELEASE_VERSION_TITLE=1"
Enter
Type "rm -rf /tmp/sase-ace-demo.aObs7Kd1"
Enter
Type "eval $(./demos/scripts/seed_sase_ace_demo /tmp/sase-ace-demo.aObs7Kd1)"
Enter
Type "sase agent index rebuild --json >/dev/null"
Enter
Type "cd $SASE_DEMO_WORKSPACE"
Enter
Type "clear"
Enter
Show

Type "sase ace --refresh-interval 0 --tab agents -x"
Hide
Enter
Wait+Screen /Agents/
Wait+Screen /nova--code/
Wait+Screen /nova--review/
Wait+Screen /gemini-2.5-pro/
Show
Sleep 2.5s

Type "j"
Wait+Screen /nova--code/
Wait+Screen /gpt-5-codex/
Sleep 1.2s
Type "j"
Wait+Screen /nova--plan-1/
Wait+Screen /claude-sonnet-4-6/
Sleep 1.5s

Type "h"
Wait+Screen /nova_prompt_input/
Sleep 1.2s
Type "l"
Wait+Screen /nova--plan-1/
Sleep 1.3s

Type "k"
Wait+Screen /nova--code/
Wait+Screen /gpt-5-codex/
Sleep 1.2s

Wait+Screen /diff --git/
Sleep 1.5s
Type "]"
Wait+Screen /TOOLS/
Wait+Screen /pytest tests\/test_parser.py/
Sleep 2s

Type "z"
Wait+Screen /ZOOM.*TOOLS/
Sleep 2.7s
Type "j"
Sleep 600ms
Type "q"
Wait+Screen /TOOLS/
Sleep 1s

Hide
Type "q"
Sleep 700ms
Type "exit"
Enter
