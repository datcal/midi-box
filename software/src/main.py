#!/usr/bin/env python3
"""
MIDI Box - Main Entry Point

Initializes all subsystems and starts the MIDI routing engine + web UI.
Runs on both macOS (for testing) and Raspberry Pi (production).
"""

import sys
import platform
import signal
import time
import logging
import argparse
import threading

from device_registry import DeviceRegistry
from alsa_midi import AlsaMidi
from router import MidiRouter
from preset_manager import PresetManager
from midi_logger import MidiLogger
from state import StateManager
from ui_web import create_app, LogBuffer

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("midi-box")


def detect_platform() -> str:
    system = platform.system()
    if system == "Darwin":
        return "mac"
    elif system == "Linux":
        try:
            with open("/proc/device-tree/model") as f:
                if "raspberry" in f.read().lower():
                    return "pi"
        except FileNotFoundError:
            pass
        return "linux"
    return "unknown"


# ---------------------------------------------------------------------------
# MIDI Box Application
# ---------------------------------------------------------------------------

class MidiBox:
    def __init__(self, args):
        self.args = args
        self.platform = args.platform or detect_platform()
        self.registry = DeviceRegistry()
        self.alsa = AlsaMidi(
            on_device_connected=self._on_usb_device_connected,
            on_device_disconnected=self._on_usb_device_disconnected,
        )
        self.hw = None       # HardwareMidi, Pi only
        self.gadget = None   # GadgetMidi, Pi only
        self.router = MidiRouter()
        self.presets = PresetManager()
        self.state = StateManager()
        self.midi_logger = MidiLogger(max_entries=500)
        self.log_buffer = LogBuffer()
        self.mode = "standalone"
        self.wifi_config = self._load_wifi_config()
        self._running = False
        self._web_thread = None

    def start(self):
        self.log_buffer.install()

        logger.info("=" * 50)
        logger.info("  MIDI Box Starting")
        logger.info(f"  Platform: {self.platform}")
        logger.info("=" * 50)

        # Restore saved state
        self.state.load()

        # Detect mode
        self.mode = self._detect_mode()
        logger.info(f"Mode: {self.mode.upper()}")

        # Register the send callback
        self.router.set_send_callback(self._send_midi)

        # Open MIDI devices (real or mock)
        if self.args.mock:
            self._init_mock_devices()
        else:
            self._init_usb_midi()
            if self.platform == "pi":
                self._init_hardware_midi()

        # If DAW mode on Pi, set up USB gadget bridge
        if self.mode == "daw" and self.platform == "pi":
            self._init_gadget()

        # Restore routes from saved state, or fall back to preset
        self._restore_state()

        # Start hotplug monitor for USB devices (skip in mock mode)
        if not self.args.mock:
            self.alsa.start_hotplug_monitor()

        # Start hardware MIDI read thread (Pi only)
        if self.hw:
            self.hw.start_reading(self._on_hw_midi_received)

        # Print status
        print()
        print(self.registry.list_devices())
        print()
        print(self.router.status())
        print()

        # Start web UI
        self._start_web_ui()

        # Main loop
        self._running = True
        logger.info("Routing engine running. Press Ctrl+C to stop.")
        logger.info(f"Web UI: http://localhost:{self.args.port}")
        self._main_loop()

    def stop(self):
        logger.info("Shutting down...")
        self._save_state()
        self._running = False
        self.alsa.close_all()
        if self.hw:
            self.hw.close_all()
        if self.gadget:
            self.gadget.close()
        logger.info("MIDI Box stopped.")

    # -------------------------------------------------------------------
    # Initialization
    # -------------------------------------------------------------------

    def _detect_mode(self) -> str:
        if self.args.mode:
            return self.args.mode
        # On Pi, check if Mac is connected via USB-C gadget
        if self.platform == "pi":
            try:
                from gadget import GadgetMidi
                g = GadgetMidi()
                if g.is_connected:
                    return "daw"
            except ImportError:
                pass
        return "standalone"

    def _init_usb_midi(self):
        """Open all USB MIDI devices and register them."""
        ports = self.alsa.open_all()
        for port in ports:
            device = self.registry.register_usb_device(port.port_name, port.name)
            if device:
                logger.info(f"  USB: {device.name}")
        if not ports:
            logger.info("  No USB MIDI devices found")

    def _load_wifi_config(self) -> dict:
        """Load WiFi AP settings from midi_box.yaml, falling back to defaults."""
        import yaml
        from pathlib import Path
        config_path = Path(__file__).resolve().parent.parent / "config" / "midi_box.yaml"
        defaults = {
            "ssid": "MIDI-BOX",
            "password": "midibox123",
            "ip": "192.168.4.1",
            "port": getattr(self.args, "port", 8080),
        }
        try:
            with open(config_path) as f:
                cfg = yaml.safe_load(f) or {}
            defaults.update(cfg.get("wifi_ap", {}))
            defaults["port"] = getattr(self.args, "port", 8080)
        except FileNotFoundError:
            pass
        return defaults

    def _init_mock_devices(self):
        """Register all devices from config as fake connected devices (no hardware needed)."""
        logger.info("Mock mode: loading all configured devices as virtual...")
        names = []

        for vendor_product, info in self.registry.usb_devices.items():
            name = info["name"]
            self.registry.register_usb_device(name, name, vendor_product)
            names.append(name)
            logger.info(f"  MOCK USB: {name}")

        for port_key in self.registry.hardware_ports:
            device = self.registry.register_hardware_device(f"/dev/{port_key}")
            if device:
                names.append(device.name)
                logger.info(f"  MOCK HW:  {device.name}")

        self.alsa.open_mock_devices(names)

    def _init_hardware_midi(self):
        """Open hardware MIDI ports (Pi only)."""
        try:
            from hw_midi import HardwareMidi
            self.hw = HardwareMidi()
            hw_config = self.registry.hardware_ports
            ports = self.hw.open_all(hw_config)
            for port in ports:
                device = self.registry.register_hardware_device(port.device_path)
                if device:
                    logger.info(f"  HW:  {device.name} ({port.device_path})")
        except ImportError:
            logger.info("  Hardware MIDI not available (not on Pi)")

    def _init_gadget(self):
        """Set up USB gadget MIDI bridge (Pi only)."""
        try:
            from gadget import GadgetMidi
            self.gadget = GadgetMidi()
            if not self.gadget.is_configured:
                self.gadget.setup()
            if self.gadget.open_ports():
                logger.info("DAW bridge active")
            else:
                logger.warning("Could not open gadget ports")
        except ImportError:
            logger.info("  USB gadget not available (not on Pi)")

    def _restore_state(self):
        """Restore routes from saved state, or fall back to a preset."""
        saved_routes = self.state.get_routes()

        if saved_routes:
            # Restore from saved state
            logger.info(f"Restoring {len(saved_routes)} routes from saved state")
            self.router.load_routes(saved_routes)
            clock = self.state.get_clock_source()
            if clock:
                self.router.set_clock_source(clock)
            # Also set the preset name so the UI shows it
            self.presets.current_preset = self.state.get_preset()
        else:
            # No saved state — load from preset file
            preset_name = self.args.preset or self.state.get_preset() or "default"
            self._load_preset(preset_name)

    def _load_preset(self, name: str):
        data = self.presets.load(name)
        if not data:
            logger.warning(f"Preset '{name}' not found, running with no routes")
            return
        routes = self.presets.get_routes(data)
        self.router.load_routes(routes)
        clock = self.presets.get_clock_source(data)
        if clock:
            self.router.set_clock_source(clock)
        # Save to state
        self.state.set_preset(name)
        self.state.set_routes(self.router.dump_routes())
        self.state.set_clock_source(clock)

    def _save_state(self):
        """Persist current state to disk."""
        self.state.set_routes(self.router.dump_routes())
        self.state.set_clock_source(self.router._clock_source)
        logger.info("State saved")

    def _start_web_ui(self):
        app = create_app(self)
        self._web_thread = threading.Thread(
            target=app.run,
            kwargs={
                "host": self.args.host,
                "port": self.args.port,
                "debug": False,
                "use_reloader": False,
            },
            daemon=True,
        )
        self._web_thread.start()

    # -------------------------------------------------------------------
    # Main Loop
    # -------------------------------------------------------------------

    def _main_loop(self):
        while self._running:
            # Read from all USB MIDI input ports
            for port_name in self.alsa.get_input_ports():
                msg = self.alsa.receive(port_name)
                if msg:
                    self.midi_logger.log_input(port_name, msg)
                    self.router.process_message(port_name, msg)

            # Read from USB gadget (Mac → Pi)
            if self.gadget and self.mode == "daw":
                for msg in self.gadget.receive_from_host():
                    self.midi_logger.log_input("Logic Pro", msg)
                    self.router.process_message("Logic Pro", msg)

            time.sleep(0.001)

    # -------------------------------------------------------------------
    # Callbacks
    # -------------------------------------------------------------------

    def _send_midi(self, destination: str, message) -> bool:
        device = self.registry.get_device(destination)

        # Send to Mac via gadget
        if destination in ("Logic Pro", "Mac"):
            if self.gadget:
                ok = self.gadget.send_to_host(message)
                if ok:
                    self.midi_logger.log_output(destination, message)
                return ok
            return False

        if not device:
            return False

        ok = False
        if device.port_type == "usb":
            ok = self.alsa.send(device.port_id, message)
        elif device.port_type == "hardware" and self.hw:
            ok = self.hw.send(device.name, message)

        if ok:
            self.midi_logger.log_output(destination, message)
        return ok

    def _on_hw_midi_received(self, port_name: str, message):
        self.midi_logger.log_input(port_name, message)
        self.router.process_message(port_name, message)

    def _on_usb_device_connected(self, name: str, port):
        self.registry.register_usb_device(port.port_name, name)
        logger.info(f"Hotplug: {name} connected")

    def _on_usb_device_disconnected(self, name: str):
        self.registry.unregister_device(name)
        logger.info(f"Hotplug: {name} disconnected")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="MIDI Box Router")
    parser.add_argument(
        "--mode", choices=["standalone", "daw"], default=None,
        help="Force operating mode (default: auto-detect)",
    )
    parser.add_argument(
        "--preset", default="default",
        help="Preset to load on startup (default: 'default')",
    )
    parser.add_argument(
        "--platform", choices=["mac", "pi"], default=None,
        help="Force platform (default: auto-detect)",
    )
    parser.add_argument(
        "--host", default="0.0.0.0",
        help="Web UI bind address (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port", default=8080, type=int,
        help="Web UI port (default: 8080)",
    )
    parser.add_argument(
        "--mock", action="store_true",
        help="Use virtual devices from config (no hardware required)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--list-presets", action="store_true",
        help="List available presets and exit",
    )
    parser.add_argument(
        "--list-devices", action="store_true",
        help="List MIDI devices and exit",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.list_presets:
        pm = PresetManager()
        print("Available presets:")
        for p in pm.list_presets():
            print(f"  - {p}")
        return

    if args.list_devices:
        import mido
        print("MIDI Input Ports:")
        for name in mido.get_input_names():
            print(f"  IN:  {name}")
        print("\nMIDI Output Ports:")
        for name in mido.get_output_names():
            print(f"  OUT: {name}")
        return

    box = MidiBox(args)

    def signal_handler(sig, frame):
        box.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    box.start()


if __name__ == "__main__":
    main()
