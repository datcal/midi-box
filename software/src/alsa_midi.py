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


@dataclass
class AlsaPort:
    name: str
    port_name: str
    input_port: mido.ports.BaseInput | None = None
    output_port: mido.ports.BaseOutput | None = None


class AlsaMidi:
    def __init__(self, on_device_connected=None, on_device_disconnected=None):
        self.ports: dict[str, AlsaPort] = {}
        self.on_device_connected = on_device_connected
        self.on_device_disconnected = on_device_disconnected
        self._poll_thread: threading.Thread | None = None
        self._running = False

    def scan_devices(self) -> list[str]:
        """Scan for available MIDI input and output ports."""
        try:
            inputs = set(mido.get_input_names())
            outputs = set(mido.get_output_names())
        except Exception as e:
            logger.warning(f"ALSA not available (no MIDI devices): {e}")
            return []
        all_ports = inputs | outputs

        # Filter out system ports (like "Midi Through")
        devices = [
            p for p in all_ports
            if "through" not in p.lower() and "midi box" not in p.lower()
        ]

        logger.info(f"Found {len(devices)} MIDI devices")
        for d in sorted(devices):
            directions = []
            if d in inputs:
                directions.append("IN")
            if d in outputs:
                directions.append("OUT")
            logger.debug(f"  {d} [{'/'.join(directions)}]")

        return sorted(devices)

    def open_port(self, port_name: str) -> AlsaPort | None:
        """Open input and/or output for a named MIDI port."""
        if port_name in self.ports:
            return self.ports[port_name]

        inputs = mido.get_input_names()
        outputs = mido.get_output_names()

        port = AlsaPort(name=port_name, port_name=port_name)

        try:
            if port_name in inputs:
                port.input_port = mido.open_input(port_name)
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
        port = self.ports.get(port_name)
        if port and port.output_port:
            try:
                port.output_port.send(message)
                return True
            except Exception as e:
                logger.error(f"Send failed on {port_name}: {e}")
        return False

    def receive(self, port_name: str, timeout: float = 0) -> mido.Message | None:
        """Receive a MIDI message from a named port (non-blocking by default)."""
        port = self.ports.get(port_name)
        if port and port.input_port:
            if timeout > 0:
                return port.input_port.poll()  # Non-blocking
            # Check for pending messages
            for msg in port.input_port.iter_pending():
                return msg
        return None

    def get_input_ports(self) -> list[str]:
        return [name for name, p in self.ports.items() if p.input_port]

    def get_output_ports(self) -> list[str]:
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
        known_devices = set(self.ports.keys())

        while self._running:
            try:
                current = set(self.scan_devices())

                # New devices
                for name in current - known_devices:
                    logger.info(f"Device connected: {name}")
                    port = self.open_port(name)
                    if port and self.on_device_connected:
                        self.on_device_connected(name, port)

                # Removed devices
                for name in known_devices - current:
                    logger.info(f"Device disconnected: {name}")
                    self._close_port(name)
                    if self.on_device_disconnected:
                        self.on_device_disconnected(name)

                known_devices = current
            except Exception as e:
                logger.error(f"Hotplug monitor error: {e}")

            time.sleep(interval)

    def _close_port(self, port_name: str):
        port = self.ports.pop(port_name, None)
        if port:
            try:
                if port.input_port:
                    port.input_port.close()
                if port.output_port:
                    port.output_port.close()
            except Exception as e:
                logger.debug(f"Error closing {port_name}: {e}")

    def close_all(self):
        """Close all open ports."""
        self.stop_hotplug_monitor()
        for name in list(self.ports.keys()):
            self._close_port(name)
        logger.info("All MIDI ports closed")
