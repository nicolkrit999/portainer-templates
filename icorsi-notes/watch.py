#!/usr/bin/env python3
"""
icorsi-notes - watch _icorsi/ folders and propose study-note additions via Claude Code.

Self-scheduling daemon (mirroring icorsi-sync patterns):
  - rclone-mounts ownCloud over WebDAV at /oc
  - fingerprints each watched course's _icorsi/ folder
  - on change: invokes `claude -p` headlessly to generate proposals into notes/_suggested/
  - active-hours window + /data/PAUSE file prevent running during the user's working hours
  - graceful window stop: SIGTERM at (window_end - WINDOW_GRACE_MINUTES), SIGKILL at window_end
  - ANTHROPIC_API_KEY is never set (startup assertion); cost circuit-breaker halts on any spend
  - limit-hit backoff: no API fallback, no billing

The sole user-facing control surface is /data/courses.json (edit it, no rebuild needed).
"""

import datetime
import hashlib
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

# ─── env helpers ────────────────────────────────────────────────────────────


def env(key, default=None, required=False):
    v = os.environ.get(key, default)
    if required and not v:
        sys.exit(f"FATAL: required env var {key} is not set")
    return v


def env_bool(key, default=False):
    return str(os.environ.get(key, str(default))).strip().lower() in (
        "1", "true", "yes", "on",
    )


# ─── configuration ──────────────────────────────────────────────────────────

DRY_RUN = env_bool("DRY_RUN", False)

DAV_URL = (env("OWNCLOUD_WEBDAV_URL", "", required=not DRY_RUN) or "").rstrip("/")
DAV_USER = env("OWNCLOUD_USER", "", required=not DRY_RUN)
DAV_PASS = env("OWNCLOUD_APP_PASSWORD", "", required=not DRY_RUN)
DAV_HOST_HEADER = env("OWNCLOUD_HOST_HEADER", "")
BASE_PATH = env("OWNCLOUD_BASE_PATH", "").strip("/")

MOUNT_POINT = "/oc"
DATA_DIR = env("DATA_DIR", "/data")
STATE_FILE = os.path.join(DATA_DIR, "state.json")
PAUSE_FILE = os.path.join(DATA_DIR, "PAUSE")
HALT_FILE = os.path.join(DATA_DIR, "HALT")

INTERVAL = int(env("NOTES_INTERVAL_SECONDS", "21600"))
LIMIT_BACKOFF = int(env("LIMIT_BACKOFF_SECONDS", "3600"))
RUN_ON_START = env_bool("RUN_ON_START", True)
LOOP = INTERVAL > 0
ACTIVE_HOURS_RAW = env("ACTIVE_HOURS", "00:00-03:00").strip()  # empty = always active
DISCORD_WEBHOOK = env("DISCORD_WEBHOOK_URL", "")

COST_CIRCUIT_BREAKER = env_bool("COST_CIRCUIT_BREAKER", True)
MIN_TASK_WINDOW = int(env("MIN_TASK_WINDOW_SECONDS", "1800"))
WINDOW_GRACE_MINUTES = int(env("WINDOW_GRACE_MINUTES", "10"))
STALL_THRESHOLD = int(env("STALL_THRESHOLD", "4"))

PROMPT_FILE = "/app/prompt.md"
CLAUDE_MODEL = env("CLAUDE_MODEL", "")

# Billing-capable vars: daemon must NEVER have these set (startup assertion)
_BILLING_ENV_VARS = {
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
}

# Strip credentials from the subprocess env
_STRIP_FROM_CLAUDE_ENV = _BILLING_ENV_VARS | {
    "OWNCLOUD_APP_PASSWORD",   # WebDAV secret - rclone mount handles auth
    "DISCORD_WEBHOOK_URL",     # notification token - watch.py owns this
}

# ─── logging ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("icorsi-notes")

# ─── billing-safety assertion ────────────────────────────────────────────────


