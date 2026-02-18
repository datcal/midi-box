"""
Preset Manager - Load, save, and switch MIDI routing presets.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger("midi-box.presets")

PRESET_DIR = Path(__file__).resolve().parent.parent / "presets"


class PresetManager:
    def __init__(self, preset_dir: str = None):
        self.preset_dir = Path(preset_dir) if preset_dir else PRESET_DIR
        self.current_preset: str | None = None
        self.current_data: dict | None = None

    def list_presets(self) -> list[str]:
        """List all available preset names."""
        if not self.preset_dir.exists():
            return []
        presets = sorted(self.preset_dir.glob("*.json"))
        return [p.stem for p in presets]

    def load(self, name: str) -> dict | None:
        """Load a preset by name. Returns the preset data dict."""
        path = self.preset_dir / f"{name}.json"
        if not path.exists():
            logger.error(f"Preset not found: {name}")
            return None

        try:
            with open(path) as f:
                data = json.load(f)
            self.current_preset = name
            self.current_data = data
            logger.info(f"Loaded preset: {name} ({len(data.get('routes', []))} routes)")
            return data
        except json.JSONDecodeError as e:
            logger.error(f"Invalid preset JSON {name}: {e}")
            return None

    def save(self, name: str, data: dict) -> bool:
        """Save a preset to disk."""
        self.preset_dir.mkdir(parents=True, exist_ok=True)
        path = self.preset_dir / f"{name}.json"

        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved preset: {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to save preset {name}: {e}")
            return False

    def delete(self, name: str) -> bool:
        """Delete a preset."""
        path = self.preset_dir / f"{name}.json"
        if path.exists():
            path.unlink()
            logger.info(f"Deleted preset: {name}")
            return True
        return False

    def get_routes(self, preset_data: dict = None) -> list[dict]:
        """Get the routes list from a preset."""
        data = preset_data or self.current_data
        if data:
            return data.get("routes", [])
        return []

    def get_clock_source(self, preset_data: dict = None) -> str | None:
        """Get the clock source from a preset."""
        data = preset_data or self.current_data
        if data:
            return data.get("clock_source")
        return None

    def create_preset(
        self,
        name: str,
        description: str,
        routes: list[dict],
        clock_source: str = None,
    ) -> dict:
        """Create a new preset data structure."""
        data = {
            "name": name,
            "description": description,
            "routes": routes,
        }
        if clock_source:
            data["clock_source"] = clock_source
        return data
