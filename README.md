# Status Line for Claude Code

A rich terminal status line showing **model**, **context window usage**, **active todo tasks**, **spec-kit feature state**, and **rate limit meters**.

## Layout

```
<dim>sonnet</dim> │ <bold>Implement auth middleware</bold> │ <dim>my-app</dim>  ████░░░░░░ 62%
<dim>5h</dim> ██░░░ 34% <dim>wk</dim> ████░ 81% │ <dim>↻ 5h 3pm · wk Tue 3pm</dim>
```

Row 1 segments: `model` · `task / speckit state` · `directory` · `context bar`

Row 2 (shown only when rate-limit data is available): `5h`/`wk` usage meters and reset times, kept on their own line so they don't crowd the primary row.

Position defaults to **end** (right-aligned). Toggle with `.claude/statusbar.json`:
```json
{ "context_position": "front" }
```

## Install

### 1. Install the plugin

```bash
claude plugin install kerryhatcher/status-line
```

This places `bin/statusline.py` on your PATH via the plugin system.

### 2. Enable the status line

Add to your Claude Code **settings.json** (`~/.claude/settings.json`):

```json
{
  "statusLine": {
    "type": "command",
    "command": "statusline.py"
  }
}
```

> **Note:** Claude Code plugins cannot ship a default `statusLine` config — it must be set in your user settings. The `bin/` directory is added to PATH automatically, so the script is invokable by name.

### Alternative: full path

If you prefer not to rely on PATH resolution:

```json
{
  "statusLine": {
    "type": "command",
    "command": "${CLAUDE_PLUGIN_ROOT}/bin/statusline.py"
  }
}
```

## Configuration

Create `.claude/statusbar.json` in any project to customize behavior (walks up from the current directory, same as the speckit lookup below):

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `context_position` | `"end"` \| `"front"` | `"end"` | Where the context bar appears |
| `show_last_command` | `boolean` | `false` | Show last slash command used |

## Spec-kit integration

The status line detects [GitHub spec-kit](https://github.com/github/spec-kit) state from `specs/NNN-slug/`:

- **Active feature**: prefers a `specs/NNN-slug/` ancestor of the current directory, else the highest-numbered feature under `specs/` at the repo root (matching spec-kit's own fallback when not on a feature branch)
- **Step**: inferred from which artifact exists — `spec.md` → `specify`, `plan.md` → `plan`, `tasks.md` → `tasks` — overridden by the most recent `/speckit.*` slash command from the transcript, if any
- **Progress**: once `tasks.md` exists, a progress bar reflects the fraction of `- [x]` checked tasks

```
006-user-onboarding-flow · tasks · [██████████] 100%
```

## Requirements

- Python 3.11+ (via `uv run --script`)
- Claude Code v2.x with plugin support

## License

MIT