def assert_no_billing_credentials():
    """
    Fatal exit if any billing-capable credential is present in the environment.
    This daemon uses subscription OAuth only - no API key should ever be set.
    Without a billing credential, exhausting the Max plan is a no-op (limit backoff),
    not an opportunity for the account to switch to pay-as-you-go spend.
    """
    found = [k for k in _BILLING_ENV_VARS if os.environ.get(k)]
    if found:
        sys.exit(
            f"FATAL: billing-capable env var(s) detected: {', '.join(found)}. "
            "This daemon uses subscription OAuth only (no ANTHROPIC_API_KEY). "
            "Refusing to start to prevent accidental API spend."
        )
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
    if base_url and "anthropic.com" not in base_url:
        sys.exit(
            f"FATAL: ANTHROPIC_BASE_URL={base_url!r} does not point to the official "
            "Anthropic endpoint. Refusing to start."
        )


# ─── state (atomic JSON, icorsi-sync pattern) ────────────────────────────────


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)


# ─── courses.json ─────────────────────────────────────────────────────────────


def load_courses():
    path = "/data/courses.json"
    if not os.path.exists(path):
        log.warning(
            "No /data/courses.json found; nothing to do. Copy courses.example.json to get started."
        )
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception as e:
        log.error("Failed to parse /data/courses.json: %s", e)
        return {}
    return {k: v for k, v in data.items() if not k.startswith("_")}


# ─── active-hours guard ──────────────────────────────────────────────────────


