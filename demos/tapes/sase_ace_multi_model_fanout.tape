Output demos/out/sase_ace_multi_model_fanout.mp4
Output demos/out/sase_ace_multi_model_fanout.gif

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
Type "rm -rf /tmp/sase-ace-demo.mFan0Ut5"
Enter
Type "eval $(./demos/scripts/seed_sase_ace_demo /tmp/sase-ace-demo.mFan0Ut5)"
Enter
Type "sase agent index rebuild --json >/dev/null"
Enter
Type "cd $SASE_DEMO_WORKSPACE"
Enter
Type "python - <<'PY'"
Enter
Type "from sase.agent.launch_preview import build_launch_preview_request, write_launch_preview_files"
Enter
Type "from sase.agent.launch_request import _preview_context"
Enter
Type "from sase.agent.multi_prompt import parse_multi_prompt"
Enter
Type "from sase.core.agent_launch_facade import plan_fake_fanout"
Enter
Type "from sase.notifications import Notification, append_notification, normalize_notification_tags"
Enter
Type "segments = ["
Enter
Type "    '#git:nova %model:claude-sonnet-4-6 Audit parser risks.',"
Enter
Type "    '#git:nova %model:gpt-5-codex Add parser tests.',"
Enter
Type "    '#git:nova %model:gemini-2.5-pro Review release notes.',"
Enter
Type "]"
Enter
Type "prompt = (chr(10) + '---' + chr(10)).join(segments)"
Enter
Type "multi = parse_multi_prompt(prompt)"
Enter
Type "plan = plan_fake_fanout('multi_prompt', multi.segments)"
Enter
Type "request_id = 'launch-demo-multi-model-fanout'"
Enter
Type "request = build_launch_preview_request(plan=plan, context=_preview_context(), source_surface='ace', request_id=request_id, submitted_prompt=prompt, created_at_unix=1783345500.0)"
Enter
Type "paths = write_launch_preview_files(request)"
Enter
Type "append_notification(Notification(id='launch-demo-multi-model-fanout-notification', timestamp='2026-07-06T14:00:00-04:00', sender='launch', notes=['Launch approval requested: 3 slots', 'Source: ace'], files=[str(paths['preview']), str(paths['request'])], action='LaunchApproval', action_data={'response_dir': str(paths['response_dir']), 'request_id': request_id, 'source_surface': 'ace', 'slot_count': '3'}, tags=normalize_notification_tags(['launch'])))"
Enter
Type "PY"
Enter
Type "clear"
Enter
Show

Type "sase ace --refresh-interval 0 --tab agents -x"
Hide
Enter
Wait+Screen /Agents/
Wait+Screen /nova--code/
Show
Sleep 1s

Space
Wait+Screen /Type prompt/
Sleep 500ms

Type "+nov"
Wait+Screen /#git:nova/
Sleep 700ms
Ctrl+L
Wait+Screen /#git:nova/
Sleep 500ms

Type " %mo"
Wait+Screen /directives/
Wait+Screen /model/
Sleep 900ms
Ctrl+L
Wait+Screen /%model/
Type ":claude-sonnet-4-6 Audit parser risks."
Sleep 700ms

Escape
Sleep 300ms
Type "g-"
Wait+Screen /Prompt.*2 agents/
Sleep 500ms
Type "#git:nova %mo"
Wait+Screen /directives/
Wait+Screen /model/
Sleep 900ms
Ctrl+L
Wait+Screen /%model/
Type ":gpt-5-codex Add parser tests."
Sleep 700ms

Escape
Sleep 300ms
Type "g-"
Wait+Screen /Prompt.*3 agents/
Sleep 500ms
Type "#git:nova %mo"
Wait+Screen /directives/
Wait+Screen /model/
Sleep 900ms
Ctrl+L
Wait+Screen /%model/
Type ":gemini-2.5-pro Review release notes."
Wait+Screen /Prompt.*3 agents/
Wait+Screen /gemini-2.5-pro/
Sleep 1400ms

Ctrl+C
Sleep 350ms
Ctrl+C
Sleep 350ms
Ctrl+C
Sleep 700ms
Type "i"
Wait+Screen /Notifications/
Wait+Screen /Launch approval requested: 3 slots/
Sleep 1200ms
Enter
Wait+Screen /Launch Review/
Wait+Screen /claude-sonnet-4-6/
Wait+Screen /gpt-5-codex/
Wait+Screen /gemini-2.5-pro/
Sleep 3200ms
Escape
Sleep 700ms

Hide
Type "q"
Sleep 700ms
Type "exit"
Enter
