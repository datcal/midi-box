"""
State Manager - Persists application state to a JSON file.
Saves current preset, active routes, clock source, and user settings.
Auto-saves on changes, restores on startup.
"""

import json
import time
import logging
import shutil
from pathlib import Path

logger = logging.getLogger("midi-box.state")

STATE_DIR = Path(__file__).resolve().parent.parent / "data"
STATE_FILE = STATE_DIR / "state.json"
BACKUP_FILE = STATE_DIR / "state.backup.json"

DEFAULT_STATE = {
    "version": 1,
    "current_preset": "default",
    "clock_source": None,
    "routes": [],
    "device_overrides": {},  # {device_name: {direction, device_type, midi_channel}}
    "launcher": {},  # clip launcher state (layers, clips, clock config)
    "recorder_clock": {
        "source": "standalone",
        "bpm": 120.0,
        "quantize": "free",
        "beats_per_bar": 4,
    },
    "looper_clock": {
        "source": "standalone",
        "bpm": 120.0,
        "quantize": "free",
        "beats_per_bar": 4,
    },
    "settings": {
        "mode": "standalone",
        "log_level": "INFO",
    },
    "last_saved": None,
}


class StateManager:
    def __init__(self, state_file: str = None):
        self.state_file = Path(state_file) if state_file else STATE_FILE
        self.state: dict = dict(DEFAULT_STATE)
        self._dirty = False

    def load(self) -> dict:
        """Load state from disk. Returns the state dict."""
        if not self.state_file.exists():
            logger.info("No state file found, using defaults")
            self.state = dict(DEFAULT_STATE)
            return self.state

        try:
            with open(self.state_file) as f:
                self.state = json.load(f)
            logger.info(f"State loaded: preset={self.state.get('current_preset')}, "
                        f"{len(self.state.get('routes', []))} routes")
            return self.state
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Corrupted state file: {e}, trying backup...")
            return self._load_backup()

    def _load_backup(self) -> dict:
        backup = self.state_file.parent / "state.backup.json"
        if backup.exists():
            try:
                with open(backup) as f:
                    self.state = json.load(f)
                logger.info("Restored from backup")
                return self.state
            except Exception:
                pass
        logger.warning("No valid backup, using defaults")
        self.state = dict(DEFAULT_STATE)
        return self.state

    def save(self):
        """Save current state to disk. Creates a backup of the previous state."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state["last_saved"] = time.strftime("%Y-%m-%d %H:%M:%S")

        # Backup existing state file before overwriting
        if self.state_file.exists():
            backup = self.state_file.parent / "state.backup.json"
            shutil.copy2(self.state_file, backup)

        try:
            tmp = self.state_file.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump(self.state, f, indent=2)
            tmp.replace(self.state_file)
            self._dirty = False
            logger.debug("State saved")
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def set_preset(self, name: str):
        self.state["current_preset"] = name
        self.save()

    def set_routes(self, routes: list[dict]):
        self.state["routes"] = routes
        self.save()

    def set_clock_source(self, source: str | None):
        self.state["clock_source"] = source
        self.save()

    def get_preset(self) -> str:
        return self.state.get("current_preset", "default")

    def get_routes(self) -> list[dict]:
        return self.state.get("routes", [])

    def get_clock_source(self) -> str | None:
        return self.state.get("clock_source")

    def get_launcher_state(self) -> dict:
        return self.state.get("launcher", {})

    def set_launcher_state(self, data: dict):
        self.state["launcher"] = data
        self.save()

    def get_device_overrides(self) -> dict:
        return self.state.get("device_overrides", {})

    def set_device_override(self, name: str, config: dict):
        if "device_overrides" not in self.state:
            self.state["device_overrides"] = {}
        self.state["device_overrides"][name] = config
        self.save()

    def get_recorder_clock(self) -> dict:
        return self.state.get("recorder_clock", {})

    def set_recorder_clock(self, data: dict):
        self.state["recorder_clock"] = data
        self.save()

    def get_looper_clock(self) -> dict:
        return self.state.get("looper_clock", {})

    def set_looper_clock(self, data: dict):
        self.state["looper_clock"] = data
        self.save()

    def get_settings(self) -> dict:
        return self.state.get("settings", {})

    def update_settings(self, **kwargs):
        if "settings" not in self.state:
            self.state["settings"] = {}
        self.state["settings"].update(kwargs)
        self.save()

    def export_all(self) -> dict:
        """Export complete state for backup/transfer."""
        return {
            "export_version": 1,
            "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "state": dict(self.state),
        }

    def import_all(self, data: dict) -> bool:
        """Import state from an exported file."""
        try:
            if "state" in data:
                imported = data["state"]
            else:
                imported = data

            # Validate minimum required fields
            if "routes" not in imported and "current_preset" not in imported:
                logger.error("Import data missing required fields")
                return False

            # Merge with defaults to fill any missing fields
            self.state = {**DEFAULT_STATE, **imported}
            self.save()
            logger.info(f"State imported: preset={self.state.get('current_preset')}, "
                        f"{len(self.state.get('routes', []))} routes")
            return True
        except Exception as e:
            logger.error(f"Import failed: {e}")
            return False

    def reset(self):
        """Reset to default state."""
        self.state = dict(DEFAULT_STATE)
        self.save()
        logger.info("State reset to defaults")
