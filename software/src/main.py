#!/usr/bin/env python3
"""
MIDI Box - Main Entry Point

Initializes all subsystems and starts the MIDI routing engine + web UI.
Runs on both macOS (for testing) and Raspberry Pi (production).

Architecture:
  Process 1 (this process): MIDI routing engine — owns all MIDI hardware objects.
  Process 2 (Flask subprocess): Web API server — reads shared state, sends commands.
  IPC: multiprocessing.Manager shared dict + command queue.
"""

import os
import sys
import platform
import signal
from typing import Optional
import time
import logging
import logging.handlers
import argparse
import threading
import multiprocessing

import mido

# --- Targeted diagnostic logger (writes to data/midi_debug.log) ---
# Only captures transport send results and per-device send timing.
_diag_logger = logging.getLogger("midi-box.diag")
_diag_logger.setLevel(logging.DEBUG)
_diag_logger.propagate = False  # don't pollute console
_DIAG_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "midi_debug.log"
)
_diag_handler = logging.handlers.RotatingFileHandler(
    _DIAG_LOG_PATH, maxBytes=512_000, backupCount=1,  # ~500 KB cap
)
_diag_handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
_diag_logger.addHandler(_diag_handler)

# Message types that must never appear in the MIDI monitor ring buffer.
# Clock (0xF8) fires 24 times per beat — logging it would flood the 500-entry
# buffer in under a second and add lock-acquisition overhead on the hot path.
_TRANSPORT_TYPES = frozenset(("clock", "start", "stop", "continue", "songpos"))

# Pre-allocated clock message — reused on every tick to avoid GC churn.
_CLOCK_MSG = mido.Message("clock")

