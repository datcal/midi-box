"""
RTP-MIDI (Apple MIDI) Session Server for MIDI Box.

Implements RFC 6295 + the Apple session protocol so Mac / iOS devices can
connect over WiFi and send/receive MIDI without a USB cable.

How it appears on the Mac:
  Open Audio MIDI Setup → Window → Show MIDI Studio → Network
  The device "MIDI Box" will appear automatically via Bonjour (mDNS).
  Click "Connect" → done.  It works exactly like a USB MIDI device.

Architecture:
  Two UDP sockets: control port (default 5004) + data port (5005).
  Control port: session management (IN / OK / BY / CK).
  Data port:    RTP-MIDI packets + clock sync.

  Both sockets are served by background daemon threads.
  Received MIDI is delivered via on_message callback (→ routing engine).
  Outgoing MIDI is sent to all currently connected sessions.

Dependencies:
  Required: none (uses stdlib socket + struct only)
  Optional: zeroconf>=0.47  (for mDNS auto-discovery)
            Install with:  pip install zeroconf
            Without it the server still works; users must enter the IP
            manually in Audio MIDI Setup.
"""

import os
import socket
import struct
import threading
import time
import random
import logging
from typing import Optional, Callable

logger = logging.getLogger("midi-box.rtpmidi")

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------

_MAGIC          = b'\xff\xff'
_CMD_INVITE     = b'IN'
_CMD_ACCEPT     = b'OK'
_CMD_DECLINE    = b'NO'
_CMD_GOODBYE    = b'BY'
_CMD_CLOCK      = b'CK'
_PROTOCOL_VER   = 2
_RTP_PAYLOAD_PT = 97        # dynamic PT for MIDI (RFC 4695)
_RECV_BUF       = 4096


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class _Session:
    def __init__(self, peer_ssrc: int, peer_token: int, peer_ip: str,
                 peer_ctrl_port: int):
        self.peer_ssrc      = peer_ssrc
        self.peer_token     = peer_token
        self.peer_ip        = peer_ip
        self.peer_ctrl_port = peer_ctrl_port
        self.peer_data_port: Optional[int] = None
        self.connected      = False            # True after data-port handshake
        self.name           = ""
        self.created        = time.monotonic()

    @property
    def data_addr(self):
        return (self.peer_ip, self.peer_data_port) if self.peer_data_port else None


# ---------------------------------------------------------------------------
# RtpMidiServer
# ---------------------------------------------------------------------------

