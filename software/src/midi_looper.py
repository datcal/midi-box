"""
MIDI Looper — real-time loop recorder for MIDI Box.

4 independent loop slots. Each slot can:
  - Record incoming MIDI from any source device
  - Play back in a seamless loop to any destination device
  - Overdub: layer new notes on top while already playing
  - Clear: wipe all recorded data

Usage pattern (Ableton-style):
  1. Configure slot (source + destination)
  2. Press REC → starts recording
  3. Press REC again → stops recording, begins looping
  4. Press REC while playing → enters overdub mode
  5. Press REC while overdubbing → commits overdub, keeps looping
  6. Press STOP → stop playback (keeps content)
  7. Press CLEAR → erase content

Integration:
  main.py calls on_midi_message() for EVERY incoming MIDI event so the
  looper can capture it during record/overdub.  The _send_callback is set
  to MidiBox._send_midi so the looper can route playback through the engine.
"""

import time
import threading
import logging
from typing import Optional, Callable

logger = logging.getLogger("midi-box.looper")

NUM_SLOTS = 4
MAX_LOOP_SECONDS = 120.0   # hard cap on a single loop recording


# ---------------------------------------------------------------------------
# LoopSlot
# ---------------------------------------------------------------------------

class LoopSlot:
    """A single record/play slot."""

    def __init__(self, slot_id: int):
        self.slot_id = slot_id
        self.source = ""
        self.destination = ""
        self.midi_channel: Optional[int] = None

        # State machine: empty → recording → playing ↔ overdubbing → stopped
        self.state = "empty"

        self._events: list[tuple] = []     # (offset_seconds, mido.Message)
        self._overdub: list[tuple] = []    # accumulates during overdub pass
        self.length: float = 0.0           # loop duration in seconds

        self._record_start: float = 0.0
        # The playback worker signals itself through this event
        self._stop_event: Optional[threading.Event] = None

    # ------------------------------------------------------------------
    # Recording helpers
    # ------------------------------------------------------------------

    def start_recording(self):
        if self.state == "playing":
            # Overdub: keep playing, start recording on top
            self.state = "overdubbing"
            self._overdub = []
        else:
            # Fresh recording
            self._events = []
            self._overdub = []
            self.length = 0.0
            self.state = "recording"
        self._record_start = time.monotonic()

    def stop_recording(self) -> bool:
        """Commit the current recording pass.  Returns True if the slot now
        has playable content."""
        if self.state == "recording":
            self.length = time.monotonic() - self._record_start
            if self.length < 0.1 or not self._events:
                self._events = []
                self.length = 0.0
                self.state = "empty"
                return False
            self.state = "playing"
            return True

        elif self.state == "overdubbing":
            # Merge overdub events, sort by time offset, trim to loop length
            merged = self._events + self._overdub
            merged.sort(key=lambda e: e[0])
            self._events = [(t, m) for t, m in merged if t < self.length]
            self._overdub = []
            self.state = "playing"
            return True

        return False

    def record_event(self, message):
        """Called for every incoming MIDI message while recording/overdubbing."""
        if self.state not in ("recording", "overdubbing"):
            return
        offset = time.monotonic() - self._record_start
        if self.state == "overdubbing":
            offset = offset % self.length if self.length else 0.0
            self._overdub.append((offset, message))
        elif offset <= MAX_LOOP_SECONDS:
            self._events.append((offset, message))

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def clear(self):
        if self._stop_event:
            self._stop_event.set()
        self.state = "empty"
        self._events = []
        self._overdub = []
        self.length = 0.0

    def snapshot_events(self) -> list[tuple]:
        """Return a stable copy of events for the playback worker."""
        return list(self._events)

    def get_status(self) -> dict:
        return {
            "slot_id":     self.slot_id,
            "source":      self.source,
            "destination": self.destination,
            "midi_channel": self.midi_channel,
            "state":       self.state,
            "length":      round(self.length, 2),
            "event_count": len(self._events),
        }


# ---------------------------------------------------------------------------
# MidiLooper
# ---------------------------------------------------------------------------

