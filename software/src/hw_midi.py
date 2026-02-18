"""
Hardware MIDI Layer - Manages 5-pin DIN MIDI via SC16IS752 UARTs and Pi native UART.
Communicates over serial at 31250 baud (MIDI standard).
"""

import threading
import logging
from pathlib import Path

import serial
import mido

logger = logging.getLogger("midi-box.hw")

MIDI_BAUD = 31250


class HardwareMidiPort:
    """A single hardware MIDI port (one serial connection)."""

    def __init__(self, device_path: str, name: str, direction: str = "out"):
        self.device_path = device_path
        self.name = name
        self.direction = direction  # "in", "out", or "both"
        self.serial: serial.Serial | None = None
        self._parser = mido.Parser()

    def open(self) -> bool:
        try:
            self.serial = serial.Serial(
                port=self.device_path,
                baudrate=MIDI_BAUD,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0,  # Non-blocking reads
            )
            logger.info(f"Opened hardware MIDI port: {self.name} ({self.device_path})")
            return True
        except serial.SerialException as e:
            logger.error(f"Failed to open {self.device_path}: {e}")
            return False

    def close(self):
        if self.serial and self.serial.is_open:
            self.serial.close()
            logger.debug(f"Closed hardware MIDI port: {self.name}")

    @property
    def is_open(self) -> bool:
        return self.serial is not None and self.serial.is_open

    def send(self, message: mido.Message) -> bool:
        """Send a MIDI message out this port."""
        if self.direction == "in":
            return False
        if not self.is_open:
            return False
        try:
            self.serial.write(message.bin())
            return True
        except serial.SerialException as e:
            logger.error(f"Send error on {self.name}: {e}")
            return False

    def receive(self) -> list[mido.Message]:
        """Read and parse any pending MIDI messages from this port."""
        if self.direction == "out":
            return []
        if not self.is_open:
            return []

        messages = []
        try:
            data = self.serial.read(self.serial.in_waiting or 1)
            if data:
                self._parser.feed(data)
                while self._parser.pending():
                    messages.append(self._parser.get_message())
        except serial.SerialException as e:
            logger.error(f"Receive error on {self.name}: {e}")

        return messages

    def send_raw(self, data: bytes) -> bool:
        """Send raw bytes (for sysex or testing)."""
        if not self.is_open:
            return False
        try:
            self.serial.write(data)
            return True
        except serial.SerialException as e:
            logger.error(f"Raw send error on {self.name}: {e}")
            return False


class HardwareMidi:
    """Manages all hardware MIDI ports."""

    # Default SC16IS752 serial devices on Raspberry Pi
    DEFAULT_PORTS = [
        ("/dev/ttySC0", "DIN Port 1", "out"),   # SC16IS752 #1, Channel A
        ("/dev/ttySC1", "DIN Port 2", "out"),   # SC16IS752 #1, Channel B
        ("/dev/ttySC2", "DIN Port 3", "out"),   # SC16IS752 #2, Channel A
        ("/dev/ttySC3", "DIN Port 4", "out"),   # SC16IS752 #2, Channel B
        ("/dev/ttyAMA0", "DIN Port 5", "both"), # Pi native UART
    ]

    def __init__(self):
        self.ports: dict[str, HardwareMidiPort] = {}
        self._read_thread: threading.Thread | None = None
        self._running = False
        self._message_callback = None

    def scan_ports(self) -> list[tuple[str, str, str]]:
        """Check which hardware serial ports actually exist."""
        available = []
        for device_path, default_name, direction in self.DEFAULT_PORTS:
            if Path(device_path).exists():
                available.append((device_path, default_name, direction))
                logger.debug(f"Found hardware port: {device_path}")
            else:
                logger.debug(f"Hardware port not found: {device_path}")
        return available

    def open_all(self, port_config: dict[str, dict] = None) -> list[HardwareMidiPort]:
        """
        Open all available hardware MIDI ports.
        port_config maps device path basenames to {name, direction} overrides.
        """
        opened = []
        for device_path, default_name, default_dir in self.scan_ports():
            basename = Path(device_path).name

            # Apply config overrides if provided
            if port_config and basename in port_config:
                cfg = port_config[basename]
                name = cfg.get("name", default_name)
                direction = cfg.get("direction", default_dir)
            else:
                name = default_name
                direction = default_dir

            port = HardwareMidiPort(device_path, name, direction)
            if port.open():
                self.ports[name] = port
                opened.append(port)

        logger.info(f"Opened {len(opened)} hardware MIDI ports")
        return opened

    def send(self, port_name: str, message: mido.Message) -> bool:
        port = self.ports.get(port_name)
        if port:
            return port.send(message)
        logger.warning(f"Unknown hardware port: {port_name}")
        return False

    def start_reading(self, callback):
        """
        Start a background thread that reads all input-capable hardware ports
        and calls callback(port_name, message) for each received message.
        """
        self._message_callback = callback
        self._running = True
        self._read_thread = threading.Thread(
            target=self._read_loop,
            daemon=True,
        )
        self._read_thread.start()
        logger.info("Hardware MIDI read thread started")

    def stop_reading(self):
        self._running = False
        if self._read_thread:
            self._read_thread.join(timeout=5)

    def _read_loop(self):
        input_ports = [
            p for p in self.ports.values()
            if p.direction in ("in", "both") and p.is_open
        ]

        while self._running:
            for port in input_ports:
                messages = port.receive()
                for msg in messages:
                    if self._message_callback:
                        self._message_callback(port.name, msg)

    def get_output_ports(self) -> list[str]:
        return [
            name for name, p in self.ports.items()
            if p.direction in ("out", "both")
        ]

    def get_input_ports(self) -> list[str]:
        return [
            name for name, p in self.ports.items()
            if p.direction in ("in", "both")
        ]

    def close_all(self):
        self.stop_reading()
        for port in self.ports.values():
            port.close()
        self.ports.clear()
        logger.info("All hardware MIDI ports closed")
