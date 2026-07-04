---
description: Configure Claude Code's statusLine to use this plugin's script
---

## Context

- This plugin's script is installed at `${CLAUDE_PLUGIN_ROOT}/bin/statusline.py`.
- Claude Code plugins cannot ship a default `statusLine` config — it has to be set in the user's own settings, so this command exists to do that setup for them.

## Your task

Use the `statusline-setup` agent to configure the statusLine. Instruct it to:

1. Update `~/.claude/settings.json` (or, if the user says they want this scoped to the current project instead, `.claude/settings.json`/`.claude/settings.local.json`), preserving every other existing setting, so that it contains:

   ```json
   "statusLine": {
     "type": "command",
     "command": "${CLAUDE_PLUGIN_ROOT}/bin/statusline.py"
   }
   ```

2. If `settings.json` is a symlink, edit the target file instead of overwriting the symlink.

After the agent reports back, tell the user:

- They need to start a new Claude Code session for the change to take effect (statusLine config is read once at session start).
- They can optionally create a `.claude/statusbar.yaml` in any project to set `context_position: front|end` and `show_last_command: true|false` — see this plugin's README for details.