class MidiLooper:
    """Manages NUM_SLOTS independent loop slots."""

    def __init__(self):
        self.slots: list[LoopSlot] = [LoopSlot(i) for i in range(NUM_SLOTS)]
        self._send_callback: Optional[Callable] = None
        self._threads: dict[int, threading.Thread] = {}
        self._stops:   dict[int, threading.Event]  = {}

    # ------------------------------------------------------------------
    # Incoming MIDI feed (called by main.py on every message)
    # ------------------------------------------------------------------

    def on_midi_message(self, source: str, message):
        for slot in self.slots:
            if slot.source == source and slot.state in ("recording", "overdubbing"):
                slot.record_event(message)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def configure(self, slot_id: int, source: str, destination: str,
                  midi_channel: Optional[int] = None) -> dict:
        slot = self._get(slot_id)
        if not slot:
            return {"ok": False, "error": "Invalid slot"}
        slot.source      = source
        slot.destination = destination
        slot.midi_channel = midi_channel or None
        return {"ok": True}

    def record(self, slot_id: int) -> dict:
        """Toggle record: arm → record → stop+play → overdub → stop+play."""
        slot = self._get(slot_id)
        if not slot:
            return {"ok": False, "error": "Invalid slot"}
        if not slot.source or not slot.destination:
            return {"ok": False, "error": "Configure source and destination first"}

        if slot.state in ("empty", "stopped"):
            slot.start_recording()
        elif slot.state == "playing":
            slot.start_recording()          # → overdubbing
        elif slot.state == "recording":
            had_content = slot.stop_recording()
            if had_content:
                self._start_playback(slot)
        elif slot.state == "overdubbing":
            slot.stop_recording()           # merges, stays playing
        return {"ok": True, "state": slot.state}

    def play(self, slot_id: int) -> dict:
        slot = self._get(slot_id)
        if not slot:
            return {"ok": False, "error": "Invalid slot"}
        if slot.state == "stopped" and slot._events:
            slot.state = "playing"
            self._start_playback(slot)
            return {"ok": True, "state": slot.state}
        return {"ok": False, "error": f"Cannot play in state '{slot.state}'"}

    def stop(self, slot_id: int) -> dict:
        slot = self._get(slot_id)
        if not slot:
            return {"ok": False, "error": "Invalid slot"}
        self._stop_playback(slot)
        if slot.state == "recording":
            slot.stop_recording()
            slot.state = "stopped" if slot._events else "empty"
        elif slot.state in ("playing", "overdubbing"):
            slot.state = "stopped"
        return {"ok": True, "state": slot.state}

    def clear(self, slot_id: int) -> dict:
        slot = self._get(slot_id)
        if not slot:
            return {"ok": False, "error": "Invalid slot"}
        self._stop_playback(slot)
        slot.clear()
        return {"ok": True}

    def get_status(self) -> dict:
        return {"slots": [s.get_status() for s in self.slots]}

    def close(self):
        for slot in self.slots:
            self._stop_playback(slot)

    # ------------------------------------------------------------------
    # Playback internals
    # ------------------------------------------------------------------

    def _start_playback(self, slot: LoopSlot):
        self._stop_playback(slot)
        stop_ev = threading.Event()
        slot._stop_event = stop_ev
        self._stops[slot.slot_id] = stop_ev
        t = threading.Thread(
            target=self._playback_worker,
            args=(slot, stop_ev),
            daemon=True,
            name=f"looper-{slot.slot_id}",
        )
        self._threads[slot.slot_id] = t
        t.start()

    def _stop_playback(self, slot: LoopSlot):
        ev = self._stops.pop(slot.slot_id, None)
        if ev:
            ev.set()
        t = self._threads.pop(slot.slot_id, None)
        if t and t.is_alive():
            t.join(timeout=0.5)

    def _playback_worker(self, slot: LoopSlot, stop_ev: threading.Event):
        while not stop_ev.is_set() and slot.state in ("playing", "overdubbing"):
            loop_start = time.monotonic()
            events = slot.snapshot_events()   # stable copy

            for offset, message in events:
                wait = (loop_start + offset) - time.monotonic()
                if wait > 0 and stop_ev.wait(wait):
                    return
                if stop_ev.is_set() or slot.state not in ("playing", "overdubbing"):
                    return
                if self._send_callback:
                    msg = message
                    if slot.midi_channel and hasattr(message, "channel"):
                        try:
                            msg = message.copy(channel=slot.midi_channel - 1)
                        except Exception:
                            pass
                    self._send_callback(slot.destination, msg)

            # Sleep until end of loop, then iterate
            remaining = (loop_start + slot.length) - time.monotonic()
            if remaining > 0:
                stop_ev.wait(remaining)

    def _get(self, slot_id: int) -> Optional[LoopSlot]:
        return self.slots[slot_id] if 0 <= slot_id < len(self.slots) else None