from device_registry import DeviceRegistry
from alsa_midi import AlsaMidi
from router import MidiRouter
from preset_manager import PresetManager
from midi_logger import MidiLogger
from midi_player import MidiPlayer
from midi_looper import MidiLooper
from quick_recorder import QuickRecorder
from gpio_pedal import GpioPedal
from rtpmidi import RtpMidiServer
from clip_launcher import ClipLauncher
from clock_manager import ClockManager
from state import StateManager
from ui_web import LogBuffer, run_flask_process
from ipc import IpcBridge, STATE_UPDATE_INTERVAL

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
            on_message=self._on_usb_midi_received,
        )
        self.hw = None       # HardwareMidi, Pi only
        self.gadget = None   # GadgetMidi, Pi only
        self.router = MidiRouter()
        self.presets = PresetManager()
        self.state = StateManager()
        self.midi_logger = MidiLogger(max_entries=500)
        # ClockManager must be created before modules that depend on it
        self.clock_manager = ClockManager()
        self.player = MidiPlayer(clock_manager=self.clock_manager)
        self.looper = MidiLooper(clock_manager=self.clock_manager)
        self.launcher = ClipLauncher(clock_manager=self.clock_manager)
        self.log_buffer = LogBuffer()
        self.mode = "standalone"
        self.wifi_config = self._load_wifi_config()
        self.rtp_midi: Optional[RtpMidiServer] = None
        self._running = False
        self._web_process = None
        self.bridge = None
        self._performance_mode = False
        # Cached list of output device names for the clock broadcast loop.
        # Rebuilt once at startup and invalidated on hotplug events instead of
        # being recomputed from scratch on every 24-PPQ tick.
        self._clock_output_names: list[str] = []
        self._verbose = getattr(args, "verbose", False)
        self.recorder = QuickRecorder(recordings_dir="data/recordings",
                                      clock_manager=self.clock_manager)
        self.gpio_pedal = None

    def start(self):
        self.log_buffer.install()

        logger.info("=" * 50)
        logger.info("  MIDI Box Starting")
        logger.info(f"  Platform: {self.platform}")
        logger.info("=" * 50)

        # Restore saved state
        self.state.load()

        # Apply device overrides from saved state
        self.registry.set_device_overrides(
            self.state.state.get("device_overrides", {})
        )

        # Detect mode
        self.mode = self._detect_mode()
        logger.info(f"Mode: {self.mode.upper()}")

        # Register callbacks
        self.router.set_send_callback(self._send_midi)
        self.player._send_callback  = self._send_midi
        self.looper._send_callback  = self._send_midi
        self.launcher._send_callback = self._send_midi
        self.recorder._router_callback = self.router.process_message

        # Wire ClockManager clock callback via router:
        # router calls this for clock/start/stop/continue from the designated source
        self.router._clock_callback = self._on_external_clock_message

        # Broadcast MIDI clock (0xF8) to all output devices at 24 PPQ.
        # Works for both internal clock (generated by ClockManager thread) and
        # external clock (forwarded immediately when 0xF8 is received).
        self.clock_manager.register_midi_clock_callback(self._send_clock_to_outputs)

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

        # Initialize clip launcher (restore state or auto-create layers)
        self._init_launcher()

        # Restore recorder/looper clock settings
        self._restore_clock_settings()

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

        # Build the clock output device cache before the clock thread starts ticking.
        self._refresh_clock_outputs()

        # Start ClockManager (tick engine) then Launcher (tick subscriber)
        self.clock_manager.start()
        self.launcher.start()

        # Create IPC bridge and start web UI in a separate process
        self.bridge = IpcBridge()
        self._start_web_ui()

        # Start RTP-MIDI server (Apple MIDI over WiFi)
        self._init_rtpmidi()

        # GPIO foot pedal (Pi only)
        if self.platform == "pi":
            try:
                import yaml
                from pathlib import Path
                _cfg_path = Path(__file__).resolve().parent.parent / "config" / "midi_box.yaml"
                with open(_cfg_path) as _f:
                    _yaml = yaml.safe_load(_f) or {}
                gpio_cfg = _yaml.get("gpio_pedal", {})
            except Exception:
                gpio_cfg = {}
            self.gpio_pedal = GpioPedal(
                pin=gpio_cfg.get("pin", 17),
                pull_up=gpio_cfg.get("pull_up", True),
                debounce_ms=gpio_cfg.get("debounce_ms", 50),
                callback=self._on_pedal_press,
            )

        # Main loop
        self._running = True
        logger.info("Routing engine running. Press Ctrl+C to stop.")
        logger.info(f"Web UI: http://localhost:{self.args.port}")
        self._set_realtime_priority()
        self._main_loop()

    def stop(self):
        logger.info("Shutting down...")
        self.player.stop()
        self.looper.close()
        self.recorder.close()
        if self.gpio_pedal:
            self.gpio_pedal.close()
        self.launcher.stop()
        self.clock_manager.stop()
        if self.rtp_midi:
            self.rtp_midi.stop()
        self._save_state()
        self._running = False
        self.alsa.close_all()
        if self.hw:
            self.hw.close_all()
        if self.gadget:
            self.gadget.close()
        if self._web_process and self._web_process.is_alive():
            self._web_process.terminate()
        if self.bridge:
            self.bridge.close()
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
            device = self.registry.register_usb_device(port.port_name, port.port_name)
            if device:
                logger.info(f"  USB: {device.name} (port: {port.port_name})")
        if not ports:
            logger.info("  No USB MIDI devices found")
        # Apply any manually-saved port overrides (handles ALSA client number changes)
        self._apply_port_overrides()

    def _apply_port_overrides(self):
        """After all devices are registered, honour saved port_id overrides.

        ALSA assigns a new client number on every boot, so the full port string
        changes (e.g. "TR-8S:TR-8S MIDI 2 20:0" → "…32:0").  We store only the
        stable base name (everything before the trailing " dd:d" suffix) and
        find the matching open port at startup.
        """
        import re
        overrides = self.state.get_device_overrides()
        with self.alsa._lock:
            open_ports = list(self.alsa.ports.keys())
        for dev_name, cfg in overrides.items():
            saved_port = cfg.get("port_id", "")
            if not saved_port:
                continue
            dev = self.registry.get_device(dev_name)
            if not dev or dev.port_type != "usb":
                continue
            # Strip trailing ALSA "client:port" number to get the stable base
            base = re.sub(r'\s+\d+:\d+$', '', saved_port)
            match = next((p for p in open_ports if p.startswith(base)), None)
            if match and match != dev.port_id:
                logger.info(f"Port override: {dev_name} → {match} (was {dev.port_id})")
                dev.port_id = match

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

    def _init_rtpmidi(self):
        """Start the RTP-MIDI (Apple MIDI) server and register it as a virtual device."""
        try:
            self.rtp_midi = RtpMidiServer(name="MIDI Box", port=5004)
            if self.rtp_midi.start():
                self.rtp_midi.set_on_message(self._on_rtpmidi_received)
                # Register as both input and output so it appears in routing
                self.registry.register_usb_device("RTP-MIDI (WiFi)", "RTP-MIDI (WiFi)")
                logger.info("RTP-MIDI (Apple MIDI over WiFi) ready")
            else:
                self.rtp_midi = None
        except Exception as exc:
            logger.warning(f"RTP-MIDI server failed to start: {exc}")
            self.rtp_midi = None

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
            # Drop any saved routes whose endpoints don't match real devices.
            known = set(self.registry.get_all_devices().keys())
            valid = [r for r in saved_routes if r["from"] in known and r["to"] in known]
            if len(valid) < len(saved_routes):
                dropped = [r["name"] for r in saved_routes if r not in valid]
                logger.warning(f"Dropped {len(dropped)} stale route(s) from state: {dropped}")
                self.state.set_routes(valid)
                saved_routes = valid

            logger.info(f"Restoring {len(saved_routes)} routes from saved state")
            self.router.load_routes(saved_routes)
            # Preset name (clock source is restored in _restore_clock_settings)
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
        # Preset may specify a routing clock source (device name for forwarding)
        clock = self.presets.get_clock_source(data)
        if clock:
            self.router.set_clock_source(clock)
        # Save to state
        self.state.set_preset(name)
        self.state.set_routes(self.router.dump_routes())

    def _init_launcher(self):
        """Initialize clip launcher — restore saved state or auto-create layers."""
        saved = self.state.get_launcher_state()
        if saved and saved.get("layers"):
            self.launcher.load_state(saved)
            logger.info(f"Launcher restored: {len(self.launcher.layers)} layers")
        else:
            # Auto-create one layer per output device, pre-seeding the device's
            # configured MIDI channel so the launcher doesn't need manual setup.
            for dev in self.registry.get_output_devices():
                self.launcher.add_layer(
                    name=dev.name,
                    destination=dev.name,
                    midi_channel=dev.midi_channel if dev.midi_channel else None,
                )
            logger.info(f"Launcher: auto-created {len(self.launcher.layers)} layers")

    def _on_external_clock_message(self, message) -> None:
        """
        Called by the router for every clock/start/stop/continue message from
        the designated clock source device (router already gates by source).
        """
        if message.type == "clock":
            self.clock_manager.on_midi_clock_tick()
            # 0xF8 broadcast is handled inside on_midi_clock_tick via _midi_clock_callback
        elif message.type == "start":
            self.clock_manager.on_transport_reset()
            self.launcher.on_transport_message(message)
            self._send_transport_to_outputs(message)
        elif message.type in ("stop", "continue"):
            self.launcher.on_transport_message(message)
            self._send_transport_to_outputs(message)

    def _restore_clock_settings(self):
        """Restore unified clock settings and per-module quantize from saved state."""
        # Unified clock (BPM + source)
        clock = self.state.get_clock()
        bpm = clock.get("bpm", 120.0)
        source = clock.get("source", "internal")
        self.clock_manager.set_bpm(bpm)
        self.clock_manager.set_source(source)
        if source != "internal":
            self.router.set_clock_source(source)
        logger.info(f"Clock restored: {bpm} BPM, source={source!r}")

        # Per-module quantize
        rec_clock = self.state.get_recorder_clock()
        if rec_clock:
            self.recorder.set_quantize(rec_clock.get("quantize", "free"))
            self.recorder.set_beats_per_bar(rec_clock.get("beats_per_bar", 4))

        loop_clock = self.state.get_looper_clock()
        if loop_clock:
            self.looper.set_quantize(loop_clock.get("quantize", "free"))
            self.looper.set_beats_per_bar(loop_clock.get("beats_per_bar", 4))

    def _get_output_device_names(self) -> list[str]:
        """Return list of output device names (for clock output)."""
        return [d.name for d in self.registry.get_output_devices()]

    def _persist(self):
        """Persist routes to disk."""
        self.state.set_routes(self.router.dump_routes())

    def _save_state(self):
        """Persist complete state to disk."""
        self.state.set_routes(self.router.dump_routes())
        # Unified clock state
        self.state.set_clock({
            "bpm": self.clock_manager.bpm,
            "source": self.clock_manager.source,
        })
        self.state.set_launcher_state(self.launcher.save_state())
        self.state.set_recorder_clock({
            "quantize": self.recorder._quantize,
            "beats_per_bar": self.recorder._beats_per_bar,
        })
        self.state.set_looper_clock({
            "quantize": self.looper._quantize,
            "beats_per_bar": self.looper._beats_per_bar,
        })
        logger.info("State saved")

    def _start_web_ui(self):
        """Start Flask web server in a separate process."""
        # Pre-populate shared state before Flask starts reading it
        self.bridge.state["midi_pid"] = os.getpid()
        self.bridge.state["wifi_config"] = self.wifi_config
        self.bridge.state["platform"] = self.platform
        self._update_shared_state()

        self._web_process = multiprocessing.Process(
            target=run_flask_process,
            args=(self.bridge, self.args.host, self.args.port),
            name="midi-box-web",
            daemon=True,
        )
        self._web_process.start()
        logger.info(f"Web UI process started (pid={self._web_process.pid})")

    # -------------------------------------------------------------------
    # Main Loop
    # -------------------------------------------------------------------

    def _main_loop(self):
        # USB MIDI messages arrive via _on_usb_midi_received (rtmidi callback thread).
        # HW MIDI messages arrive via _on_hw_midi_received (hw_midi read thread).
        # This loop only handles IPC commands, gadget polling, and periodic state pushes.
        last_state_update = 0.0
        while self._running:
            # Read from USB gadget (Mac → Pi in DAW mode; different mechanism from rtmidi)
            if self.gadget and self.mode == "daw":
                for msg in self.gadget.receive_from_host():
                    if not self._performance_mode and msg.type not in _TRANSPORT_TYPES:
                        self.midi_logger.log_input("Logic Pro", msg)
                    self.router.process_message("Logic Pro", msg)

            # Process commands from Flask process
            self._process_commands()

            # Push state snapshot to shared dict periodically
            now = time.monotonic()
            if now - last_state_update >= STATE_UPDATE_INTERVAL:
                self._update_shared_state()
                last_state_update = now

            time.sleep(0.001)

    # -------------------------------------------------------------------
    # IPC: Command processing
    # -------------------------------------------------------------------

    def _process_commands(self):
        """Drain the command queue and execute each command."""
        while True:
            try:
                cmd = self.bridge.cmd_queue.get_nowait()
            except Exception:
                break

            cmd_id = cmd["id"]
            action = cmd["action"]
            params = cmd.get("params", {})

            try:
                result = self._dispatch_command(action, params)
            except Exception as e:
                logger.error(f"Command error ({action}): {e}")
                result = {"ok": False, "error": str(e)}

            self.bridge.results[cmd_id] = result

    def _dispatch_command(self, action: str, params: dict) -> dict:
        """Execute a command from Flask and return a result dict."""

        # --- Routes ---
        if action == "route.add":
            from midi_filter import MidiFilter
            filt = MidiFilter.from_dict(params.get("filter", {}))
            route = self.router.add_route(
                source=params["from"],
                destination=params["to"],
                midi_filter=filt,
                name=params.get("name", ""),
            )
            self._persist()
            return {"ok": True, "route": route.name}

        elif action == "route.remove":
            ok = self.router.remove_route(params["from"], params["to"])
            self._persist()
            return {"ok": ok}

        elif action == "route.clear":
            self.router.clear_routes()
            self._persist()
            return {"ok": True}

        elif action == "route.toggle":
            for route in self.router.get_all_routes():
                if route.source == params["from"] and route.destination == params["to"]:
                    route.enabled = not route.enabled
                    self._persist()
                    return {"ok": True, "enabled": route.enabled}
            return {"ok": False}

        elif action == "route.load":
            self.router.load_routes(params["routes"])
            self._persist()
            return {"ok": True}

        # --- Devices ---
        elif action == "device.config":
            name = params["name"]
            block_transport = params.get("block_transport")
            if isinstance(block_transport, str):
                block_transport = block_transport.lower() in ("true", "1", "yes")
            ok = self.registry.update_device_config(
                name,
                direction=params.get("direction"),
                device_type=params.get("device_type"),
                midi_channel=params.get("midi_channel"),
                block_transport=block_transport if isinstance(block_transport, bool) else None,
            )
            if not ok:
                return {"ok": False, "error": "Device not found"}
            dev = self.registry.get_device(name)
            # Port override: allow user to manually select which ALSA port to use
            port_id = params.get("port_id", "").strip()
            existing_overrides = self.state.get_device_overrides()
            if port_id and dev.port_type == "usb":
                dev.port_id = port_id
            else:
                # Preserve any previously-saved port_id override
                port_id = existing_overrides.get(name, {}).get("port_id", "")
            self.state.set_device_override(name, {
                "direction": dev.direction,
                "device_type": dev.device_type,
                "midi_channel": dev.midi_channel,
                "port_id": port_id,
                "block_transport": dev.block_transport,
            })
            # Refresh clock output cache (block_transport may have changed)
            self._refresh_clock_outputs()
            self.registry.set_device_overrides(self.state.get_device_overrides())
            # Save display name if provided
            display_name = params.get("display_name", "").strip()
            if display_name and display_name != name:
                self.state.set_device_display_name(name, display_name)
            else:
                self.state.remove_device_display_name(name)
            return {"ok": True}

        elif action == "device.rescan":
            usb_names = [
                n for n, d in self.registry.get_all_devices().items()
                if d.port_type == "usb"
            ]
            for n in usb_names:
                self.registry.unregister_device(n)
            ports = self.alsa.rescan()
            for port in ports:
                self.registry.register_usb_device(port.port_name, port.port_name)
            return {"ok": True, "devices": list(self.registry.get_all_devices().keys())}

        # --- Presets ---
        elif action == "preset.load":
            name = params["name"]
            data = self.presets.load(name)
            if not data:
                return {"ok": False, "error": "not found"}
            routes = self.presets.get_routes(data)
            self.router.load_routes(routes)
            clock = self.presets.get_clock_source(data)
            self.router.set_clock_source(clock)
            self.state.set_preset(name)
            self._persist()
            return {"ok": True, "name": name, "routes": len(routes)}

        elif action == "preset.save":
            name = params.get("name", "custom")
            preset = {
                "name": params.get("display_name", name),
                "description": params.get("description", ""),
                "routes": self.router.dump_routes(),
                "clock_source": params.get("clock_source"),
            }
            ok = self.presets.save(name, preset)
            if ok:
                self.presets.current_preset = name
                self.state.set_preset(name)
            return {"ok": ok, "name": name}

        elif action == "preset.delete":
            deleted_name = params["name"]
            ok = self.presets.delete(deleted_name)
            if ok and self.presets.current_preset == deleted_name:
                self.presets.current_preset = None
                self.state.set_preset(None)
            return {"ok": ok}

        # --- Clock (unified) ---
        elif action == "clock.bpm":
            bpm = float(params.get("bpm", 120.0))
            self.clock_manager.set_bpm(bpm)
            self.state.set_clock({
                "bpm": self.clock_manager.bpm,
                "source": self.clock_manager.source,
            })
            return {"ok": True, "bpm": self.clock_manager.bpm}

        elif action == "clock.source":
            source = params.get("source", "internal")
            self.clock_manager.set_source(source)
            # Update router to gate MIDI clock from the right device
            self.router.set_clock_source(None if source == "internal" else source)
            self.state.set_clock({
                "bpm": self.clock_manager.bpm,
                "source": self.clock_manager.source,
            })
            return {"ok": True, "source": self.clock_manager.source}

        # --- Settings ---
        elif action == "settings.clock":
            # Legacy: redirect to unified clock.source
            source = params.get("source", "internal")
            self.clock_manager.set_source(source)
            self.router.set_clock_source(None if source == "internal" else source)
            self.state.set_clock({
                "bpm": self.clock_manager.bpm,
                "source": self.clock_manager.source,
            })
            return {"ok": True}

        # --- Monitor ---
        elif action == "monitor.clear":
            self.midi_logger.clear()
            return {"ok": True}

        elif action == "monitor.pause":
            self.midi_logger.pause()
            return {"ok": True, "paused": True}

        elif action == "monitor.resume":
            self.midi_logger.resume()
            return {"ok": True, "paused": False}

        # --- Performance Mode ---
        elif action == "performance.enable":
            self._performance_mode = True
            logging.getLogger().setLevel(logging.WARNING)
            self.bridge.state["performance_mode"] = True
            logger.warning("Performance mode ON — all logging suppressed")
            return {"ok": True}

        elif action == "performance.disable":
            self._performance_mode = False
            level = logging.DEBUG if self._verbose else logging.INFO
            logging.getLogger().setLevel(level)
            self.bridge.state["performance_mode"] = False
            logger.info("Performance mode OFF — logging resumed")
            return {"ok": True}

        # --- Quick Recorder ---
        elif action == "recorder.toggle":
            return self.recorder.toggle()
        elif action == "recorder.play":
            return self.recorder.play()
        elif action == "recorder.stop":
            return self.recorder.stop()
        elif action == "recorder.clear":
            return self.recorder.clear()
        elif action == "recorder.auto_play":
            self.recorder.set_auto_play(params.get("value", True))
            return {"ok": True}
        elif action == "recorder.save":
            return self.recorder.save(params.get("name"))
        elif action == "recorder.delete":
            return self.recorder.delete_recording(params.get("name", ""))
        elif action == "recorder.list":
            return {"ok": True, "recordings": self.recorder.list_recordings()}
        elif action == "recorder.get_path":
            path = self.recorder.get_recording_path(params.get("name", ""))
            return {"ok": path is not None, "path": path}

        elif action == "recorder.clock":
            if "quantize" in params:
                self.recorder.set_quantize(params["quantize"])
            if "beats_per_bar" in params:
                self.recorder.set_beats_per_bar(int(params["beats_per_bar"]))
            self.state.set_recorder_clock({
                "quantize": self.recorder._quantize,
                "beats_per_bar": self.recorder._beats_per_bar,
            })
            return {"ok": True}

        # --- Launcher ---
        elif action == "launcher.clock":
            # bpm changes go through the unified clock
            if "bpm" in params:
                bpm = float(params["bpm"])
                self.clock_manager.set_bpm(bpm)
                self.state.set_clock({
                    "bpm": self.clock_manager.bpm,
                    "source": self.clock_manager.source,
                })
            if "quantum" in params:
                self.launcher.set_quantum(params["quantum"])
            if "beats_per_bar" in params:
                self.launcher.set_beats_per_bar(int(params["beats_per_bar"]))
                self.clock_manager.set_beats_per_bar(int(params["beats_per_bar"]))
            self.state.set_launcher_state(self.launcher.save_state())
            return {"ok": True}

        elif action == "launcher.start":
            self.launcher.transport_start()
            self.clock_manager.on_transport_reset()
            self._send_transport_to_outputs(mido.Message("start"))
            return {"ok": True}

        elif action == "launcher.stop":
            self.launcher.transport_stop()
            self._send_transport_to_outputs(mido.Message("stop"))
            return {"ok": True}

        elif action == "launcher.add_layer":
            layer = self.launcher.add_layer(
                name=params.get("name", ""),
                destination=params.get("destination", ""),
                midi_channel=params.get("midi_channel"),
            )
            self.state.set_launcher_state(self.launcher.save_state())
            return {"ok": True, "layer_id": layer.layer_id}

        elif action == "launcher.remove_layer":
            ok = self.launcher.remove_layer(params["layer_id"])
            self.state.set_launcher_state(self.launcher.save_state())
            return {"ok": ok}

        elif action == "launcher.update_layer":
            self.launcher.update_layer(
                params["layer_id"],
                name=params.get("name"),
                destination=params.get("destination"),
                midi_channel=params.get("midi_channel"),
            )
            self.state.set_launcher_state(self.launcher.save_state())
            return {"ok": True}

        elif action == "launcher.assign_clip":
            ok = self.launcher.assign_clip(
                params["layer_id"], params["slot"],
                filename=params.get("filename", ""),
                name=params.get("name", ""),
                loop=params.get("loop", True),
            )
            self.state.set_launcher_state(self.launcher.save_state())
            return {"ok": ok}

        elif action == "launcher.remove_clip":
            ok = self.launcher.remove_clip(params["layer_id"], params["slot"])
            self.state.set_launcher_state(self.launcher.save_state())
            return {"ok": ok}

        elif action == "launcher.launch_clip":
            self.launcher.launch_clip(params["layer_id"], params["slot"])
            return {"ok": True}

        elif action == "launcher.stop_layer":
            self.launcher.stop_layer(params["layer_id"])
            return {"ok": True}

        elif action == "launcher.stop_all":
            self.launcher.stop_all()
            return {"ok": True}

        elif action == "launcher.upload":
            ok = self.launcher.upload(params["filename"], params["data"])
            return {"ok": ok}

        elif action == "launcher.delete_file":
            ok = self.launcher.delete_file(params["file"])
            return {"ok": ok}

        elif action == "launcher.launch_column":
            self.launcher.launch_column(params["slot"])
            return {"ok": True}

        elif action == "launcher.set_start_point":
            self.launcher.set_start_point(
                column=params.get("column"),
                layer_id=params.get("layer_id"),
                slot=params.get("slot"),
            )
            return {"ok": True}

        # --- Player ---
        elif action == "player.play":
            ok = self.player.play(
                params["file"], params["destination"],
                folder=params.get("folder"),
                loop=params.get("loop", False),
                tempo_factor=params.get("tempo", 1.0),
            )
            return {"ok": ok}

        elif action == "player.stop":
            self.player.stop()
            return {"ok": True}

        elif action == "player.pause":
            self.player.pause()
            return {"ok": True}

        elif action == "player.resume":
            self.player.resume()
            return {"ok": True}

        elif action == "player.set_loop":
            self.player.set_loop(params.get("loop", False))
            return {"ok": True}

        elif action == "player.set_tempo":
            self.player.set_tempo(params.get("tempo", 1.0))
            return {"ok": True}

        elif action == "player.upload":
            result = self.player.upload(
                params["filename"], params["data"],
                folder=params.get("folder"),
            )
            return result if isinstance(result, dict) else {"ok": result}

        elif action == "player.delete":
            ok = self.player.delete(params["file"], folder=params.get("folder"))
            return {"ok": ok}

        elif action == "player.list_files":
            return self.player.list_files(folder=params.get("folder"))

        elif action == "player.rename":
            return self.player.rename(
                params["old_name"], params["new_name"],
                folder=params.get("folder"),
            )

        elif action == "player.mkdir":
            return self.player.mkdir(params["name"])

        elif action == "player.rename_folder":
            return self.player.rename_folder(params["old_name"], params["new_name"])

        elif action == "player.delete_folder":
            return self.player.delete_folder(params["name"])

        elif action == "player.move":
            return self.player.move(
                params["filename"],
                params.get("src_folder"),
                params.get("dst_folder"),
            )

        # --- State management ---
        elif action == "state.export":
            return {"ok": True, "data": self.state.export_all()}

        elif action == "state.import":
            ok = self.state.import_all(params["data"])
            if ok:
                routes = self.state.get_routes()
                self.router.load_routes(routes)
                self.presets.current_preset = self.state.get_preset()
                # Restore unified clock
                clock = self.state.get_clock()
                source = clock.get("source", "internal")
                self.clock_manager.set_bpm(clock.get("bpm", 120.0))
                self.clock_manager.set_source(source)
                self.router.set_clock_source(None if source == "internal" else source)
            return {"ok": ok, "routes": len(self.state.get_routes()) if ok else 0}

        elif action == "state.reset":
            self.state.reset()
            self.router.clear_routes()
            self.presets.current_preset = None
            return {"ok": True}

        # --- Looper ---
        elif action == "looper.configure":
            return self.looper.configure(
                params["slot_id"],
                params.get("source", ""),
                params.get("destination", ""),
                params.get("midi_channel"),
            )

        elif action == "looper.record":
            return self.looper.record(params["slot_id"])

        elif action == "looper.play":
            return self.looper.play(params["slot_id"])

        elif action == "looper.stop":
            return self.looper.stop(params["slot_id"])

        elif action == "looper.clear":
            return self.looper.clear(params["slot_id"])

        elif action == "looper.clock":
            if "quantize" in params:
                self.looper.set_quantize(params["quantize"])
            if "beats_per_bar" in params:
                self.looper.set_beats_per_bar(int(params["beats_per_bar"]))
            self.state.set_looper_clock({
                "quantize": self.looper._quantize,
                "beats_per_bar": self.looper._beats_per_bar,
            })
            return {"ok": True}

        # --- MIDI Panic ---
        elif action == "midi.panic":
            self._send_panic()
            return {"ok": True}

        # --- Logs ---
        elif action == "logs.clear":
            self.log_buffer.clear()
            return {"ok": True}

        # --- System ---
        elif action == "system.restart":
            def _kill():
                time.sleep(0.4)
                os.kill(os.getpid(), signal.SIGTERM)
            threading.Thread(target=_kill, daemon=True).start()
            return {"ok": True, "message": "Restarting service..."}

        else:
            return {"ok": False, "error": f"Unknown action: {action}"}

    # -------------------------------------------------------------------
    # IPC: State push
    # -------------------------------------------------------------------

    def _update_shared_state(self):
        """Push a snapshot of the current MIDI state to the shared dict."""
        # Devices with activity
        devices = []
        for name, dev in self.registry.get_all_devices().items():
            a_in = self.router.get_activity(name, is_input=True)
            a_out = self.router.get_activity(name, is_input=False)
            devices.append({
                "name": name,
                "port_type": dev.port_type,
                "direction": dev.direction,
                "device_type": dev.device_type,
                "port_id": dev.port_id,
                "midi_channel": dev.midi_channel,
                "connected": dev.connected,
                "block_transport": dev.block_transport,
                "activity_in": a_in.is_active,
                "activity_out": a_out.is_active,
                "msg_count_in": a_in.message_count,
                "msg_count_out": a_out.message_count,
            })
        self.bridge.state["devices"] = devices

        # Activity summary for /api/poll
        self.bridge.state["activity"] = [
            {
                "name": d["name"],
                "active_in": d["activity_in"],
                "active_out": d["activity_out"],
                "count_in": d["msg_count_in"],
                "count_out": d["msg_count_out"],
            }
            for d in devices
        ]

        # Routes
        self.bridge.state["routes"] = self.router.dump_routes()

        # Mode, preset, unified clock
        self.bridge.state["mode"] = self.mode
        self.bridge.state["preset"] = self.presets.current_preset or "default"
        self.bridge.state["current_preset"] = self.presets.current_preset or "default"
        self.bridge.state["clock_source"] = self.router._clock_source  # legacy compat
        self.bridge.state["clock"] = self.clock_manager.get_status()

        # Quick recorder state
        self.bridge.state["recorder"] = self.recorder.get_status()

        # MIDI log + Python app log — skipped in performance mode to reduce IPC overhead
        self.bridge.state["performance_mode"] = self._performance_mode
        if not self._performance_mode:
            self.bridge.state["midi_log"] = self.midi_logger.get_entries(limit=100)
            self.bridge.state["midi_stats"] = self.midi_logger.get_stats()
            self.bridge.state["midi_paused"] = self.midi_logger.is_paused
            self.bridge.state["log_entries"] = self.log_buffer.get_entries(limit=200)

        # Launcher
        status = self.launcher.get_status()
        status["files"] = self.launcher.list_files()
        self.bridge.state["launcher"] = status
        self.bridge.state["launcher_poll"] = self.launcher.get_poll()

        # Player
        self.bridge.state["player"] = {
            "status": self.player.status,
            "files": self.player.list_files(),  # root-level {"folders":..., "files":...}
        }

        # Looper
        self.bridge.state["looper"] = self.looper.get_status()

        # All currently-open ALSA port names (for the port selector UI)
        with self.alsa._lock:
            self.bridge.state["raw_ports"] = sorted(self.alsa.ports.keys())

        # Device onboarding: which devices have no user-configured overrides yet
        overrides = self.state.get_device_overrides()
        self.bridge.state["unconfigured_devices"] = [
            name for name in self.registry.get_all_devices()
            if name not in overrides
        ]
        self.bridge.state["device_display_names"] = self.state.get_device_display_names()

        # RTP-MIDI
        self.bridge.state["rtp_midi"] = {
            "enabled":  self.rtp_midi is not None,
            "port":     self.rtp_midi.port if self.rtp_midi else 5004,
            "sessions": self.rtp_midi.active_sessions if self.rtp_midi else [],
        }

        # Preset list
        self.bridge.state["presets"] = self.presets.list_presets()

        # WiFi config (static, set once but keep in sync)
        self.bridge.state["wifi_config"] = self.wifi_config
        self.bridge.state["platform"] = self.platform

    # -------------------------------------------------------------------
    # Callbacks
    # -------------------------------------------------------------------

    def _on_usb_midi_received(self, port_name: str, message):
        """Called from rtmidi's thread immediately when a USB MIDI message arrives."""
        device = self.registry.find_by_port_id(port_name)
        source_name = device.name if device else port_name
        # Ignore messages from output-only devices (e.g. synths sending unsolicited clock)
        if device and device.direction == "out":
            return
        # Clock/transport messages are too frequent to log — they flood the monitor
        # ring buffer and add lock overhead on the hot receive path.
        if not self._performance_mode and message.type not in _TRANSPORT_TYPES:
            self.midi_logger.log_input(source_name, message)
        self.looper.on_midi_message(source_name, message)
        self.recorder.on_midi_message(source_name, message)
        self.router.process_message(source_name, message)

    def _set_realtime_priority(self):
        """Switch this thread to SCHED_FIFO real-time scheduling (Pi only).

        Requires either root or the systemd unit to set:
            LimitRTPRIO=70
            LimitMEMLOCK=infinity
        """
        if self.platform != "pi":
            return
        try:
            param = os.sched_param(sched_priority=70)
            os.sched_setscheduler(0, os.SCHED_FIFO, param)

            # Lock all current and future memory pages to eliminate page-fault spikes.
            import ctypes
            import ctypes.util
            libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
            MCL_CURRENT, MCL_FUTURE = 1, 2
            libc.mlockall(MCL_CURRENT | MCL_FUTURE)

            logger.info("Real-time scheduling active: SCHED_FIFO priority 70, memory locked")
        except PermissionError:
            logger.warning(
                "Could not set SCHED_FIFO — add to systemd unit: "
                "LimitRTPRIO=70 and LimitMEMLOCK=infinity"
            )
        except Exception as e:
            logger.warning(f"Real-time scheduling not available: {e}")

    def _send_midi(self, destination: str, message) -> bool:
        device = self.registry.get_device(destination)

        # Send to WiFi peers via RTP-MIDI
        if destination == "RTP-MIDI (WiFi)" and self.rtp_midi:
            ok = self.rtp_midi.send(message)
            if ok and not self._performance_mode and message.type not in _TRANSPORT_TYPES:
                self.midi_logger.log_output(destination, message)
            return ok

        # Send to Mac via gadget
        if destination in ("Logic Pro", "Mac"):
            if self.gadget:
                ok = self.gadget.send_to_host(message)
                if ok and not self._performance_mode and message.type not in _TRANSPORT_TYPES:
                    self.midi_logger.log_output(destination, message)
                return ok
            return False

        if not device:
            return False

        # Apply device-level channel: if the device is configured for a specific
        # MIDI channel (1-16), remap all channel messages to that channel before
        # sending. 0 means "all channels" (no remapping). mido uses 0-indexed
        # channels internally, so we subtract 1 from the user-facing 1-indexed value.
        if device.midi_channel and hasattr(message, "channel"):
            incoming_ch = message.channel + 1  # convert to 1-indexed for display
            if incoming_ch != device.midi_channel:
                logger.debug(
                    "Channel remap: %s received ch%d → forced to ch%d",
                    destination, incoming_ch, device.midi_channel,
                )
            message = message.copy(channel=device.midi_channel - 1)

        ok = False
        if device.port_type == "usb":
            t0 = time.monotonic()
            ok = self.alsa.send(device.port_id, message)
            dt = (time.monotonic() - t0) * 1000
            if message.type in ("note_on", "note_off") and dt > 1.0:
                _diag_logger.debug("SLOW SEND %.1fms  %s → %s  %s", dt, destination, message.type, message)
        elif device.port_type == "hardware" and self.hw:
            ok = self.hw.send(device.name, message)

        if not ok and message.type not in _TRANSPORT_TYPES:
            _diag_logger.debug("SEND FAIL  %s → %s  %s", destination, message.type, message)

        if ok and not self._performance_mode and message.type not in _TRANSPORT_TYPES:
            self.midi_logger.log_output(destination, message)
        return ok

    def _send_clock_to_outputs(self) -> None:
        """Send MIDI clock (0xF8) to every connected output device.
        Called at 24 PPQ by ClockManager for both internal and external sources.
        The clock source device itself is skipped to avoid echo.
        Uses pre-cached device list and message object to keep the hot path lean."""
        clock_source = self.clock_manager.source
        for name in self._clock_output_names:
            if name != clock_source:
                self._send_midi(name, _CLOCK_MSG)

    def _refresh_clock_outputs(self) -> None:
        """Rebuild the cached output device name list. Called at startup and on hotplug."""
        self._clock_output_names = [
            d.name for d in self.registry.get_output_devices()
            if not d.block_transport
        ]

    def _send_transport_to_outputs(self, message) -> None:
        """Broadcast a start/stop/continue message to all output devices."""
        clock_source = self.clock_manager.source
        for dev in self.registry.get_output_devices():
            if dev.name == clock_source:
                continue
            if dev.block_transport:
                _diag_logger.debug("TRANSPORT %s → %s  BLOCKED (block_transport)", message.type, dev.name)
                continue
            ok = self._send_midi(dev.name, message)
            _diag_logger.debug("TRANSPORT %s → %s  ok=%s", message.type, dev.name, ok)

    def _send_panic(self):
        """Send All Sound Off (CC 120) + All Notes Off (CC 123) on all 16 channels
        to every connected output device."""
        import mido
        outputs = [d.name for d in self.registry.get_output_devices()]
        for dest in outputs:
            for ch in range(16):
                self._send_midi(dest, mido.Message("control_change", channel=ch, control=120, value=0))
                self._send_midi(dest, mido.Message("control_change", channel=ch, control=123, value=0))
        logger.info(f"MIDI Panic: All Sound Off + All Notes Off sent to {len(outputs)} output(s)")

    def _on_hw_midi_received(self, port_name: str, message):
        device = self.registry.get_device(port_name)
        if device and device.direction == "out":
            return
        if not self._performance_mode and message.type not in _TRANSPORT_TYPES:
            self.midi_logger.log_input(port_name, message)
        self.looper.on_midi_message(port_name, message)
        self.recorder.on_midi_message(port_name, message)
        self.router.process_message(port_name, message)

    def _on_rtpmidi_received(self, message):
        """Called from the RTP-MIDI server thread when a WiFi MIDI message arrives."""
        source_name = "RTP-MIDI (WiFi)"
        if not self._performance_mode and message.type not in _TRANSPORT_TYPES:
            self.midi_logger.log_input(source_name, message)
        self.looper.on_midi_message(source_name, message)
        self.recorder.on_midi_message(source_name, message)
        self.router.process_message(source_name, message)

    def _on_pedal_press(self):
        """Called from GPIO interrupt thread when foot pedal is pressed."""
        result = self.recorder.toggle()
        logger.info(f"Pedal press → recorder {result.get('state')}")

    def _on_usb_device_connected(self, port_name: str, port):
        device = self.registry.register_usb_device(port.port_name, port_name)
        if device:
            logger.info(f"Hotplug: {device.name} connected (port: {port_name})")
            self._refresh_clock_outputs()

    def _on_usb_device_disconnected(self, port_name: str):
        device = self.registry.find_by_port_id(port_name)
        if device:
            dev_name = device.name
            self.registry.unregister_device(dev_name)
            logger.info(f"Hotplug: {dev_name} disconnected")
            # If this was the clock source, fall back to internal
            if self.clock_manager.source == dev_name:
                logger.warning(f"Clock source '{dev_name}' disconnected — switching to internal")
                self.clock_manager.set_source("internal")
                self.router.set_clock_source(None)
                self.state.set_clock({"bpm": self.clock_manager.bpm, "source": "internal"})
        else:
            self.registry.unregister_device(port_name)
            logger.info(f"Hotplug: {port_name} disconnected")
        self._refresh_clock_outputs()


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def main():
    # On Linux (Raspberry Pi), fork is the default and most efficient.
    # Set explicitly to avoid any ambiguity.
    if platform.system() == "Linux":
        multiprocessing.set_start_method("fork", force=True)

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
