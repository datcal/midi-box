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
import time
import logging
import argparse
import threading
import multiprocessing

from device_registry import DeviceRegistry
from alsa_midi import AlsaMidi
from router import MidiRouter
from preset_manager import PresetManager
from midi_logger import MidiLogger
from midi_player import MidiPlayer
from clip_launcher import ClipLauncher
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
        )
        self.hw = None       # HardwareMidi, Pi only
        self.gadget = None   # GadgetMidi, Pi only
        self.router = MidiRouter()
        self.presets = PresetManager()
        self.state = StateManager()
        self.midi_logger = MidiLogger(max_entries=500)
        self.player = MidiPlayer()
        self.launcher = ClipLauncher()
        self.log_buffer = LogBuffer()
        self.mode = "standalone"
        self.wifi_config = self._load_wifi_config()
        self._running = False
        self._web_process = None
        self.bridge = None

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
        self.player._send_callback = self._send_midi
        self.launcher._send_callback = self._send_midi
        self.launcher._output_devices_callback = self._get_output_device_names
        self.router._clock_callback = self.launcher.on_clock_message

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

        # Start clip launcher clock
        self.launcher.start()

        # Create IPC bridge and start web UI in a separate process
        self.bridge = IpcBridge()
        self._start_web_ui()

        # Main loop
        self._running = True
        logger.info("Routing engine running. Press Ctrl+C to stop.")
        logger.info(f"Web UI: http://localhost:{self.args.port}")
        self._main_loop()

    def stop(self):
        logger.info("Shutting down...")
        self.player.stop()
        self.launcher.stop()
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

    def _init_launcher(self):
        """Initialize clip launcher — restore saved state or auto-create layers."""
        saved = self.state.get_launcher_state()
        if saved and saved.get("layers"):
            self.launcher.load_state(saved)
            logger.info(f"Launcher restored: {len(self.launcher.layers)} layers")
        else:
            # Auto-create one layer per output device
            for dev in self.registry.get_output_devices():
                self.launcher.add_layer(
                    name=dev.name,
                    destination=dev.name,
                )
            logger.info(f"Launcher: auto-created {len(self.launcher.layers)} layers")

    def _get_output_device_names(self) -> list[str]:
        """Return list of output device names (for clock output)."""
        return [d.name for d in self.registry.get_output_devices()]

    def _persist(self):
        """Persist routes and clock source to disk."""
        self.state.set_routes(self.router.dump_routes())
        self.state.set_clock_source(self.router._clock_source)

    def _save_state(self):
        """Persist complete state to disk."""
        self.state.set_routes(self.router.dump_routes())
        self.state.set_clock_source(self.router._clock_source)
        self.state.set_launcher_state(self.launcher.save_state())
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
        last_state_update = 0.0
        while self._running:
            # Read from all USB MIDI input ports
            for port_name in self.alsa.get_input_ports():
                msg = self.alsa.receive(port_name)
                if msg:
                    device = self.registry.find_by_port_id(port_name)
                    source_name = device.name if device else port_name
                    self.midi_logger.log_input(source_name, msg)
                    self.router.process_message(source_name, msg)

            # Read from USB gadget (Mac → Pi)
            if self.gadget and self.mode == "daw":
                for msg in self.gadget.receive_from_host():
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
            ok = self.registry.update_device_config(
                name,
                direction=params.get("direction"),
                device_type=params.get("device_type"),
                midi_channel=params.get("midi_channel"),
            )
            if not ok:
                return {"ok": False, "error": "Device not found"}
            dev = self.registry.get_device(name)
            self.state.set_device_override(name, {
                "direction": dev.direction,
                "device_type": dev.device_type,
                "midi_channel": dev.midi_channel,
            })
            self.registry.set_device_overrides(self.state.get_device_overrides())
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
            return {"ok": ok, "name": name}

        elif action == "preset.delete":
            ok = self.presets.delete(params["name"])
            return {"ok": ok}

        # --- Settings ---
        elif action == "settings.clock":
            self.router.set_clock_source(params.get("source"))
            self._persist()
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

        # --- Launcher ---
        elif action == "launcher.clock":
            if "mode" in params:
                self.launcher.set_clock_mode(params["mode"])
            if "bpm" in params:
                self.launcher.set_bpm(float(params["bpm"]))
            if "quantum" in params:
                self.launcher.set_quantum(params["quantum"])
            if "beats_per_bar" in params:
                self.launcher.set_beats_per_bar(int(params["beats_per_bar"]))
            self.state.set_launcher_state(self.launcher.save_state())
            return {"ok": True}

        elif action == "launcher.start":
            self.launcher.transport_start()
            return {"ok": True}

        elif action == "launcher.stop":
            self.launcher.transport_stop()
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

        # --- Player ---
        elif action == "player.play":
            ok = self.player.play(
                params["file"], params["destination"],
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
            ok = self.player.upload(params["filename"], params["data"])
            return {"ok": ok}

        elif action == "player.delete":
            ok = self.player.delete(params["file"])
            return {"ok": ok}

        # --- State management ---
        elif action == "state.export":
            return {"ok": True, "data": self.state.export_all()}

        elif action == "state.import":
            ok = self.state.import_all(params["data"])
            if ok:
                routes = self.state.get_routes()
                self.router.load_routes(routes)
                clock = self.state.get_clock_source()
                self.router.set_clock_source(clock)
                self.presets.current_preset = self.state.get_preset()
            return {"ok": ok, "routes": len(self.state.get_routes()) if ok else 0}

        elif action == "state.reset":
            self.state.reset()
            self.router.clear_routes()
            self.presets.current_preset = None
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

        # Mode, preset, clock
        self.bridge.state["mode"] = self.mode
        self.bridge.state["preset"] = self.presets.current_preset or "default"
        self.bridge.state["current_preset"] = self.presets.current_preset or "default"
        self.bridge.state["clock_source"] = self.router._clock_source

        # MIDI log
        self.bridge.state["midi_log"] = self.midi_logger.get_entries(limit=100)
        self.bridge.state["midi_stats"] = self.midi_logger.get_stats()
        self.bridge.state["midi_paused"] = self.midi_logger.is_paused

        # Python app log
        self.bridge.state["log_entries"] = self.log_buffer.get_entries(limit=200)

        # Launcher
        status = self.launcher.get_status()
        status["files"] = self.launcher.list_files()
        self.bridge.state["launcher"] = status
        self.bridge.state["launcher_poll"] = self.launcher.get_poll()

        # Player
        self.bridge.state["player"] = {
            "status": self.player.status,
            "files": self.player.list_files(),
        }

        # Preset list
        self.bridge.state["presets"] = self.presets.list_presets()

        # WiFi config (static, set once but keep in sync)
        self.bridge.state["wifi_config"] = self.wifi_config
        self.bridge.state["platform"] = self.platform

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

    def _on_usb_device_connected(self, port_name: str, port):
        device = self.registry.register_usb_device(port.port_name, port_name)
        if device:
            logger.info(f"Hotplug: {device.name} connected (port: {port_name})")

    def _on_usb_device_disconnected(self, port_name: str):
        device = self.registry.find_by_port_id(port_name)
        if device:
            self.registry.unregister_device(device.name)
            logger.info(f"Hotplug: {device.name} disconnected")
        else:
            self.registry.unregister_device(port_name)
            logger.info(f"Hotplug: {port_name} disconnected")


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
