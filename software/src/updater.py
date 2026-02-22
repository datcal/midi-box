"""
updater.py — Software update checker and trigger for MIDI Box.

Runs entirely in the Flask process (no IPC needed).
Background thread checks GitHub Tags API every 6 hours.
Update execution is a detached subprocess that outlives the service restart it triggers.
"""

import logging
import subprocess
import threading
import time
from pathlib import Path

logger = logging.getLogger("midi-box.updater")

# Path constants
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # midi-box/
_VERSION_FILE = _REPO_ROOT / "VERSION"
_UPDATE_SCRIPT = _REPO_ROOT / "scripts" / "update.sh"
_UPDATE_LOG = Path("/tmp/midi-box-update.log")

_CHECK_INTERVAL_SECONDS = 6 * 3600  # 6 hours

# Module-level state — written by background thread, read by Flask request threads
_state: dict = {
    "current_version": "unknown",
    "latest_version": None,
    "update_available": False,
    "update_type": None,       # "simple" | "full" | None
    "last_checked": None,      # ISO timestamp string
    "check_error": None,
    "update_status": "idle",   # "idle" | "running"
    "update_pid": None,
}
_state_lock = threading.Lock()
_checker_started = False
_checker_lock = threading.Lock()


def get_current_version() -> str:
    """Read VERSION file from repo root. Returns 'unknown' if missing."""
    try:
        return _VERSION_FILE.read_text().strip()
    except FileNotFoundError:
        return "unknown"


def get_latest_version() -> tuple:
    """
    Fetch latest tag from the git remote using 'git ls-remote --tags origin'.
    Works for both public and private repos — uses whatever git credentials
    are configured on the machine (SSH keys, stored HTTPS credentials, etc.).
    Returns (tag_name_or_None, error_message_or_None).
    """
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", "--sort=-version:refname", "origin"],
            capture_output=True, text=True, timeout=20, cwd=str(_REPO_ROOT),
        )
        if result.returncode != 0:
            return None, result.stderr.strip() or "git ls-remote failed"

        # Output lines look like:
        #   abc123  refs/tags/v1.0.0
        #   def456  refs/tags/v1.0.0^{}   ← peeled annotated tag (skip these)
        tags = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].startswith("refs/tags/") and not parts[1].endswith("^{}"):
                tags.append(parts[1].replace("refs/tags/", ""))

        if not tags:
            return None, "No tags found in remote repository"

        # Pick the highest semver tag
        def _sort_key(v):
            try:
                return [int(x) for x in v.lstrip("v").split(".")]
            except Exception:
                return [0]

        tags.sort(key=_sort_key, reverse=True)
        return tags[0], None
    except Exception as exc:
        return None, str(exc)


def _compare_semver(v1: str, v2: str) -> int:
    """
    Compare two version strings (e.g. 'v1.2.3').
    Returns -1 if v1 < v2, 0 if equal, 1 if v1 > v2.
    """
    def _parts(v):
        return [int(x) for x in v.lstrip("v").split(".")]
    try:
        p1, p2 = _parts(v1), _parts(v2)
        return (p1 > p2) - (p1 < p2)
    except Exception:
        return 0


def _detect_update_type(current_tag: str, latest_tag: str) -> str:
    """
    Returns 'full' if pi_setup.sh changed between tags, else 'simple'.
    Falls back to 'simple' on any git error (safe default).
    """
    try:
        result_current = subprocess.run(
            ["git", "show", f"{current_tag}:scripts/pi_setup.sh"],
            capture_output=True, text=True, timeout=10, cwd=str(_REPO_ROOT),
        )
        result_latest = subprocess.run(
            ["git", "show", f"{latest_tag}:scripts/pi_setup.sh"],
            capture_output=True, text=True, timeout=10, cwd=str(_REPO_ROOT),
        )
        if result_current.returncode != 0 or result_latest.returncode != 0:
            return "simple"
        if result_current.stdout != result_latest.stdout:
            return "full"
        return "simple"
    except Exception as exc:
        logger.warning("Could not detect update type: %s", exc)
        return "simple"


