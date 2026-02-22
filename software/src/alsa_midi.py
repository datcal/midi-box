"""
ALSA MIDI Layer - Manages USB MIDI devices via ALSA sequencer using rtmidi.
Handles device enumeration, hotplug detection, and message I/O.
"""

import time
import threading
import logging
from dataclasses import dataclass

import mido

logger = logging.getLogger("midi-box.alsa")


class _MockPort:
    """Null MIDI port used in --mock mode (no hardware required)."""
    def send(self, msg): pass
    def poll(self): return None
    def iter_pending(self): return iter([])
    def close(self): pass


@dataclass
class AlsaPort:
    name: str
    port_name: str
    input_port: mido.ports.BaseInput | None = None
    output_port: mido.ports.BaseOutput | None = None


class AlsaMidi:
    def __init__(self, on_device_connected=None, on_device_disconnected=None, on_message=None):
        self.ports: dict[str, AlsaPort] = {}
        self.on_device_connected = on_device_connected
        self.on_device_disconnected = on_device_disconnected
        self._on_message = on_message  # callback(port_name, msg) — fired from rtmidi's thread
        self._poll_thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()

    def _make_port_callback(self, port_name: str):
        """Return a mido-compatible callback that tags messages with the port name."""
        def cb(msg):
            self._on_message(port_name, msg)
        return cb

    def scan_devices(self) -> list[str]:
        """Scan for available MIDI input and output ports."""
        try:
            inputs = set(mido.get_input_names())
            outputs = set(mido.get_output_names())
        except Exception as e:
            logger.warning(f"ALSA not available (no MIDI devices): {e}")
            return []
        all_ports = inputs | outputs

        # Filter out system ports and our own rtmidi loopback clients.
        # RtMidiIn/RtMidiOut clients are created by python-rtmidi itself each
        # time we open a port; they appear in ALSA and trigger the hotplug
        # monitor, causing an exponential port-creation loop if not excluded.
        devices = [
            p for p in all_ports
            if "through" not in p.lower()
            and "midi box" not in p.lower()
            and "rtmidi" not in p.lower()
        ]

        def _port_sort_key(name):
            # Prefer standard MIDI ports over DAW/control-surface ports.
            # This ensures the MIDI port registers first when a device exposes
            # multiple ports (e.g. KeyLab mkII 88 MIDI vs KeyLab mkII 88 DAW).
            lower = name.lower()
            for kw in (" daw", " control"):
                if kw in lower:
                    return (1, name)
            return (0, name)

        devices = sorted(devices, key=_port_sort_key)

        logger.debug(f"Scan found {len(devices)} MIDI devices")
        for d in devices:
            directions = []
            if d in inputs:
                directions.append("IN")
            if d in outputs:
                directions.append("OUT")
            logger.debug(f"  {d} [{'/'.join(directions)}]")

        return devices

    def open_port(self, port_name: str) -> AlsaPort | None:
        """Open input and/or output for a named MIDI port."""
        with self._lock:
            if port_name in self.ports:
                return self.ports[port_name]

        inputs = mido.get_input_names()
        outputs = mido.get_output_names()

        port = AlsaPort(name=port_name, port_name=port_name)

        try:
            if port_name in inputs:
                cb = self._make_port_callback(port_name) if self._on_message else None
                port.input_port = mido.open_input(port_name, callback=cb)
                logger.debug(f"Opened input: {port_name}")
        except Exception as e:
            logger.error(f"Failed to open input {port_name}: {e}")

        try:
            if port_name in outputs:
                port.output_port = mido.open_output(port_name)
                logger.debug(f"Opened output: {port_name}")
        except Exception as e:
            logger.error(f"Failed to open output {port_name}: {e}")

        if port.input_port or port.output_port:
            with self._lock:
                self.ports[port_name] = port
            return port

        logger.warning(f"Could not open any ports for: {port_name}")
        return None

    def open_all(self) -> list[AlsaPort]:
        """Open all available MIDI devices."""
        opened = []
        for name in self.scan_devices():
            port = self.open_port(name)
            if port:
                opened.append(port)
        return opened

    def send(self, port_name: str, message: mido.Message) -> bool:
        """Send a MIDI message to a named port."""
        with self._lock:
            port = self.ports.get(port_name)
        if port and port.output_port:
            try:
                port.output_port.send(message)
                return True
            except Exception as e:
                logger.error(f"Send failed on {port_name}: {e}")
        return False

    def receive(self, port_name: str) -> list[mido.Message]:
        """Drain all pending MIDI messages from a named port (non-blocking)."""
        with self._lock:
            port = self.ports.get(port_name)
        if port and port.input_port:
            try:
                return list(port.input_port.iter_pending())
            except Exception as e:
                logger.debug(f"Receive error on {port_name}: {e}")
        return []

    def get_input_ports(self) -> list[str]:
        with self._lock:
            return [name for name, p in self.ports.items() if p.input_port]

    def get_output_ports(self) -> list[str]:
        with self._lock:
            return [name for name, p in self.ports.items() if p.output_port]

    def start_hotplug_monitor(self, interval: float = 2.0):
        """Start a background thread that polls for device changes."""
        self._running = True
        self._poll_thread = threading.Thread(
            target=self._hotplug_loop,
            args=(interval,),
            daemon=True,
        )
        self._poll_thread.start()
        logger.info("Hotplug monitor started")

    def stop_hotplug_monitor(self):
        self._running = False
        if self._poll_thread:
            self._poll_thread.join(timeout=5)

    def _hotplug_loop(self, interval: float):
        with self._lock:
            known_ports = set(self.ports.keys())

        while self._running:
            try:
                current_ports = set(self.scan_devices())

                # New devices (ports that appeared)
                new_ports = current_ports - known_ports
                for port_name in new_ports:
                    try:
                        logger.info(f"Hotplug: device connected — {port_name}")
                        port = self.open_port(port_name)
                        if port and self.on_device_connected:
                            self.on_device_connected(port_name, port)
                    except Exception as e:
                        logger.error(f"Hotplug: failed to open new device {port_name}: {e}")

                # Removed devices (ports that disappeared)
                gone_ports = known_ports - current_ports
                for port_name in gone_ports:
                    try:
                        logger.info(f"Hotplug: device disconnected — {port_name}")
                        self._close_port(port_name)
                        if self.on_device_disconnected:
                            self.on_device_disconnected(port_name)
                    except Exception as e:
                        logger.error(f"Hotplug: error handling disconnect for {port_name}: {e}")

                known_ports = current_ports

            except Exception as e:
                logger.error(f"Hotplug monitor error: {e}")

            time.sleep(interval)

    def _close_port(self, port_name: str):
        with self._lock:
            port = self.ports.pop(port_name, None)
        if port:
            try:
                if port.input_port:
                    port.input_port.close()
            except Exception as e:
                logger.debug(f"Error closing input {port_name}: {e}")
            try:
                if port.output_port:
                    port.output_port.close()
            except Exception as e:
                logger.debug(f"Error closing output {port_name}: {e}")

    def rescan(self) -> list[AlsaPort]:
        """Full rescan: close all ports and reopen everything.
        Use this when hotplug detection misses changes."""
        logger.info("Full MIDI rescan...")

        # Close all existing ports
        with self._lock:
            port_names = list(self.ports.keys())
        for name in port_names:
            self._close_port(name)

        # Open all discovered devices
        return self.open_all()

    def open_mock_devices(self, names: list[str]) -> list[AlsaPort]:
        """Create fake ports for all names (--mock mode, no hardware needed)."""
        ports = []
        for name in names:
            port = AlsaPort(
                name=name,
                port_name=name,
                input_port=_MockPort(),
                output_port=_MockPort(),
            )
            with self._lock:
                self.ports[name] = port
            ports.append(port)
        logger.info(f"Mock mode: {len(ports)} virtual devices created")
        return ports

    def close_all(self):
        """Close all open ports."""
        self.stop_hotplug_monitor()
        with self._lock:
            names = list(self.ports.keys())
        for name in names:
            self._close_port(name)
        logger.info("All MIDI ports closed")
