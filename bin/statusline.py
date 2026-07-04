#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Claude Code statusline.

Reads a JSON payload from stdin (Claude Code's statusLine hook protocol) and writes
a formatted statusline string to stdout.

Layout (position=end, default):
  <dim>model</dim> │ <bold>task</bold>|<dim>speckit state</dim> │ <dim>dirname</dim> <ctx-bar>

Layout (position=front):
  <dim>model</dim><ctx-bar> │ <bold>task</bold>|<dim>speckit state</dim> │ <dim>dirname</dim>
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def read_project_config(cwd: str) -> dict:
    """Walk up from cwd looking for .claude/statusbar.json."""
    home = Path.home()
    current = Path(cwd).resolve()
    for _ in range(10):
        candidate = current / ".claude" / "statusbar.json"
        if candidate.exists():
            try:
                return json.loads(candidate.read_text()) or {}
            except Exception:
                return {}
        parent = current.parent
        if parent == current or current == home:
            break
        current = parent
    return {}


def get_config_value(cfg: dict, key_path: str):
    """Look up a dotted key path in a config dict (supports nested or flat keys)."""
    if not cfg:
        return None
    if key_path in cfg:
        return cfg[key_path]
    cur = cfg
    for part in key_path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


# ---------------------------------------------------------------------------
# Transcript reader (last slash command)
# ---------------------------------------------------------------------------

def read_last_slash_command(transcript_path: str | None) -> str | None:
    """Return the most recently invoked slash command name from a JSONL transcript."""
    if not transcript_path:
        return None
    try:
        p = Path(transcript_path)
        if not p.exists():
            return None
        size = p.stat().st_size
        MAX = 256 * 1024
        start = max(0, size - MAX)
        with open(p, "rb") as f:
            f.seek(start)
            content = f.read().decode("utf-8", errors="replace")
    except Exception:
        return None

    TAG_CLOSE = "</command-name>"
    TAG_OPEN = "<command-name>"
    idx = content.rfind(TAG_CLOSE)
    if idx < 0:
        return None
    open_idx = content.rfind(TAG_OPEN, 0, idx)
    if open_idx < 0:
        return None
    name = content[open_idx + len(TAG_OPEN) : idx].strip()
    if name.startswith("/"):
        name = name[1:]
    if not name or re.search(r'[\s\\"<>]', name) or len(name) > 80:
        return None
    return name


# ---------------------------------------------------------------------------
# speckit feature dir + state
# ---------------------------------------------------------------------------

def find_speckit_feature_dir(cwd: str) -> Path | None:
    """Locate the active speckit feature dir (specs/NNN-slug/).

    Prefers an ancestor of cwd (covers being cd'ed into or having a spec dir
    open directly), since the current git branch often isn't the feature
    branch (e.g. still on main). Falls back to the highest-numbered feature
    under specs/ at the repo root, matching speckit's own branch-less fallback.
    """
    home = Path.home()
    start = Path(cwd).resolve()

    for p in [start, *start.parents]:
        if p.parent.name == "specs" and re.match(r"^\d{3}-", p.name):
            return p
        if p == home:
            break

    current = start
    for _ in range(10):
        specs_dir = current / "specs"
        if specs_dir.is_dir():
            best, best_num = None, -1
            for d in specs_dir.iterdir():
                m = d.is_dir() and re.match(r"^(\d{3})-", d.name)
                if m and int(m.group(1)) > best_num:
                    best_num, best = int(m.group(1)), d
            return best
        parent = current.parent
        if parent == current or current == home:
            break
        current = parent
    return None


def read_speckit_state(cwd: str, transcript_path: str | None) -> dict | None:
    """Infer the current speckit step from feature-dir artifacts and tasks.md checkboxes."""
    feature_dir = find_speckit_feature_dir(cwd)
    if feature_dir is None:
        return None

    state: dict = {"slug": feature_dir.name}

    tasks_path = feature_dir / "tasks.md"
    if tasks_path.exists():
        state["artifact_step"] = "tasks"
        try:
            content = tasks_path.read_text()
            total = len(re.findall(r"^- \[[ xX]\]", content, re.M))
            done = len(re.findall(r"^- \[[xX]\]", content, re.M))
            if total:
                state["percent"] = round(done / total * 100)
        except Exception:
            pass
    elif (feature_dir / "plan.md").exists():
        state["artifact_step"] = "plan"
    elif (feature_dir / "spec.md").exists():
        state["artifact_step"] = "specify"

    last_cmd = read_last_slash_command(transcript_path)
    if last_cmd and last_cmd.startswith("speckit."):
        state["last_command"] = last_cmd[len("speckit."):]

    return state


def format_speckit_state(s: dict) -> str:
    """Format a speckit state dict: slug · step/last-command · progress bar."""
    parts = [s["slug"]]
    label = s.get("last_command") or s.get("artifact_step")
    if label:
        parts.append(label)
    if s.get("percent") is not None:
        bar = render_progress_bar(s["percent"])
        if bar:
            parts.append(bar)
    return " · ".join(parts)


def render_progress_bar(percent) -> str:
    """Render a 10-segment progress bar: [█████░░░░░] 50%"""
    if percent is None:
        return ""
    try:
        pct = max(0, min(100, int(percent)))
    except (ValueError, TypeError):
        return ""
    bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
    return f"[{bar}] {pct}%"


# ---------------------------------------------------------------------------
# Layout composer
# ---------------------------------------------------------------------------

DIM = "\x1b[2m"
BOLD = "\x1b[1m"
RESET = "\x1b[0m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
ORANGE = "\x1b[38;5;208m"
RED = "\x1b[31m"
BLINK_RED = "\x1b[5;31m"


def render_limit_meter(label: str, pct) -> str:
    """Render a compact 5-segment usage-limit meter: 5h ██░░░ 34%"""
    if pct is None:
        return ""
    try:
        pct = max(0, min(100, round(float(pct))))
    except (ValueError, TypeError):
        return ""
    filled = pct * 5 // 100
    bar = "█" * filled + "░" * (5 - filled)
    if pct < 50:
        color = GREEN
    elif pct < 75:
        color = YELLOW
    elif pct < 90:
        color = ORANGE
    else:
        color = RED
    return f" {DIM}{label}{RESET} {color}{bar} {pct}%{RESET}"


def format_reset_time(ts) -> str:
    """Format an epoch reset timestamp compactly: '3pm' today, else 'Tue 3pm'."""
    try:
        dt = datetime.fromtimestamp(int(ts))
    except (ValueError, TypeError, OSError, OverflowError):
        return ""
    t = dt.strftime("%-I:%M%p").lower().replace(":00", "")
    if dt.date() == datetime.now().date():
        return t
    return f"{dt.strftime('%a')} {t}"


def compose_statusline(
    *,
    model: str,
    ctx: str,
    middle: str | None,
    dirname: str,
    last_cmd_suffix: str = "",
    position: str = "end",
) -> str:
    model_seg = f"{DIM}{model}{RESET}"
    dir_seg = f"{DIM}{dirname}{RESET}"
    pos = "front" if position == "front" else "end"

    if pos == "front":
        if middle:
            return f"{model_seg}{ctx} │ {middle} │ {dir_seg}{last_cmd_suffix}"
        return f"{model_seg}{ctx} │ {dir_seg}{last_cmd_suffix}"
    # default: end
    if ctx:
        ctx = f" {DIM}│{RESET}{ctx}"
    if middle:
        return f"{model_seg} │ {middle} │ {dir_seg}{ctx}{last_cmd_suffix}"
    return f"{model_seg} │ {dir_seg}{ctx}{last_cmd_suffix}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return

    model = (data.get("model") or {}).get("display_name") or "Claude"
    workspace = data.get("workspace") or {}
    cwd = workspace.get("current_dir") or os.getcwd()
    session = data.get("session_id") or ""
    ctx_win = data.get("context_window") or {}
    remaining = ctx_win.get("remaining_percentage")
    total_ctx = ctx_win.get("total_tokens") or 1_000_000

    # --- Context bar --------------------------------------------------------
    ctx = ""
    if remaining is not None:
        # Claude reserves a buffer for autocompact (~16.5% by default).
        # CLAUDE_CODE_AUTO_COMPACT_WINDOW lets users override it as a token count.
        acw_env = int(os.environ.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW") or "0")
        if acw_env > 0:
            buffer_pct = min(100.0, max(0.0, (1 - acw_env / total_ctx) * 100))
        else:
            buffer_pct = 16.5

        usable_remaining = max(0.0, (remaining - buffer_pct) / (100 - buffer_pct) * 100)
        used = max(0, min(100, round(100 - usable_remaining)))

        # Write bridge file for any PostToolUse context monitor
        if session and "/" not in session and "\\" not in session and ".." not in session:
            try:
                bridge = Path("/tmp") / f"claude-ctx-{session}.json"
                bridge.write_text(json.dumps({
                    "session_id": session,
                    "remaining_percentage": remaining,
                    "used_pct": round(100 - remaining),
                    "timestamp": int(time.time()),
                }))
            except Exception:
                pass

        bar = "█" * (used // 10) + "░" * (10 - used // 10)
        if used < 50:
            ctx = f" {GREEN}{bar} {used}%{RESET}"
        elif used < 65:
            ctx = f" {YELLOW}{bar} {used}%{RESET}"
        elif used < 80:
            ctx = f" {ORANGE}{bar} {used}%{RESET}"
        else:
            ctx = f" {BLINK_RED}💀 {bar} {used}%{RESET}"

    # --- Session (5h) and weekly usage-limit meters (rendered on their own row)
    # rate_limits appears for Claude.ai Pro/Max subscribers after the first
    # API response; each window may be independently absent.
    rate_limits = data.get("rate_limits") or {}
    limits = ""
    resets: list[str] = []
    for label, key in (("5h", "five_hour"), ("wk", "seven_day")):
        window = rate_limits.get(key) or {}
        limits += render_limit_meter(label, window.get("used_percentage"))
        reset = format_reset_time(window.get("resets_at"))
        if reset:
            resets.append(f"{label} {reset}")

    limits_line = limits.strip()
    if resets:
        sep = f" {DIM}│{RESET} " if limits_line else ""
        limits_line += f"{sep}{DIM}↻ {' · '.join(resets)}{RESET}"

    # --- Active todo task ---------------------------------------------------
    task = ""
    claude_dir = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    todos_dir = Path(claude_dir) / "todos"
    if session and todos_dir.exists():
        try:
            latest: Path | None = None
            latest_mtime: float | None = None
            for entry in todos_dir.iterdir():
                n = entry.name
                if not (n.startswith(session) and "-agent-" in n and n.endswith(".json")):
                    continue
                mt = entry.stat().st_mtime
                if latest_mtime is None or mt > latest_mtime:
                    latest, latest_mtime = entry, mt
            if latest:
                todos = json.loads(latest.read_text())
                in_prog = next((t for t in todos if t.get("status") == "in_progress"), None)
                if in_prog:
                    # activeForm is TodoWrite's present-continuous label; fall back to content
                    task = in_prog.get("activeForm") or in_prog.get("content") or ""
        except Exception:
            pass

    # --- speckit feature state (shown when no active todo) ------------------
    state_str = ""
    if not task:
        speckit_state = read_speckit_state(cwd, data.get("transcript_path"))
        if speckit_state:
            state_str = format_speckit_state(speckit_state)

    # --- Config (context position, last slash command) ----------------------
    last_cmd_suffix = ""
    position = "end"
    try:
        cfg = read_project_config(cwd)
        if get_config_value(cfg, "show_last_command") is True:
            last_cmd = read_last_slash_command(data.get("transcript_path"))
            if last_cmd:
                last_cmd_suffix = f" │ {DIM}last: /{last_cmd}{RESET}"
        cfg_pos = get_config_value(cfg, "context_position")
        if cfg_pos is not None:
            position = cfg_pos
    except Exception:
        pass

    # --- Compose ------------------------------------------------------------
    dirname = Path(cwd).name

    if task:
        middle: str | None = f"{BOLD}{task}{RESET}"
    elif state_str:
        middle = f"{DIM}{state_str}{RESET}"
    else:
        middle = None

    output = compose_statusline(
        model=model,
        ctx=ctx,
        middle=middle,
        dirname=dirname,
        last_cmd_suffix=last_cmd_suffix,
        position=position,
    )
    if limits_line:
        output += f"\n{limits_line}"

    sys.stdout.write(output)


if __name__ == "__main__":
    main()