class RtpMidiServer:
    """
    Apple MIDI session server.

    Typical usage::

        srv = RtpMidiServer(name="MIDI Box", port=5004)
        srv.set_on_message(lambda msg: router.process_message("RTP-MIDI", msg))
        srv.start()
        ...
        srv.send(mido_message)   # send to all connected sessions
        srv.stop()
    """

    def __init__(self, name: str = "MIDI Box", port: int = 5004):
        self.name      = name
        self.port      = port                 # control port
        self.data_port = port + 1             # data port
        self.ssrc      = random.randint(1, 0xFFFF_FFFF)
        self._seq      = random.randint(0, 0xFFFF)

        self._sessions: dict[str, _Session] = {}  # keyed by peer IP
        self._lock     = threading.Lock()

        self._on_message: Optional[Callable] = None

        self._ctrl_sock: Optional[socket.socket] = None
        self._data_sock: Optional[socket.socket] = None
        self._running   = False
        self._zeroconf  = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_on_message(self, callback: Callable):
        """Set callback invoked on every received MIDI message: callback(mido.Message)."""
        self._on_message = callback

    def start(self) -> bool:
        """Bind ports and start receive threads.  Returns False on failure."""
        try:
            self._ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._ctrl_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._ctrl_sock.bind(("", self.port))
            self._ctrl_sock.settimeout(1.0)

            self._data_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._data_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._data_sock.bind(("", self.data_port))
            self._data_sock.settimeout(1.0)
        except OSError as exc:
            logger.error(f"RTP-MIDI: cannot bind ports {self.port}/{self.data_port}: {exc}")
            return False

        self._running = True

        threading.Thread(target=self._recv_loop, args=(self._ctrl_sock, True),
                         daemon=True, name="rtpmidi-ctrl").start()
        threading.Thread(target=self._recv_loop, args=(self._data_sock, False),
                         daemon=True, name="rtpmidi-data").start()

        self._advertise()
        logger.info(f"RTP-MIDI: server '{self.name}' listening on "
                    f":{self.port}/{self.data_port}")
        return True

    def stop(self):
        self._running = False
        self._unadvertise()
        for sock in (self._ctrl_sock, self._data_sock):
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass

    def send(self, message) -> bool:
        """Send a MIDI message to all connected sessions."""
        with self._lock:
            sessions = [s for s in self._sessions.values() if s.connected]
        if not sessions:
            return False

        packet = self._make_rtp_packet(message)
        if not packet:
            return False

        sent = False
        for sess in sessions:
            if sess.data_addr and self._data_sock:
                try:
                    self._data_sock.sendto(packet, sess.data_addr)
                    sent = True
                except OSError as exc:
                    logger.debug(f"RTP-MIDI: send error to {sess.peer_ip}: {exc}")
        return sent

    @property
    def active_sessions(self) -> list[dict]:
        with self._lock:
            return [
                {"name": s.name, "address": s.peer_ip, "connected": s.connected}
                for s in self._sessions.values()
            ]

    # ------------------------------------------------------------------
    # Receive loop
    # ------------------------------------------------------------------

    def _recv_loop(self, sock: socket.socket, is_ctrl: bool):
        while self._running:
            try:
                data, addr = sock.recvfrom(_RECV_BUF)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                continue
            if len(data) >= 4 and data[:2] == _MAGIC:
                self._handle_session(data, addr, sock, is_ctrl)
            elif not is_ctrl and len(data) >= 12:
                self._handle_rtp(data, addr)

    # ------------------------------------------------------------------
    # Session protocol
    # ------------------------------------------------------------------

    def _handle_session(self, data: bytes, addr, sock: socket.socket, is_ctrl: bool):
        cmd = data[2:4]
        if   cmd == _CMD_INVITE:  self._on_invite(data, addr, sock, is_ctrl)
        elif cmd == _CMD_GOODBYE: self._on_goodbye(data, addr)
        elif cmd == _CMD_CLOCK:   self._on_clock(data, addr, sock)

    def _on_invite(self, data: bytes, addr, sock: socket.socket, is_ctrl: bool):
        if len(data) < 16:
            return
        try:
            token = struct.unpack_from(">I", data, 8)[0]
            ssrc  = struct.unpack_from(">I", data, 12)[0]
            name  = data[16:].split(b"\x00")[0].decode("utf-8", errors="replace")
        except struct.error:
            return

        ip = addr[0]

        if is_ctrl:
            # First handshake — create pending session
            sess = _Session(ssrc, token, ip, addr[1])
            sess.name = name or ip
            with self._lock:
                self._sessions[ip] = sess
            logger.info(f"RTP-MIDI: invitation from '{sess.name}' ({ip})")
        else:
            # Second handshake (data port) — mark session connected
            with self._lock:
                sess = self._sessions.get(ip)
            if sess:
                sess.peer_data_port = addr[1]
                sess.connected = True
                logger.info(f"RTP-MIDI: '{sess.name}' connected")
            else:
                # Session was never initiated on ctrl port — accept anyway
                sess = _Session(ssrc, token, ip, addr[1])
                sess.peer_data_port = addr[1]
                sess.connected = True
                sess.name = name or ip
                with self._lock:
                    self._sessions[ip] = sess

        # Reply with OK on whichever port received the invite
        reply = _MAGIC + _CMD_ACCEPT + struct.pack(">I", _PROTOCOL_VER)
        reply += struct.pack(">I", token) + struct.pack(">I", self.ssrc)
        reply += self.name.encode("utf-8") + b"\x00"
        try:
            sock.sendto(reply, addr)
        except OSError:
            pass

    def _on_goodbye(self, data: bytes, addr):
        ip = addr[0]
        with self._lock:
            sess = self._sessions.pop(ip, None)
        if sess:
            logger.info(f"RTP-MIDI: '{sess.name}' disconnected")

    def _on_clock(self, data: bytes, addr, sock: socket.socket):
        """Apple 3-way clock sync.  We handle count=0 (respond with count=1)."""
        if len(data) < 36:
            return
        try:
            count = data[8]
            ts1   = struct.unpack_from(">Q", data, 12)[0]
        except (struct.error, IndexError):
            return

        if count == 0:
            now = int(time.monotonic() * 10_000)   # 100 µs units
            reply = (_MAGIC + _CMD_CLOCK
                     + struct.pack(">I", self.ssrc)
                     + struct.pack(">B", 1) + b"\x00\x00\x00"
                     + struct.pack(">Q", ts1)
                     + struct.pack(">Q", now)
                     + struct.pack(">Q", 0))
            try:
                sock.sendto(reply, addr)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # RTP-MIDI receive
    # ------------------------------------------------------------------

    def _handle_rtp(self, data: bytes, addr):
        """Parse an RTP-MIDI packet and dispatch MIDI messages."""
        # Validate RTP header
        if (data[0] >> 6) != 2:          # V must be 2
            return
        pt = data[1] & 0x7F
        if pt != _RTP_PAYLOAD_PT:
            return

        payload = data[12:]               # skip 12-byte RTP header
        if not payload:
            return

        for msg in self._parse_midi_payload(payload):
            if self._on_message:
                try:
                    self._on_message(msg)
                except Exception:
                    pass

    def _parse_midi_payload(self, payload: bytes) -> list:
        """Extract mido.Message objects from an RTP-MIDI command section.

        RTP-MIDI command section layout:
          Byte 0 (short header) or Bytes 0-1 (long header):
            Bit 7 (B flag): 1 = long header (12-bit length), 0 = short (4-bit)
            Bit 6 (J flag): 1 = journal section follows (we ignore it)
            Bit 5 (Z flag): 1 = delta-time precedes first MIDI command
            Bit 4 (P flag): 1 = status byte present in first command (phantom)
          Low bits: length of MIDI command section
        """
        import mido

        if not payload:
            return []

        b0 = payload[0]
        has_bflag = b0 & 0x80           # long header
        has_delta = b0 & 0x20           # Z flag — delta-times present

        if has_bflag:
            if len(payload) < 2:
                return []
            length   = ((b0 & 0x0F) << 8) | payload[1]
            data_off = 2
        else:
            length   = b0 & 0x0F
            data_off = 1

        if length == 0:
            return []

        midi_bytes = payload[data_off: data_off + length]
        messages   = []
        i          = 0
        running_status = 0

        def _skip_delta():
            """Skip a variable-length delta-time (VLQ). Returns new index."""
            nonlocal i
            while i < len(midi_bytes) and midi_bytes[i] & 0x80:
                i += 1           # continuation bytes (bit 7 set)
            if i < len(midi_bytes):
                i += 1           # final byte (bit 7 clear)

        # Skip initial delta-time if Z flag set
        if has_delta:
            _skip_delta()

        while i < len(midi_bytes):
            b = midi_bytes[i]

            try:
                if b >= 0x80 and b <= 0xEF:
                    # Channel message with status byte
                    status   = b
                    running_status = status
                    msg_type = status & 0xF0
                    need = 2 if msg_type in (0x80, 0x90, 0xA0, 0xB0, 0xE0) else 1
                    end  = i + 1 + need
                    if end > len(midi_bytes):
                        break
                    d = midi_bytes[i:end]
                    if all(byte < 0x80 for byte in d[1:]):
                        msg = mido.Message.from_bytes(list(d))
                        messages.append(msg)
                    i = end
                elif b < 0x80 and running_status:
                    # Running status — reuse previous status byte
                    msg_type = running_status & 0xF0
                    need = 2 if msg_type in (0x80, 0x90, 0xA0, 0xB0, 0xE0) else 1
                    end  = i + need
                    if end > len(midi_bytes):
                        break
                    d = bytes([running_status]) + midi_bytes[i:end]
                    if all(byte < 0x80 for byte in d[1:]):
                        msg = mido.Message.from_bytes(list(d))
                        messages.append(msg)
                    i = end
                elif b == 0xF8:
                    messages.append(mido.Message("clock"))
                    running_status = 0
                    i += 1
                elif b == 0xFA:
                    messages.append(mido.Message("start"))
                    running_status = 0
                    i += 1
                elif b == 0xFB:
                    messages.append(mido.Message("continue"))
                    running_status = 0
                    i += 1
                elif b == 0xFC:
                    messages.append(mido.Message("stop"))
                    running_status = 0
                    i += 1
                else:
                    running_status = 0
                    i += 1   # unknown system byte — skip
            except Exception:
                i += 1
                continue

            # Between MIDI commands, skip the inter-command delta-time
            if has_delta and i < len(midi_bytes):
                _skip_delta()

        return messages

    # ------------------------------------------------------------------
    # RTP-MIDI send
    # ------------------------------------------------------------------

    def _make_rtp_packet(self, message) -> bytes:
        """Encode a mido.Message as a minimal RTP-MIDI packet."""
        try:
            midi_bytes = bytes(message.bytes())
        except Exception:
            return b""
        if not midi_bytes:
            return b""

        self._seq = (self._seq + 1) & 0xFFFF
        ts = int(time.monotonic() * 10_000) & 0xFFFF_FFFF   # 100 µs units

        rtp_hdr = struct.pack(">BBHI",
                              0x80,                   # V=2 P=0 X=0 CC=0
                              _RTP_PAYLOAD_PT & 0x7F, # M=0 PT=97
                              self._seq,
                              ts) + struct.pack(">I", self.ssrc)

        # Short B-header: no delta-time, 4-bit length
        length = len(midi_bytes)
        if length <= 15:
            b_hdr = bytes([length])
        else:
            b_hdr = bytes([0x80 | (length >> 8), length & 0xFF])

        return rtp_hdr + b_hdr + midi_bytes

    # ------------------------------------------------------------------
    # mDNS advertisement
    # ------------------------------------------------------------------

    def _advertise(self):
        try:
            from zeroconf import Zeroconf, ServiceInfo
            self._zeroconf = Zeroconf()
            addrs = self._local_ips()
            info = ServiceInfo(
                "_apple-midi._udp.local.",
                f"{self.name}._apple-midi._udp.local.",
                addresses=[socket.inet_aton(ip) for ip in addrs],
                port=self.port,
                properties={},
            )
            self._zeroconf.register_service(info)
            self._zconf_info = info
            logger.info(f"RTP-MIDI: Bonjour registered '{self.name}' on {addrs}:{self.port}")
        except ImportError:
            logger.info("RTP-MIDI: zeroconf not installed — Bonjour unavailable. "
                        "Add server manually in Audio MIDI Setup using the Pi's IP.")
        except Exception as exc:
            logger.warning(f"RTP-MIDI: Bonjour registration failed: {exc}")

    def _unadvertise(self):
        if self._zeroconf:
            try:
                if hasattr(self, "_zconf_info"):
                    self._zeroconf.unregister_service(self._zconf_info)
                self._zeroconf.close()
            except Exception:
                pass

    def _local_ips(self) -> list[str]:
        """Return all non-loopback IPv4 addresses (wlan0, uap0, etc.)."""
        import subprocess
        addrs = set()
        try:
            # Use hostname -I on Linux (space-separated IPs)
            out = subprocess.check_output(["hostname", "-I"], timeout=2,
                                          stderr=subprocess.DEVNULL).decode().strip()
            for ip in out.split():
                if ":" not in ip and ip != "127.0.0.1":  # skip IPv6 and loopback
                    addrs.add(ip)
        except Exception:
            pass
        if not addrs:
            # Fallback: connect to public DNS to find default route IP
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.connect(("8.8.8.8", 80))
                    addrs.add(s.getsockname()[0])
            except OSError:
                addrs.add("127.0.0.1")
        return sorted(addrs)
