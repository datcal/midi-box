"""
Hardware MIDI Layer - Manages 5-pin DIN MIDI OUT via Pi native UARTs.
All 4 DIN ports are MIDI OUT only. No SC16IS752 bridge chips needed.
Communicates over serial at 31250 baud (MIDI standard).

Required /boot/firmware/config.txt overlays:
    dtoverlay=disable-bt    # frees UART0 (GPIO 14)
    dtoverlay=uart3         # GPIO 4  → /dev/ttyAMA2
    dtoverlay=uart4         # GPIO 8  → /dev/ttyAMA3
    dtoverlay=uart5         # GPIO 12 → /dev/ttyAMA4
"""

import array
import fcntl
import logging
import termios
import threading
import time
from pathlib import Path

import serial
import mido

logger = logging.getLogger("midi-box.hw")

MIDI_BAUD = 31250

# Linux ioctl constants for setting non-standard baud rates.
# The standard termios API only supports pre-defined speeds; MIDI's 31250
# baud requires the BOTHER flag via the termios2 (TCGETS2/TCSETS2) interface.
_BOTHER = 0o010000
_TCGETS2 = 0x802C542A
_TCSETS2 = 0x402C542B


def _set_custom_baudrate(fd: int, baudrate: int):
    """Set a non-standard baud rate on a serial port using TCSETS2 ioctl."""
    buf = array.array("i", [0] * 64)
    fcntl.ioctl(fd, _TCGETS2, buf)
    buf[2] = (buf[2] & ~termios.CBAUD) | _BOTHER  # cflag
    buf[9] = baudrate   # ispeed
    buf[10] = baudrate  # ospeed
    fcntl.ioctl(fd, _TCSETS2, buf)


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
            # pyserial's standard termios path silently fails to set the
            # non-standard 31250 baud on Pi's PL011 UART.  Force it via
            # the TCSETS2 ioctl which supports arbitrary baud rates.
            _set_custom_baudrate(self.serial.fd, MIDI_BAUD)
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

    def __init__(self):
        self.ports: dict[str, HardwareMidiPort] = {}
        self._read_thread: threading.Thread | None = None
        self._running = False
        self._message_callback = None

    def open_all(self, port_config: dict[str, dict]) -> list[HardwareMidiPort]:
        """
        Open all hardware MIDI ports defined in devices.yaml.
        port_config maps device basenames (e.g. "ttyAMA0") to config dicts.
        """
        opened = []
        for basename, cfg in port_config.items():
            device_path = f"/dev/{basename}"
            name = cfg.get("name", basename)
            direction = cfg.get("direction", "out")

            if not Path(device_path).exists():
                logger.warning(f"Hardware port not found: {device_path} — check dtoverlay and serial console config")
                continue

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
            got_any = False
            for port in input_ports:
                messages = port.receive()
                for msg in messages:
                    got_any = True
                    if self._message_callback:
                        self._message_callback(port.name, msg)
            # Avoid busy-spin when no messages are arriving
            if not got_any:
                time.sleep(0.0005)

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
