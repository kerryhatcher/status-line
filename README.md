# Status Line for Claude Code

A rich terminal status line showing **model**, **context window usage**, **active todo tasks**, **spec-kit feature state**, and **rate limit meters**.

## Layout

```
<dim>sonnet</dim> │ <bold>Implement auth middleware</bold> │ <dim>my-app</dim>  ████░░░░░░ 62%
<dim>5h</dim> ██░░░ 34% <dim>wk</dim> ████░ 81% │ <dim>↻ 5h 3pm · wk Tue 3pm</dim>
```

Row 1 segments: `model` · `task / speckit state` · `directory` · `context bar`

Row 2 (shown only when rate-limit data is available): `5h`/`wk` usage meters and reset times, kept on their own line so they don't crowd the primary row.

Position defaults to **end** (right-aligned). Toggle with `.claude/statusbar.yaml`:
```yaml
context_position: front
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

Create `.claude/statusbar.yaml` in any project to customize behavior (walks up from the current directory, same as the speckit lookup below):

```yaml
context_position: front
show_last_command: true
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `context_position` | `"end"` \| `"front"` | `"end"` | Where the context bar appears |
| `show_last_command` | `boolean` | `false` | Show last slash command used |

## Spec-kit integration

The status line tracks the full [GitHub spec-kit](https://github.com/github/spec-kit) command chain for the active feature under `specs/NNN-slug/` and tells you exactly which `/speckit.*` command to run next — so you can walk away mid-feature and pick back up without reconstructing where you left off.

- **Active feature**: prefers a `specs/NNN-slug/` ancestor of the current directory, else the highest-numbered feature under `specs/` at the repo root (matching spec-kit's own fallback when not on a feature branch)
- **Chain enforced** (every step, none skipped): `constitution → specify → clarify → plan → checklist → tasks → analyze → implement → converge`
- **Next command**: the first unmet step in that chain, checked in order:

  | Step | Detected via |
  |---|---|
  | `constitution` | `.specify/memory/constitution.md` exists at the repo root (this one gates the whole project, not just the current feature) |
  | `specify` | `spec.md` exists |
  | `clarify` | `spec.md` contains a `## Clarifications` section |
  | `plan` | `plan.md` exists |
  | `checklist` | `checklists/` contains at least one file |
  | `tasks` | `tasks.md` exists |
  | `analyze` | a `.speckit-log.yaml` marker in the feature dir (see below) |
  | `implement` | `tasks.md` checkbox completion < 100% |
  | `converge` | a `## Phase N: Convergence` heading has been appended to `tasks.md` |

  Once every step is satisfied, the status line shows `done`.
- **Progress**: once `tasks.md` exists, a progress bar reflects the fraction of `- [x]` checked tasks.
- **The `analyze` marker**: `/speckit.analyze` is read-only and leaves no file behind, so it can't be detected from artifacts like the other steps. The status line writes a small `specs/NNN-slug/.speckit-log.yaml` (`{analyzed: true}`) the first time it sees `/speckit.analyze` as the last command in your transcript, so "next" correctly skips past it even in a brand-new session. Add `**/.speckit-log.yaml` to your project's `.gitignore` — it's a local Claude Code cache, not a spec-kit artifact meant to be shared.
- **`taskstoissues` is intentionally excluded** from the chain — not everyone files tasks as GitHub issues.

```
009-notification-preferences · next: clarify
006-user-onboarding-flow · next: converge · [██████████] 100%
003-search-autocomplete · next: implement · [████████░░] 83%
011-dashboard-widgets · done · [██████████] 100%
```

## Requirements

- Python 3.11+ (via `uv run --script`)
- Claude Code v2.x with plugin support

## License

MIT
