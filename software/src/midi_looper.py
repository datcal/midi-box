"""
MIDI Looper — real-time loop recorder for MIDI Box.

4 independent loop slots. Each slot can:
  - Record incoming MIDI from any source device
  - Play back in a seamless loop to any destination device
  - Overdub: layer new notes on top while already playing
  - Clear: wipe all recorded data

Clock is provided by ClockManager (shared system BPM).  No per-module
BPM — all clock-dependent behaviour follows the unified system clock.

Supports clock-synced recording with quantization and count-in:
  - Quantize: free, 1/16, 1/8, 1/4, bar, 2bar, 4bar
  - Count-in: waits for next quantum boundary before recording starts
  - Quantized loop length: snaps first recording length to quantum boundary

Usage pattern (Ableton-style):
  1. Configure slot (source + destination)
  2. Press REC → count-in (if quantized) → starts recording
  3. Press REC again → stops recording, begins looping (length quantized)
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

INTERNAL_PPQ = 96

_FIXED_QUANTUM_TICKS = {
    "1/16": INTERNAL_PPQ // 4,   # 24
    "1/8":  INTERNAL_PPQ // 2,   # 48
    "1/4":  INTERNAL_PPQ,        # 96
}

VALID_QUANTIZE = ("free", "1/16", "1/8", "1/4", "bar", "2bar", "4bar")


def _quantum_ticks(quantize: str, beats_per_bar: int) -> int:
    """Return tick count for a quantum value. Returns 0 for 'free'."""
    if quantize == "free":
        return 0
    if quantize in _FIXED_QUANTUM_TICKS:
        return _FIXED_QUANTUM_TICKS[quantize]
    tpbar = INTERNAL_PPQ * beats_per_bar
    if quantize == "bar":
        return tpbar
    if quantize == "2bar":
        return tpbar * 2
    if quantize == "4bar":
        return tpbar * 4
    return 0


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

        # State machine: empty → count_in → recording → playing ↔ overdubbing → stopped
        self.state = "empty"

        self._events: list[tuple] = []     # (offset_seconds, mido.Message)
        self._overdub: list[tuple] = []    # accumulates during overdub pass
        self.length: float = 0.0           # loop duration in seconds

        self._record_start: float = 0.0
        # The playback worker signals itself through this event
        self._stop_event: Optional[threading.Event] = None

        # Count-in
        self._count_in_event = threading.Event()

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

    def stop_recording(self, quantize: str = "free", bpm: float = 120.0,
                       beats_per_bar: int = 4) -> bool:
        """Commit the current recording pass.  Returns True if the slot now
        has playable content."""
        if self.state == "recording":
            raw_length = time.monotonic() - self._record_start

            # Quantize the loop length
            if quantize != "free":
                qt = _quantum_ticks(quantize, beats_per_bar)
                if qt > 0 and bpm > 0:
                    tick_interval = 60.0 / (bpm * INTERNAL_PPQ)
                    elapsed_ticks = raw_length / tick_interval
                    quantized_ticks = ((int(elapsed_ticks) // qt) + 1) * qt
                    self.length = quantized_ticks * tick_interval
                else:
                    self.length = raw_length
            else:
                self.length = raw_length

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
        self._count_in_event.set()
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

    def __init__(self, clock_manager=None):
        self.slots: list[LoopSlot] = [LoopSlot(i) for i in range(NUM_SLOTS)]
        self._send_callback: Optional[Callable] = None
        self._threads: dict[int, threading.Thread] = {}
        self._stops:   dict[int, threading.Event]  = {}

        # Quantize settings (BPM comes from ClockManager)
        self._quantize = "free"
        self._beats_per_bar = 4
        self._clock_manager = clock_manager  # shared ClockManager

        # Clock position (updated by tick callback from ClockManager)
        self._tick = 0
        self._beat = 0
        self._bar = 0
        self._transport_running = False

    # ------------------------------------------------------------------
    # Quantize configuration
    # ------------------------------------------------------------------

    def set_quantize(self, quantize: str) -> None:
        if quantize in VALID_QUANTIZE:
            self._quantize = quantize

    def set_beats_per_bar(self, beats: int) -> None:
        self._beats_per_bar = max(1, min(16, beats))

    # ------------------------------------------------------------------
    # Tick callback (from ClockManager subscription)
    # ------------------------------------------------------------------

    def _on_tick(self, tick: int, beat: int, bar: int, running: bool) -> None:
        self._tick = tick
        self._beat = beat
        self._bar = bar
        self._transport_running = running

        qt = _quantum_ticks(self._quantize, self._beats_per_bar)
        if qt <= 0 or tick == 0:
            return

        if tick % qt == 0:
            for slot in self.slots:
                if slot.state == "count_in":
                    slot._count_in_event.set()

    def _subscribe_to_clock(self) -> None:
        if self._clock_manager:
            self._clock_manager.register_tick_subscriber(self._on_tick)

    def _unsubscribe_from_clock(self) -> None:
        if self._clock_manager:
            self._clock_manager.unregister_tick_subscriber(self._on_tick)

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
        """Toggle record: arm → count_in/record → stop+play → overdub → stop+play."""
        slot = self._get(slot_id)
        if not slot:
            return {"ok": False, "error": "Invalid slot"}
        if not slot.source or not slot.destination:
            return {"ok": False, "error": "Configure source and destination first"}

        if slot.state == "count_in":
            # Cancel count-in
            slot._count_in_event.set()
            slot.state = "empty"
            # Unsubscribe if no other slots need clock
            if not any(s.state == "count_in" for s in self.slots):
                self._unsubscribe_from_clock()
            return {"ok": True, "state": slot.state}

        if slot.state in ("empty", "stopped"):
            if self._quantize == "free":
                slot.start_recording()
            else:
                # Enter count-in
                slot.state = "count_in"
                slot._count_in_event.clear()
                self._subscribe_to_clock()
                # Start count-in wait in background
                t = threading.Thread(
                    target=self._count_in_worker, args=(slot,),
                    daemon=True, name=f"looper-{slot_id}-count-in",
                )
                t.start()

        elif slot.state == "playing":
            slot.start_recording()          # → overdubbing

        elif slot.state == "recording":
            bpm = self._clock_manager.bpm if self._clock_manager else 120.0
            had_content = slot.stop_recording(
                quantize=self._quantize, bpm=bpm,
                beats_per_bar=self._beats_per_bar,
            )
            if had_content:
                self._start_playback(slot)
            # Unsubscribe if no other slots need clock
            if not any(s.state in ("count_in", "recording", "overdubbing") for s in self.slots):
                self._unsubscribe_from_clock()

        elif slot.state == "overdubbing":
            bpm = self._clock_manager.bpm if self._clock_manager else 120.0
            slot.stop_recording(
                quantize=self._quantize, bpm=bpm,
                beats_per_bar=self._beats_per_bar,
            )

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
        if slot.state == "count_in":
            slot._count_in_event.set()
            slot.state = "empty"
            if not any(s.state == "count_in" for s in self.slots):
                self._unsubscribe_from_clock()
            return {"ok": True, "state": slot.state}
        self._stop_playback(slot)
        if slot.state == "recording":
            bpm = self._clock_manager.bpm if self._clock_manager else 120.0
            slot.stop_recording(
                quantize=self._quantize, bpm=bpm,
                beats_per_bar=self._beats_per_bar,
            )
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
        bpm = self._clock_manager.bpm if self._clock_manager else 120.0
        return {
            "slots": [s.get_status() for s in self.slots],
            "bpm": bpm,
            "quantize": self._quantize,
            "beats_per_bar": self._beats_per_bar,
            "beat": self._beat,
            "bar": self._bar,
            "tick": self._tick,
            "transport_running": self._transport_running,
        }

    def close(self):
        for slot in self.slots:
            self._stop_playback(slot)
        self._unsubscribe_from_clock()

    def _count_in_worker(self, slot: LoopSlot) -> None:
        """Wait for the count-in boundary, then start recording on slot."""
        triggered = slot._count_in_event.wait(timeout=30.0)
        if not triggered or slot.state != "count_in":
            if slot.state == "count_in":
                slot.state = "empty"
                logger.info(f"Looper slot {slot.slot_id}: count-in timed out")
            return
        slot.start_recording()
        logger.info(f"Looper slot {slot.slot_id}: count-in complete, recording")

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
