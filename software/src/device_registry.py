"""
Device Registry - Maps USB IDs and serial ports to friendly device names.
Tracks connected devices and their MIDI port assignments.
"""

import yaml
import logging
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger("midi-box.registry")

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


@dataclass
class MidiDevice:
    name: str
    port_type: str  # "usb" or "hardware"
    direction: str  # "in", "out", or "both"
    device_type: str  # "controller", "synth", "sampler", etc.
    port_id: str = ""  # ALSA port string or serial device path
    midi_channel: int = 0  # 0 = all channels
    connected: bool = False
    block_transport: bool = False  # block start/stop/clock broadcast to this device


class DeviceRegistry:
    def __init__(self, config_path: str = None):
        self.config_path = config_path or str(CONFIG_DIR / "devices.yaml")
        self.usb_devices: dict[str, dict] = {}
        self.hardware_ports: dict[str, dict] = {}
        self.active_devices: dict[str, MidiDevice] = {}
        self._device_overrides: dict[str, dict] = {}  # user overrides from state
        self._load_config()

    def _load_config(self):
        try:
            with open(self.config_path) as f:
                config = yaml.safe_load(f)
            self.usb_devices = config.get("usb_devices", {})
            self.hardware_ports = config.get("hardware_ports", {})
            logger.info(
                f"Loaded device config: {len(self.usb_devices)} USB, "
                f"{len(self.hardware_ports)} hardware"
            )
        except FileNotFoundError:
            logger.warning(f"Config not found: {self.config_path}, using empty registry")
        except Exception as e:
            logger.error(f"Failed to load config: {e}")

    def set_device_overrides(self, overrides: dict):
        """Load user-configured device overrides from state."""
        self._device_overrides = overrides or {}

    def match_config_by_port_name(self, port_name: str) -> tuple[str, dict]:
        """Match an ALSA/CoreMIDI port name against known devices from config.

        Returns (friendly_name, config_dict) or (port_name, {}) if not found.
        Port names look like:
          macOS:  "KeyLab 88 MK2" or "KeyLab 88 MK2 Port 1"
          Linux:  "KeyLab 88 MK2:KeyLab 88 MK2 MIDI 1 28:0"
        """
        port_lower = port_name.lower()

        # Try matching against known device names from config
        for vendor_product, info in self.usb_devices.items():
            known_name = info.get("name", "")
            if known_name and known_name.lower() in port_lower:
                return known_name, info

        # No match — use the raw port name, cleaned up
        friendly = self._clean_port_name(port_name)
        return friendly, {}

    def _clean_port_name(self, port_name: str) -> str:
        """Extract a human-friendly name from a raw MIDI port name."""
        # Remove ALSA-style suffix like ":KeyLab 88 MK2 MIDI 1 28:0"
        if ":" in port_name:
            parts = port_name.split(":")
            # Use the first part (usually the device name)
            name = parts[0].strip()
        else:
            name = port_name

        # Remove trailing port numbers like "Port 1", "MIDI 1"
        import re
        name = re.sub(r'\s+(Port|MIDI)\s+\d+$', '', name, flags=re.IGNORECASE)
        return name.strip() or port_name

    def identify_usb_device(self, vendor_id: int, product_id: int) -> str | None:
        """Look up a friendly name for a USB MIDI device by vendor:product ID."""
        key = f"{vendor_id:04x}:{product_id:04x}"
        if key in self.usb_devices:
            return self.usb_devices[key]["name"]
        return None

    def register_usb_device(self, port_id: str, name: str, vendor_product: str = ""):
        """Register a connected USB MIDI device.

        If vendor_product is given, use config lookup.
        Otherwise, try to match by port name.
        """
        # Try config lookup by vendor:product first
        device_info = self.usb_devices.get(vendor_product, {})
        friendly_name = device_info.get("name", "") if device_info else ""

        # If no vendor_product match, try name matching
        if not friendly_name:
            friendly_name, device_info = self.match_config_by_port_name(name)

        # If this friendly name is already registered, keep the first port found.
        # Some devices (e.g. MicroBrute) expose multiple USB MIDI ports; the
        # first port is the main MIDI port; later ports (MIDI Interface, SysEx)
        # would overwrite and break routing if allowed through.
        existing = self.active_devices.get(friendly_name)
        if existing and existing.connected:
            logger.debug(
                f"Device '{friendly_name}' already registered via {existing.port_id}, "
                f"skipping secondary port {port_id}"
            )
            return existing

        # Apply user overrides if any
        overrides = self._device_overrides.get(friendly_name, {})

        device = MidiDevice(
            name=friendly_name,
            port_type="usb",
            direction=overrides.get("direction", device_info.get("direction", "both")),
            device_type=overrides.get("device_type", device_info.get("type", "unknown")),
            port_id=port_id,
            midi_channel=overrides.get("midi_channel", device_info.get("default_channel", 0)),
            connected=True,
            block_transport=overrides.get("block_transport", False),
        )
        self.active_devices[friendly_name] = device
        logger.info(f"Registered USB device: {friendly_name} (port: {port_id})")
        return device

    def register_hardware_device(self, serial_port: str):
        """Register a hardware MIDI device (Pi native UART)."""
        port_key = Path(serial_port).name  # e.g., "ttyAMA0"
        if port_key in self.hardware_ports:
            info = self.hardware_ports[port_key]
            name = info["name"]
            overrides = self._device_overrides.get(name, {})
            device = MidiDevice(
                name=name,
                port_type="hardware",
                direction=overrides.get("direction", info.get("direction", "out")),
                device_type=overrides.get("device_type", info.get("type", "synth")),
                port_id=serial_port,
                midi_channel=overrides.get("midi_channel", info.get("default_channel", 0)),
                connected=True,
                block_transport=overrides.get("block_transport", False),
            )
            self.active_devices[name] = device
            logger.info(f"Registered hardware device: {name} on {serial_port}")
            return device
        else:
            logger.warning(f"Unknown hardware port: {port_key}")
            return None

    def update_device_config(self, name: str, direction: str = None,
                              device_type: str = None, midi_channel: int = None,
                              block_transport: bool = None) -> bool:
        """Update device configuration (called from UI)."""
        dev = self.active_devices.get(name)
        if not dev:
            return False
        if direction is not None:
            dev.direction = direction
        if device_type is not None:
            dev.device_type = device_type
        if midi_channel is not None:
            dev.midi_channel = midi_channel
        if block_transport is not None:
            dev.block_transport = block_transport
        logger.info(f"Updated device config: {name} -> dir={dev.direction}, type={dev.device_type}")
        return True

    def get_device(self, name: str) -> MidiDevice | None:
        return self.active_devices.get(name)

    def get_all_devices(self) -> dict[str, MidiDevice]:
        return self.active_devices

    def get_input_devices(self) -> list[MidiDevice]:
        return [
            d for d in self.active_devices.values()
            if d.direction in ("in", "both") and d.connected
        ]

    def get_output_devices(self) -> list[MidiDevice]:
        return [
            d for d in self.active_devices.values()
            if d.direction in ("out", "both") and d.connected
        ]

    def unregister_device(self, name: str):
        if name in self.active_devices:
            self.active_devices[name].connected = False
            del self.active_devices[name]
            logger.info(f"Unregistered device: {name}")

    def find_by_port_id(self, port_id: str) -> MidiDevice | None:
        """Find a device by its port_id (ALSA port name)."""
        for dev in self.active_devices.values():
            if dev.port_id == port_id:
                return dev
        return None

    def list_devices(self) -> str:
        lines = ["Connected MIDI Devices:", ""]
        for name, dev in self.active_devices.items():
            status = "OK" if dev.connected else "DISCONNECTED"
            lines.append(
                f"  {name:.<30} {dev.port_type:>8} | "
                f"{dev.direction:>4} | ch {dev.midi_channel or 'all':>3} | {status}"
            )
        if not self.active_devices:
            lines.append("  (no devices connected)")
        return "\n".join(lines)