def parse_active_hours(raw):
    """Return (sh, sm, eh, em) or None (= always active)."""
    if not raw:
        return None
    m = re.match(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$", raw)
    if not m:
        log.warning("ACTIVE_HOURS %r not understood; treating as always active", raw)
        return None
    return int(m[1]), int(m[2]), int(m[3]), int(m[4])


def _cur_minutes():
    n = datetime.datetime.now()
    return n.hour * 60 + n.minute + n.second / 60.0


def is_active_now(parsed):
    """True if the current local wall-clock time falls within the window."""
    if parsed is None:
        return True
    sh, sm, eh, em = parsed
    cur = _cur_minutes()
    start = sh * 60 + sm
    end = eh * 60 + em
    if start <= end:
        return start <= cur < end
    # Overnight window e.g. 23:00-06:00
    return cur >= start or cur < end


def window_end_seconds(parsed):
    """
    Seconds from now until the active-window END.
    Returns 0 if currently outside the window.
    Returns a large sentinel (999999) if ACTIVE_HOURS is empty (always active).
    """
    if parsed is None:
        return 999999
    if not is_active_now(parsed):
        return 0
    sh, sm, eh, em = parsed
    cur = _cur_minutes()
    start = sh * 60 + sm
    end = eh * 60 + em
    if start <= end:
        mins_left = end - cur
    else:
        # Overnight: cur is either evening (>= start) or morning (< end)
        if cur >= start:
            mins_left = (24 * 60 - cur) + end
        else:
            mins_left = end - cur
    return max(0, int(mins_left * 60))



def minutes_until_active(parsed):
    """Return minutes to sleep until the active window opens (approx)."""
    if parsed is None or is_active_now(parsed):
        return 0
    sh, sm, _eh, _em = parsed
    cur = _cur_minutes()
    start = sh * 60 + sm
    delta = start - cur if start > cur else (24 * 60 - cur + start)
    return delta


# ─── fingerprint ─────────────────────────────────────────────────────────────


def fingerprint_dir(path):
    """Walk a directory and return a stable SHA-256 fingerprint of (relpath, size) pairs."""
    p = Path(path)
    if not p.is_dir():
        return ""
    entries = []
    for f in sorted(p.rglob("*")):
        if f.is_file():
            try:
                entries.append(f"{f.relative_to(p)}:{f.stat().st_size}")
            except Exception:
                pass
    return hashlib.sha256("\n".join(entries).encode()).hexdigest()


def find_icorsi_dirs(course_path):
    """
    Find all _icorsi/ directories under a course folder.
    Supports both flat (<course>/_icorsi/) and per-semester (<course>/<sem>/_icorsi/) layouts.
    Returns list of (icorsi_path, cwd_path) where cwd_path is the parent to run claude in.
    """
    p = Path(course_path)
    if not p.is_dir():
        return []

    results = []

    # Flat layout: <course>/_icorsi/
    direct = p / "_icorsi"
    if direct.is_dir():
        results.append((direct, p))
        return results  # flat takes precedence; don't also search subdirs

    # Per-semester: <course>/<child>/_icorsi/
    try:
        children = sorted(p.iterdir())
    except PermissionError:
        return []
    for child in children:
        if child.is_dir() and not child.name.startswith("."):
            sub = child / "_icorsi"
            if sub.is_dir():
                results.append((sub, child))

    return results


# ─── Discord ──────────────────────────────────────────────────────────────────


def notify(msg):
    if not DISCORD_WEBHOOK:
        return
    import urllib.request

    payload = json.dumps({"username": "icorsi-notes", "content": msg[:2000]}).encode()
    req = urllib.request.Request(
        DISCORD_WEBHOOK,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "icorsi-notes/1.0"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log.warning("Discord notify failed: %s", e)


# ─── rclone mount ─────────────────────────────────────────────────────────────


def build_rclone_url():
    """
    If OWNCLOUD_HOST_HEADER is set, entrypoint.sh added it to /etc/hosts pointing
    to the real ownCloud container IP. We rewrite the WebDAV URL to use that trusted
    domain as the HTTP Host header (ownCloud rejects the raw container hostname).
    """
    if not DAV_HOST_HEADER:
        return DAV_URL
    m = re.match(r"(https?://)([^/:]+)(:\d+)?(.*)", DAV_URL)
    if not m:
        return DAV_URL
    scheme, _host, port, path = m.groups()
    rewritten = f"{scheme}{DAV_HOST_HEADER}{port or ''}{path}"
    log.info("rclone URL: %s -> %s", DAV_URL, rewritten)
    return rewritten


def setup_mount():
    """Write rclone config and mount ownCloud at MOUNT_POINT. Blocks until ready."""
    if DRY_RUN and not DAV_URL:
        log.info("[DRY_RUN] No DAV_URL; skipping rclone mount")
        return

    rclone_url = build_rclone_url()

    # Obscure the password (rclone requires its own encoding for config files)
    try:
        obscured = subprocess.check_output(
            ["rclone", "obscure", DAV_PASS], text=True, timeout=10
        ).strip()
    except Exception as e:
        log.error("rclone obscure failed: %s", e)
        sys.exit(1)

    cfg = (
        f"[owncloud]\n"
        f"type = webdav\n"
        f"url = {rclone_url}\n"
        f"vendor = owncloud\n"
        f"user = {DAV_USER}\n"
        f"pass = {obscured}\n"
    )
    cfg_path = "/tmp/rclone.conf"
    with open(cfg_path, "w") as f:
        f.write(cfg)
    os.chmod(cfg_path, 0o600)

    os.makedirs(MOUNT_POINT, exist_ok=True)

    # rclone mount <remote>:<path> <mountpoint> [flags]
    # NOTE: requires cap_add SYS_ADMIN + /dev/fuse device in compose
    cmd = [
        "rclone", "mount", f"owncloud:{BASE_PATH}", MOUNT_POINT,
        "--config", cfg_path,
        "--vfs-cache-mode", "writes",
        "--dir-cache-time", "2m",
        "--allow-non-empty",
        "--daemon",
        "--log-file", "/tmp/rclone.log",
        "--log-level", "INFO",
    ]
    log.info("Starting rclone mount …")
    rc = subprocess.run(cmd).returncode
    if rc != 0:
        log.error("rclone mount failed (rc=%d) - check /tmp/rclone.log", rc)
        sys.exit(1)

    # Wait up to 60 s for the mount to become usable
    for i in range(60):
        try:
            if os.path.isdir(MOUNT_POINT) and os.listdir(MOUNT_POINT):
                log.info("rclone mount ready at %s", MOUNT_POINT)
                return
        except OSError:
            pass
        time.sleep(1)
    log.warning("rclone mount may not be populated yet; continuing anyway")


# ─── rate-limit detection ─────────────────────────────────────────────────────

_LIMIT_KEYWORDS = (
    "rate limit", "usage limit", "message limit", "quota exceeded",
    "limit reached", "try again later", "plan limit",
)


def _is_limit_error(text):
    t = text.lower()
    return any(k in t for k in _LIMIT_KEYWORDS)


# ─── suggestions STATUS parser ────────────────────────────────────────────────


def parse_suggestions_status(cwd, notes_dir):
    """
    Read STATUS and Remaining from <cwd>/<notes_dir>/_suggested/_notes.md.

    Returns ("complete" | "partial" | "unknown", remaining_count_or_-1).
    "unknown" (file missing / no STATUS line) is treated as "partial" by callers -
    the conservative choice that keeps retrying rather than falsely marking done.

    The STATUS block written by claude looks like:
        ## Coverage status
        STATUS: COMPLETE        # or PARTIAL
        Authored: Topic A, Topic B
        Remaining: none         # or "Topic C, Topic D"
        Continuation: yes|no
    """
    notes_path = Path(cwd) / notes_dir / "_suggested" / "_notes.md"
    if not notes_path.exists():
        return "unknown", -1
    try:
        text = notes_path.read_text(errors="replace")
    except Exception as e:
        log.warning("Cannot read suggestions status from %s: %s", notes_path, e)
        return "unknown", -1

    # Use the LAST STATUS: line (claude rewrites the block; last wins)
    status = "partial"
    for line in text.splitlines():
        m = re.match(r"^\s*STATUS:\s*(COMPLETE|PARTIAL)\b", line, re.IGNORECASE)
        if m:
            status = m.group(1).lower()

    # Parse Remaining count
    remaining = -1
    for line in text.splitlines():
        m = re.match(r"^\s*Remaining:\s*(.+)", line, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if val.lower() in ("none", "0", ""):
                remaining = 0
            else:
                remaining = len([t for t in re.split(r"[,;]+", val) if t.strip()])

    return status, remaining


# ─── Claude invocation ────────────────────────────────────────────────────────


def _read_file(path):
    try:
        with open(path) as f:
            return f.read()
    except Exception as e:
        log.error("Cannot read %s: %s", path, e)
        return ""


def run_claude(cwd, notes_dir, format_, time_budget_secs):
    """
    Invoke claude -p headlessly for one course directory with a graceful window stop.

    Returns (success, is_limit, window_cutoff, summary, cost_usd).

    time_budget_secs: seconds available before the active window ends.
      Soft deadline (SIGTERM) = time_budget - WINDOW_GRACE_MINUTES * 60
      Hard deadline (SIGKILL) = time_budget
      2 h ceiling applies independently.

    On a window-cutoff the on-disk _suggested/_notes.md is authoritative (incremental
    writes mean it reflects exactly what was finished before the kill).
    """
    prompt_template = _read_file(PROMPT_FILE)
    if not prompt_template:
        return False, False, False, "empty prompt", 0.0

    prompt = prompt_template.replace("<notes_dir>", notes_dir).replace("<format>", format_)

    if DRY_RUN:
        log.info(
            "[DRY_RUN] Would run claude -p in %s (notes_dir=%s, format=%s)",
            cwd, notes_dir, format_,
        )
        return True, False, False, "dry-run", 0.0

    cmd = [
        "claude", "-p", prompt,
        "--output-format", "json",
        # Explicit allowlist: limits claude to the tools cs-* agents actually need.
        # Keeps network tools (WebFetch, etc.) out of scope.
        "--allowedTools", "Read,Write,Bash,Grep,Glob,Agent,mcp__bgpt__search_papers",
    ]
    if CLAUDE_MODEL:
        cmd += ["--model", CLAUDE_MODEL]

    # Never expose billing credentials or infra secrets to the subprocess
    run_env = {k: v for k, v in os.environ.items() if k not in _STRIP_FROM_CLAUDE_ENV}

    # Time budgets - never exceed 2 h regardless of window
    hard_secs = min(7200, time_budget_secs)
    grace_secs = WINDOW_GRACE_MINUTES * 60
    soft_secs = max(60, hard_secs - grace_secs)

    log.info(
        "Running claude -p in %s (soft=%ds SIGTERM, hard=%ds SIGKILL) …",
        cwd, soft_secs, hard_secs,
    )

    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=run_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Drain pipes in background threads (avoids pipe-buffer deadlock on large output)
    stdout_buf, stderr_buf = [], []

    def _drain(pipe, buf):
        try:
            buf.append(pipe.read())
        except Exception:
            buf.append("")

    t_out = threading.Thread(target=_drain, args=(proc.stdout, stdout_buf), daemon=True)
    t_err = threading.Thread(target=_drain, args=(proc.stderr, stderr_buf), daemon=True)
    t_out.start()
    t_err.start()

    start = time.monotonic()
    sigterm_sent = False
    killed = False

    while proc.poll() is None:
        time.sleep(5)
        elapsed = time.monotonic() - start

        if not sigterm_sent and elapsed >= soft_secs:
            log.info(
                "Soft deadline reached (%.0fs elapsed), sending SIGTERM to claude in %s …",
                elapsed, cwd,
            )
            try:
                proc.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass
            sigterm_sent = True

        if elapsed >= hard_secs:
            log.warning(
                "Hard deadline reached (%.0fs elapsed), sending SIGKILL to claude in %s",
                elapsed, cwd,
            )
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            killed = True
            break

    # Wait for pipe readers to finish draining
    t_out.join(timeout=30)
    t_err.join(timeout=30)
    proc.wait()

    stdout = stdout_buf[0] if stdout_buf else ""
    stderr = stderr_buf[0] if stderr_buf else ""
    window_cutoff = sigterm_sent or killed

    if window_cutoff:
        # On-disk _suggested/_notes.md is authoritative - incremental writes mean it
        # reflects exactly what was finished before the signal.
        log.info("Window cutoff for %s - on-disk status is authoritative", cwd)
        return False, False, True, "window-cutoff", 0.0

    if proc.returncode != 0:
        combined = stdout + stderr
        if _is_limit_error(combined):
            log.warning("Rate/usage limit detected in %s", cwd)
            return False, True, False, combined, 0.0
        log.error("claude rc=%d in %s:\n%s", proc.returncode, cwd, stderr[:500])
        return False, False, False, combined, 0.0

    # Parse JSON envelope
    cost = 0.0
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        if _is_limit_error(stdout + stderr):
            return False, True, False, stdout, 0.0
        log.warning("Non-JSON output from claude in %s; assuming success", cwd)
        return True, False, False, stdout[:200], 0.0

    cost = float(data.get("total_cost_usd", 0) or 0)

    if data.get("is_error"):
        msg = str(data.get("error", data.get("result", stdout)))
        if _is_limit_error(msg):
            return False, True, False, msg, cost
        log.error("claude is_error in %s: %s", cwd, msg[:300])
        return False, False, False, msg, cost

    summary = str(data.get("result", "")).strip()
    log.info("claude success in %s: %s", cwd, summary[:200])
    return True, False, False, summary, cost


# ─── main pass ────────────────────────────────────────────────────────────────


def _course_label(key):
    """Human-readable course name from a state key (last two meaningful path segments)."""
    parts = [p for p in key.replace("\\", "/").split("/") if p and p != "_icorsi"]
    return "/".join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else key)


def run_once(state, active_hours):
    # ── HALT check ───────────────────────────────────────────────────────────
    # Written by the cost circuit-breaker when extra usage billing was detected.
    # Always removed at the start of the next run: the 5-hour subscription limit
    # resets well within 24 h, so a previous HALT is never still relevant. If extra
    # usage kicks in again this run, a new HALT will be written immediately.
    if os.path.exists(HALT_FILE):
        log.info("Removing HALT file from previous run and retrying.")
        try:
            os.remove(HALT_FILE)
        except Exception as e:
            log.error("Could not remove HALT file: %s", e)
            return state

    courses = load_courses()
    if not courses:
        return state

    pass_outcomes = []   # per-course result lines for the end-of-pass Discord summary
    limit_hit = False

    for folder, opts in courses.items():
        if limit_hit:
            break

        if opts is None:
            continue

        # ── guards: run before each course ───────────────────────────────────
        if os.path.exists(PAUSE_FILE):
            log.info("PAUSE file present - skipping remaining courses this pass")
            break

        if not is_active_now(active_hours):
            log.info(
                "Outside ACTIVE_HOURS (%s) - skipping remaining courses this pass",
                ACTIVE_HOURS_RAW,
            )
            break

        win_end_s = window_end_seconds(active_hours)
        if win_end_s < MIN_TASK_WINDOW:
            log.info(
                "Only %ds left in window (MIN_TASK_WINDOW=%ds) - "
                "stopping pass to preserve morning quota",
                win_end_s, MIN_TASK_WINDOW,
            )
            break

        # ── per-course config ─────────────────────────────────────────────────
        if isinstance(opts, dict):
            notes_dir = opts.get("notes_dir", "notes")
            format_ = opts.get("format", "typst")
        else:
            notes_dir = "notes"
            format_ = "typst"

        folder = folder.strip("/")
        course_path = Path(MOUNT_POINT) / folder

        if not course_path.is_dir():
            log.warning("Course path not found (not mounted yet?): %s", course_path)
            continue

        # ── find _icorsi/ directories ─────────────────────────────────────────
        icorsi_pairs = find_icorsi_dirs(course_path)
        if not icorsi_pairs:
            log.debug("No _icorsi/ found under %s; skipping", folder)
            continue

        for icorsi_dir, cwd in icorsi_pairs:
            key = str(icorsi_dir.relative_to(MOUNT_POINT))
            label = _course_label(key)

            fp = fingerprint_dir(icorsi_dir)
            prev = state.get(key, {})

            # Skip only if source is unchanged AND prior run completed fully
            if fp and fp == prev.get("fp") and prev.get("status") == "complete":
                log.debug("Unchanged and complete: %s - skipping", key)
                continue

            was_continuation = prev.get("status") == "partial"
            log.info(
                "Processing %s%s",
                key,
                " (continuing partial run)" if was_continuation else "",
            )

            # Snapshot _suggested/ before run for stall detection
            suggestions_fp_before = fingerprint_dir(Path(cwd) / notes_dir / "_suggested")

            # Re-check window immediately before spawning the subprocess
            win_end_s = window_end_seconds(active_hours)
            if win_end_s < MIN_TASK_WINDOW:
                log.info(
                    "Window shrank below MIN_TASK_WINDOW just before %s - stopping pass",
                    key,
                )
                break

            success, is_limit, window_cutoff, summary, cost = run_claude(
                cwd, notes_dir, format_, win_end_s
            )

            # ── cost circuit-breaker (layer 2 billing safety) ─────────────────
            # NOTE: total_cost_usd from claude -p reflects the dollar value of
            # tokens consumed against the Max subscription - it is non-zero for
            # every normal run, not just when extra-usage billing kicks in.
            # The check is therefore a false signal for Max plan users and should
            # be left disabled (COST_CIRCUIT_BREAKER=false). The real billing
            # guards are: (1) no ANTHROPIC_API_KEY in env (startup assertion
            # above), and (2) "extra usage" OFF on the Anthropic dashboard.
            if COST_CIRCUIT_BREAKER and cost > 0:
                msg = (
                    f"⛔ icorsi-notes: non-zero cost (${cost:.4f}) detected after {label}. "
                    "Writing /data/HALT to prevent further billing. "
                    "Disable 'extra usage' on your Claude account, then `rm /data/HALT` to resume."
                )
                log.error(msg)
                try:
                    with open(HALT_FILE, "w") as f:
                        f.write(f"cost={cost}\nwritten={datetime.datetime.now().isoformat()}\ncourse={label}\n")
                except Exception as e:
                    log.error("Could not write HALT file: %s", e)
                notify(msg)
                return state  # stop the entire pass immediately

            # ── read on-disk STATUS (always, even after success/cutoff) ────────
            disk_status, remaining = parse_suggestions_status(cwd, notes_dir)
            if disk_status == "unknown":
                log.warning(
                    "No STATUS marker in _suggested/_notes.md for %s; treating as partial",
                    key,
                )
                disk_status = "partial"

            # ── handle outcomes ───────────────────────────────────────────────
            if is_limit:
                limit_hit = True
                msg = (
                    f"⏸ icorsi-notes: Max plan limit hit during {label}. "
                    f"Sleeping {LIMIT_BACKOFF}s, then retrying."
                )
                log.info(msg)
                notify(msg)
                # Don't advance fingerprint; record partial so we resume next night
                state[key] = {
                    **prev,
                    "status": "partial",
                    "last_run": datetime.datetime.now().isoformat(),
                }
                save_state(state)
                time.sleep(LIMIT_BACKOFF)
                break

            if window_cutoff:
                remain_str = (
                    f" ({remaining} section(s) remain)" if remaining > 0 else ""
                )
                if was_continuation:
                    outcome = (
                        f"🔁 {label} - continued, interrupted at window end{remain_str}"
                    )
                else:
                    outcome = (
                        f"⏸ {label} - interrupted (stopped at window end){remain_str}; "
                        "resumes next run"
                    )
                log.info("Window cutoff for %s%s", key, remain_str)
                state[key] = {
                    **prev,
                    "status": "partial",
                    "last_run": datetime.datetime.now().isoformat(),
                }
                save_state(state)
                pass_outcomes.append(outcome)
                break  # stop the whole pass after a window cutoff

            if not success:
                outcome = f"⚠️ {label} - error (will retry next pass): {summary[:80]}"
                log.warning("Error for %s: %s", key, summary[:100])
                pass_outcomes.append(outcome)
                continue  # try the next course

            # ── completion vs partial ─────────────────────────────────────────
            if disk_status == "complete":
                state[key] = {
                    "fp": fp,
                    "status": "complete",
                    "last_run": datetime.datetime.now().isoformat(),
                    "stall_count": 0,
                }
                save_state(state)
                if was_continuation:
                    outcome = f"✅ {label} - completed (continuation; {summary})"
                else:
                    outcome = f"✅ {label} - completed ({summary})"
                pass_outcomes.append(outcome)

            else:
                # PARTIAL: check for stalls (no progress in _suggested/ despite a run)
                suggestions_fp_after = fingerprint_dir(
                    Path(cwd) / notes_dir / "_suggested"
                )
                made_progress = suggestions_fp_after != suggestions_fp_before
                stall_count = (0 if made_progress else prev.get("stall_count", 0) + 1)

                if not made_progress:
                    log.warning(
                        "No _suggested/ progress for %s (stall_count=%d/%d)",
                        key, stall_count, STALL_THRESHOLD,
                    )

                state[key] = {
                    **prev,
                    "status": "partial",
                    "last_run": datetime.datetime.now().isoformat(),
                    "stall_count": stall_count,
                }
                save_state(state)

                if stall_count >= STALL_THRESHOLD:
                    stall_msg = (
                        f"⛔ icorsi-notes: {label} stalled ({stall_count} consecutive runs "
                        "with no _suggested/ progress). Skipping until source changes. "
                        "Manual check recommended."
                    )
                    log.warning(stall_msg)
                    notify(stall_msg)
                    # Force-complete with current fp so the course is skipped;
                    # a source change will flip the fp and re-open it.
                    state[key]["fp"] = fp
                    state[key]["status"] = "complete"
                    save_state(state)
                    continue

                remain_str = (
                    f"{remaining} section(s) remain" if remaining >= 0 else "sections remain"
                )
                if was_continuation:
                    outcome = (
                        f"🔁 {label} - continued, still partial ({remain_str}; resumes next run)"
                    )
                else:
                    outcome = (
                        f"⏸ {label} - partial ({remain_str}; resumes next run)"
                    )
                pass_outcomes.append(outcome)

    # ── end-of-pass Discord summary ───────────────────────────────────────────
    if pass_outcomes:
        lines = "\n".join(f"  {o}" for o in pass_outcomes)
        notify(f"📝 icorsi-notes pass summary:\n{lines}")

    return state


# ─── entry point ──────────────────────────────────────────────────────────────


def main():
    # Layer 1 billing safety: structural check - refuses to start if any
    # billing-capable credential is present in the environment.
    assert_no_billing_credentials()

    log.info(
        "icorsi-notes starting  DRY_RUN=%s  INTERVAL=%ds  ACTIVE_HOURS=%r  "
        "MIN_TASK_WINDOW=%ds  WINDOW_GRACE=%dm  STALL_THRESHOLD=%d",
        DRY_RUN, INTERVAL, ACTIVE_HOURS_RAW,
        MIN_TASK_WINDOW, WINDOW_GRACE_MINUTES, STALL_THRESHOLD,
    )

    setup_mount()

    active_hours = parse_active_hours(ACTIVE_HOURS_RAW)
    state = load_state()
    first = True

    while True:
        if first and not RUN_ON_START:
            log.info("RUN_ON_START=false; sleeping %ds before first pass", INTERVAL)
        else:
            try:
                state = run_once(state, active_hours)
            except Exception as e:
                log.exception("Unexpected error in run_once: %s", e)
                notify(f"⚠️ icorsi-notes unexpected error: {e}")

        first = False

        if not LOOP:
            break

        # If outside the active window, sleep until it opens
        if not is_active_now(active_hours):
            wait = min(minutes_until_active(active_hours) * 60, 3600)
            log.info("Outside active window; sleeping %ds", wait)
            time.sleep(wait)
            continue

        log.info("Sleeping %ds until next pass", INTERVAL)
        time.sleep(INTERVAL)

    log.info("icorsi-notes done")


if __name__ == "__main__":
    main()
