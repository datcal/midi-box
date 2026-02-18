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


class DeviceRegistry:
    def __init__(self, config_path: str = None):
        self.config_path = config_path or str(CONFIG_DIR / "devices.yaml")
        self.usb_devices: dict[str, dict] = {}
        self.hardware_ports: dict[str, dict] = {}
        self.active_devices: dict[str, MidiDevice] = {}
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

    def identify_usb_device(self, vendor_id: int, product_id: int) -> str | None:
        """Look up a friendly name for a USB MIDI device by vendor:product ID."""
        key = f"{vendor_id:04x}:{product_id:04x}"
        if key in self.usb_devices:
            return self.usb_devices[key]["name"]
        return None

    def register_usb_device(self, port_id: str, name: str, vendor_product: str = ""):
        """Register a connected USB MIDI device."""
        device_info = self.usb_devices.get(vendor_product, {})
        device = MidiDevice(
            name=name,
            port_type="usb",
            direction="both",
            device_type=device_info.get("type", "unknown"),
            port_id=port_id,
            midi_channel=device_info.get("default_channel", 0),
            connected=True,
        )
        self.active_devices[name] = device
        logger.info(f"Registered USB device: {name} on {port_id}")
        return device

    def register_hardware_device(self, serial_port: str):
        """Register a hardware MIDI device (SC16IS752 / native UART)."""
        port_key = Path(serial_port).name  # e.g., "ttySC0"
        if port_key in self.hardware_ports:
            info = self.hardware_ports[port_key]
            device = MidiDevice(
                name=info["name"],
                port_type="hardware",
                direction=info.get("direction", "out"),
                device_type=info.get("type", "synth"),
                port_id=serial_port,
                midi_channel=info.get("default_channel", 0),
                connected=True,
            )
            self.active_devices[info["name"]] = device
            logger.info(f"Registered hardware device: {info['name']} on {serial_port}")
            return device
        else:
            logger.warning(f"Unknown hardware port: {port_key}")
            return None

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
