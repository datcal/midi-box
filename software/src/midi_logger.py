"""
MIDI Message Logger - Captures MIDI messages for the web UI live view.
Thread-safe ring buffer with timestamps.
"""

import time
import threading
from collections import deque
from dataclasses import dataclass, asdict


@dataclass
class LogEntry:
    timestamp: float
    source: str
    destination: str  # empty if just received (not yet routed)
    msg_type: str
    channel: int  # -1 for non-channel messages
    data: str  # Human-readable message data
    raw: str  # Hex bytes
    direction: str  # "in", "out", or "routed"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["time_str"] = time.strftime("%H:%M:%S", time.localtime(self.timestamp))
        d["time_ms"] = f"{(self.timestamp % 1) * 1000:.0f}"
        return d


class MidiLogger:
    def __init__(self, max_entries: int = 500):
        self.max_entries = max_entries
        self._entries: deque[LogEntry] = deque(maxlen=max_entries)
        self._lock = threading.Lock()
        self._listeners: list = []  # Callbacks for real-time push
        self._counter = 0
        self._paused = False

    def log_input(self, source: str, message) -> LogEntry:
        """Log a received MIDI message."""
        entry = self._create_entry(source, "", message, "in")
        self._add(entry)
        return entry

    def log_output(self, destination: str, message) -> LogEntry:
        """Log a sent MIDI message."""
        entry = self._create_entry("", destination, message, "out")
        self._add(entry)
        return entry

    def log_routed(self, source: str, destination: str, message) -> LogEntry:
        """Log a routed MIDI message (source -> destination)."""
        entry = self._create_entry(source, destination, message, "routed")
        self._add(entry)
        return entry

    def _create_entry(self, source: str, destination: str, message, direction: str) -> LogEntry:
        msg_type = message.type if hasattr(message, "type") else "unknown"
        channel = (message.channel + 1) if hasattr(message, "channel") else -1
        data = self._format_message(message)
        raw = message.bin().hex(" ") if hasattr(message, "bin") else ""

        return LogEntry(
            timestamp=time.time(),
            source=source,
            destination=destination,
            msg_type=msg_type,
            channel=channel,
            data=data,
            raw=raw,
            direction=direction,
        )

    def _format_message(self, msg) -> str:
        """Create a human-readable description of a MIDI message."""
        t = msg.type if hasattr(msg, "type") else "?"

        if t == "note_on":
            return f"Note ON  {self._note_name(msg.note)} vel={msg.velocity}"
        elif t == "note_off":
            return f"Note OFF {self._note_name(msg.note)}"
        elif t == "control_change":
            return f"CC {msg.control} = {msg.value}"
        elif t == "program_change":
            return f"Program {msg.program}"
        elif t == "pitchwheel":
            return f"Pitch {msg.pitch}"
        elif t == "aftertouch":
            return f"Aftertouch {msg.value}"
        elif t == "polytouch":
            return f"Poly AT {self._note_name(msg.note)} = {msg.value}"
        elif t == "clock":
            return "Clock"
        elif t == "start":
            return "Start"
        elif t == "stop":
            return "Stop"
        elif t == "continue":
            return "Continue"
        elif t == "sysex":
            data_hex = " ".join(f"{b:02X}" for b in msg.data[:8])
            suffix = "..." if len(msg.data) > 8 else ""
            return f"SysEx [{len(msg.data)} bytes] {data_hex}{suffix}"
        else:
            return str(msg)

    def _note_name(self, note: int) -> str:
        names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        octave = (note // 12) - 1
        return f"{names[note % 12]}{octave}({note})"

    def _add(self, entry: LogEntry):
        if self._paused:
            return
        with self._lock:
            self._entries.append(entry)
            self._counter += 1
        # Notify real-time listeners
        for listener in self._listeners:
            try:
                listener(entry)
            except Exception:
                pass

    def get_entries(self, limit: int = 100, offset: int = 0) -> list[dict]:
        """Get recent log entries as dicts (for JSON serialization)."""
        with self._lock:
            entries = list(self._entries)
        # Most recent first
        entries.reverse()
        sliced = entries[offset:offset + limit]
        return [e.to_dict() for e in sliced]

    def get_stats(self) -> dict:
        """Get summary statistics."""
        with self._lock:
            entries = list(self._entries)

        if not entries:
            return {"total": 0, "sources": {}, "types": {}}

        sources = {}
        types = {}
        for e in entries:
            src = e.source or e.destination
            sources[src] = sources.get(src, 0) + 1
            types[e.msg_type] = types.get(e.msg_type, 0) + 1

        return {
            "total": self._counter,
            "buffer_size": len(entries),
            "sources": sources,
            "types": types,
        }

    def clear(self):
        with self._lock:
            self._entries.clear()
        self._counter = 0

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    @property
    def is_paused(self) -> bool:
        return self._paused

    def add_listener(self, callback):
        """Add a real-time listener (for WebSocket push)."""
        self._listeners.append(callback)

    def remove_listener(self, callback):
        self._listeners = [l for l in self._listeners if l is not callback]