def check_for_updates() -> dict:
    """
    Synchronously check GitHub for a newer tag. Updates module _state.
    Returns a copy of _state.
    """
    current = get_current_version()
    latest, error = get_latest_version()
    now = time.strftime("%Y-%m-%dT%H:%M:%S")

    with _state_lock:
        _state["current_version"] = current
        _state["last_checked"] = now
        if error:
            _state["check_error"] = error
            _state["latest_version"] = None
            _state["update_available"] = False
            _state["update_type"] = None
        else:
            _state["check_error"] = None
            _state["latest_version"] = latest
            update_available = _compare_semver(current, latest) < 0
            _state["update_available"] = update_available
            if update_available:
                _state["update_type"] = _detect_update_type(current, latest)
            else:
                _state["update_type"] = None
        return dict(_state)


def trigger_update(update_type: str) -> dict:
    """
    Launch update.sh detached from the service process group.
    Returns {'ok': bool, 'pid': int} or {'ok': False, 'error': str}.
    """
    with _state_lock:
        if _state["update_status"] == "running":
            return {"ok": False, "error": "Update already in progress"}

    if not _UPDATE_SCRIPT.exists():
        return {"ok": False, "error": f"Update script not found: {_UPDATE_SCRIPT}"}

    # Clear old log
    try:
        _UPDATE_LOG.write_text("")
    except Exception:
        pass

    try:
        log_fh = open(str(_UPDATE_LOG), "w")
        # Use 'sudo bash script' instead of 'sudo script' so the execute bit and
        # shebang line are irrelevant (avoids "command not found" on fresh clones).
        proc = subprocess.Popen(
            ["sudo", "bash", str(_UPDATE_SCRIPT), update_type],
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # setsid — detach from service process group
            close_fds=True,
        )
        with _state_lock:
            _state["update_status"] = "running"
            _state["update_pid"] = proc.pid
        logger.info("Update triggered (type=%s, pid=%d)", update_type, proc.pid)

        # Monitor process in background so status returns to idle on completion/failure
        def _monitor(p, fh):
            p.wait()
            try:
                fh.close()
            except Exception:
                pass
            with _state_lock:
                _state["update_status"] = "idle"
                _state["update_pid"] = None
            logger.info("Update process finished (exit=%d)", p.returncode)

        threading.Thread(target=_monitor, args=(proc, log_fh), daemon=True).start()

        return {"ok": True, "pid": proc.pid}
    except Exception as exc:
        logger.error("Failed to launch update script: %s", exc)
        with _state_lock:
            _state["update_status"] = "idle"
        return {"ok": False, "error": str(exc)}


def get_update_log(max_lines: int = 200) -> list:
    """Read /tmp/midi-box-update.log, return up to max_lines lines."""
    try:
        text = _UPDATE_LOG.read_text(errors="replace")
        lines = text.splitlines()
        return lines[-max_lines:] if len(lines) > max_lines else lines
    except FileNotFoundError:
        return []
    except Exception:
        return []


def get_status() -> dict:
    """Return a thread-safe copy of the current update state."""
    with _state_lock:
        return dict(_state)


def _background_check_loop():
    """Daemon thread: waits for Pi to get network, then checks every 6 hours."""
    time.sleep(30)  # Boot delay — give Pi time to acquire internet connection
    while True:
        try:
            result = check_for_updates()
            logger.info(
                "Update check: current=%s latest=%s available=%s",
                result["current_version"],
                result["latest_version"],
                result["update_available"],
            )
        except Exception as exc:
            logger.warning("Update check failed: %s", exc)
        time.sleep(_CHECK_INTERVAL_SECONDS)


def start_background_checker():
    """
    Start the periodic update-check daemon thread.
    Safe to call multiple times — only one thread is ever started.
    """
    global _checker_started
    with _checker_lock:
        if _checker_started:
            return
        _checker_started = True
    t = threading.Thread(
        target=_background_check_loop,
        daemon=True,
        name="midi-box-updater",
    )
    t.start()
    logger.info("Update checker started (interval: 6h, initial delay: 30s)")
