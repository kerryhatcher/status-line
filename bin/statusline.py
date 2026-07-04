#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Claude Code statusline — ported from gsd-statusline.js (open-gsd/gsd-core next branch).

Reads a JSON payload from stdin (Claude Code's statusLine hook protocol) and writes
a formatted statusline string to stdout. All GSD-specific items (update notices,
stale-hooks warnings) have been removed; everything else is preserved exactly.

Layout (position=end, default):
  <dim>model</dim> │ <bold>task</bold>|<dim>state</dim> │ <dim>dirname</dim> <ctx-bar>

Layout (position=front):
  <dim>model</dim><ctx-bar> │ <bold>task</bold>|<dim>state</dim> │ <dim>dirname</dim>
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
    """Walk up from cwd looking for .planning/config.json."""
    home = Path.home()
    current = Path(cwd).resolve()
    for _ in range(10):
        candidate = current / ".planning" / "config.json"
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
# .planning/STATE.md reader + parser
# ---------------------------------------------------------------------------

def read_project_state(cwd: str) -> dict | None:
    """Walk up from cwd looking for .planning/STATE.md."""
    home = Path.home()
    current = Path(cwd).resolve()
    for _ in range(10):
        candidate = current / ".planning" / "STATE.md"
        if candidate.exists():
            try:
                return parse_state_md(candidate.read_text())
            except Exception:
                return None
        parent = current.parent
        if parent == current or current == home:
            break
        current = parent
    return None


def parse_state_md(content: str) -> dict:
    """Parse STATE.md frontmatter and Phase body line into a state dict."""
    state: dict = {}

    fm_match = re.match(r"^---\n([\s\S]*?)\n---", content)
    if fm_match:
        fm = fm_match.group(1)

        # Scalar fields
        for line in fm.split("\n"):
            m = re.match(r"^(\w+):\s*(.+)", line)
            if not m:
                continue
            key, val = m.group(1), m.group(2).strip().strip("\"'")
            if key == "status":
                state["status"] = None if val == "null" else val
            elif key == "milestone":
                state["milestone"] = None if val == "null" else val
            elif key == "milestone_name":
                state["milestone_name"] = None if val == "null" else val
            elif key == "active_phase":
                state["active_phase"] = None if val in ("null", "") else val
            elif key == "next_action":
                state["next_action"] = None if val in ("null", "") else val

        # next_phases: flow [a, b] or block list
        np_flow = re.search(r"^next_phases:\s*\[([^\]]*)\]", fm, re.M)
        if np_flow:
            items = [s.strip().strip("\"'") for s in np_flow.group(1).split(",") if s.strip()]
            state["next_phases"] = items or None
        else:
            np_block = re.search(r"^next_phases:\s*\n((?:[ \t]*-[ \t]*[^\n]+\n?)*)", fm, re.M)
            if np_block:
                items = []
                for line in np_block.group(1).split("\n"):
                    bm = re.match(r"^[ \t]*-[ \t]*(.+)$", line)
                    if bm:
                        items.append(bm.group(1).strip().strip("\"'"))
                state["next_phases"] = [i for i in items if i] or None

        # progress: nested block
        prog = re.search(r"^progress:\s*\n((?:[ \t]+\w+:.+\n?)+)", fm, re.M)
        if prog:
            pb = prog.group(1)
            for field, key in [
                (r"completed_phases", "completed_phases"),
                (r"total_phases", "total_phases"),
                (r"percent", "percent"),
            ]:
                m2 = re.search(rf"^[ \t]+{field}:\s*(\d+)", pb, re.M)
                if m2:
                    state[key] = m2.group(1)

    # Phase: N of M (name)
    phase_m = re.search(r"^Phase:\s*(\d+)\s+of\s+(\d+)(?:\s+\(([^)]+)\))?", content, re.M)
    if phase_m:
        state["phase_num"] = phase_m.group(1)
        state["phase_total"] = phase_m.group(2)
        state["phase_name"] = phase_m.group(3)  # may be None

    # Fallback: Status: in body when frontmatter absent
    if not state.get("status"):
        body_s = re.search(r"^Status:\s*(.+)", content, re.M)
        if body_s:
            raw = body_s.group(1).strip().lower()
            if "ready to plan" in raw or "planning" in raw:
                state["status"] = "planning"
            elif "execut" in raw:
                state["status"] = "executing"
            elif "complet" in raw or "archived" in raw:
                state["status"] = "complete"

    return state


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


def format_state(s: dict) -> str:
    """Format a state dict into a human-readable statusline segment."""
    parts: list[str] = []

    # Milestone segment
    if s.get("milestone") or s.get("milestone_name"):
        ver = s.get("milestone") or ""
        name = s.get("milestone_name") or ""
        if name == "milestone":
            name = ""
        bar = render_progress_bar(s.get("percent"))
        pieces = [p for p in [ver, name, bar] if p]
        if pieces:
            parts.append(" ".join(pieces))

    phases_str = "/".join(s["next_phases"]) if s.get("next_phases") else None

    if s.get("active_phase"):
        stage = s.get("status") or ""
        seg = f"Phase {s['active_phase']} {stage}".strip() if stage else f"Phase {s['active_phase']}"
        parts.append(seg)
    elif s.get("next_action") and phases_str:
        parts.append(f"next {s['next_action']} {phases_str}")
    elif int(s.get("percent") or 0) == 100 or (
        s.get("completed_phases")
        and s.get("total_phases")
        and s["completed_phases"] == s["total_phases"]
    ):
        parts.append("milestone complete")
    else:
        if s.get("status"):
            parts.append(s["status"])
        if s.get("phase_num") and s.get("phase_total"):
            if s.get("phase_name"):
                parts.append(f"{s['phase_name']} ({s['phase_num']}/{s['phase_total']})")
            else:
                parts.append(f"ph {s['phase_num']}/{s['phase_total']}")

    return " · ".join(parts)


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
                    # activeForm is GSD's display label; fall back to content
                    task = in_prog.get("activeForm") or in_prog.get("content") or ""
        except Exception:
            pass

    # --- Project state from .planning/STATE.md, falling back to speckit
    # (shown when no active todo) ---------------------------------------
    state_str = ""
    if not task:
        state = read_project_state(cwd)
        if state:
            state_str = format_state(state)
        else:
            speckit_state = read_speckit_state(cwd, data.get("transcript_path"))
            if speckit_state:
                state_str = format_speckit_state(speckit_state)

    # --- Config (context position, last slash command) ----------------------
    last_cmd_suffix = ""
    position = "end"
    try:
        cfg = read_project_config(cwd)
        if get_config_value(cfg, "statusline.show_last_command") is True:
            last_cmd = read_last_slash_command(data.get("transcript_path"))
            if last_cmd:
                last_cmd_suffix = f" │ {DIM}last: /{last_cmd}{RESET}"
        cfg_pos = get_config_value(cfg, "statusline.context_position")
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
