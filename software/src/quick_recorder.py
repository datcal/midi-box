"""
Quick Recorder — live MIDI capture with DAW-style step view.

Records ALL hardware MIDI input simultaneously (USB, DIN, RTP-MIDI).
MIDI Player and looper playback are excluded automatically because they
call _send_midi directly and never enter the hardware input callbacks.

Playback fires events through router.process_message so all existing
routing rules apply — no separate destination selection needed.

Supports clock-synced recording with BPM, quantization, and count-in:
  - Clock source: standalone (own BPM), launcher (sync to clip launcher),
    or external (MIDI clock from hardware)
  - Quantize: free, 1/16, 1/8, 1/4, bar, 2bar, 4bar
  - Count-in: waits for next quantum boundary before recording starts
  - Quantized loop length: snaps recording length to quantum boundary

State machine:
  idle → count_in → recording → stopped (if auto_play=False)
                              → playing (if auto_play=True)
  idle → recording (if quantize=free, skips count_in)
  stopped → playing (play command)
  playing → stopped (stop command)
  any    → idle    (clear command)
"""

import os
import json
import time
import threading
import logging
from datetime import datetime
from typing import Optional, Callable

import mido

logger = logging.getLogger("midi-box.recorder")

_NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_SKIP_TYPES = {"clock", "active_sensing", "sysex", "start", "stop", "continue",
               "song_select", "songpos", "quarter_frame", "tune_request", "reset"}

TICKS_PER_BEAT = 480
DEFAULT_TEMPO  = 500_000   # µs per beat = 120 BPM
MAX_RECENT     = 50        # events kept in status for UI display

INTERNAL_PPQ = 96

# Quantum values to tick counts (at 96 PPQ). bar/2bar/4bar depend on beats_per_bar.
_FIXED_QUANTUM_TICKS = {
    "1/16": INTERNAL_PPQ // 4,   # 24
    "1/8":  INTERNAL_PPQ // 2,   # 48
    "1/4":  INTERNAL_PPQ,        # 96
}

VALID_QUANTIZE = ("free", "1/16", "1/8", "1/4", "bar", "2bar", "4bar")


def _note_name(n: int) -> str:
    return _NOTES[n % 12] + str(n // 12 - 1)


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


class QuickRecorder:
    """Single-slot live recorder with MIDI file save/export."""

    def __init__(self, recordings_dir: str = "data/recordings"):
        self._events: list[tuple] = []   # (offset_sec, source, mido.Message)
        self._state = "idle"
        self._length = 0.0
        self._record_start = 0.0
        self._auto_play = True
        self._router_callback: Optional[Callable] = None  # set to router.process_message
        self._thread: Optional[threading.Thread] = None
        self._stop_event: Optional[threading.Event] = None
        self._lock = threading.Lock()
        self._recordings_dir = recordings_dir
        os.makedirs(recordings_dir, exist_ok=True)

        # Clock / quantize settings
        self._clock_source = "standalone"   # "standalone", "launcher", "external"
        self._bpm = 120.0
        self._quantize = "free"
        self._beats_per_bar = 4
        self._launcher = None               # reference to ClipLauncher (set from main.py)

        # Clock position (updated by tick callback or standalone clock)
        self._tick = 0
        self._beat = 0
        self._bar = 0
        self._transport_running = False
        self._record_start_tick = 0

        # Standalone clock thread
        self._clock_thread: Optional[threading.Thread] = None
        self._clock_running = False
        self._next_tick_time = 0.0

        # Count-in event — set when quantum boundary is reached
        self._count_in_event = threading.Event()

    # ------------------------------------------------------------------
    # Clock / quantize configuration
    # ------------------------------------------------------------------

    def set_clock_source(self, source: str) -> None:
        if source not in ("standalone", "launcher", "external"):
            return
        old = self._clock_source
        self._clock_source = source
        if old != source:
            self._stop_standalone_clock()
        logger.info(f"Recorder clock source: {source}")

    def set_bpm(self, bpm: float) -> None:
        self._bpm = max(20.0, min(300.0, bpm))

    def set_quantize(self, quantize: str) -> None:
        if quantize in VALID_QUANTIZE:
            self._quantize = quantize

    def set_beats_per_bar(self, beats: int) -> None:
        self._beats_per_bar = max(1, min(16, beats))

    # ------------------------------------------------------------------
    # Standalone clock (own BPM, independent of launcher)
    # ------------------------------------------------------------------

    def _start_standalone_clock(self) -> None:
        if self._clock_running:
            return
        self._clock_running = True
        self._tick = 0
        self._beat = 0
        self._bar = 0
        self._transport_running = True
        self._next_tick_time = time.perf_counter()
        self._clock_thread = threading.Thread(
            target=self._standalone_clock_loop, daemon=True,
            name="recorder-clock",
        )
        self._clock_thread.start()

    def _stop_standalone_clock(self) -> None:
        self._clock_running = False
        self._transport_running = False
        if self._clock_thread:
            self._clock_thread.join(timeout=1)
            self._clock_thread = None

    def _standalone_clock_loop(self) -> None:
        while self._clock_running:
            if not self._transport_running:
                time.sleep(0.001)
                continue
            now = time.perf_counter()
            if now >= self._next_tick_time:
                tick_interval = 60.0 / (self._bpm * INTERNAL_PPQ)
                self._next_tick_time += tick_interval
                if self._next_tick_time < now:
                    self._next_tick_time = now + tick_interval
                self._on_tick(self._tick, self._beat, self._bar, True)
                self._tick += 1
                if self._tick % INTERNAL_PPQ == 0:
                    self._beat += 1
                    if self._beat >= self._beats_per_bar:
                        self._beat = 0
                        self._bar += 1
            time.sleep(0.0002)

    # ------------------------------------------------------------------
    # Tick callback (from launcher subscriber or standalone clock)
    # ------------------------------------------------------------------

    def _on_tick(self, tick: int, beat: int, bar: int, running: bool) -> None:
        """Called on each tick — check for count-in boundary."""
        self._tick = tick
        self._beat = beat
        self._bar = bar
        self._transport_running = running

        if self._state != "count_in":
            return

        qt = _quantum_ticks(self._quantize, self._beats_per_bar)
        if qt > 0 and tick > 0 and tick % qt == 0:
            self._count_in_event.set()

    # ------------------------------------------------------------------
    # Incoming MIDI (called from hardware input callbacks in main.py)
    # ------------------------------------------------------------------

    def on_midi_message(self, source: str, message) -> None:
        if self._state != "recording":
            return
        if message.type in _SKIP_TYPES:
            return
        offset = time.monotonic() - self._record_start
        with self._lock:
            self._events.append((offset, source, message.copy()))

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def toggle(self) -> dict:
        """Foot-pedal / RECORD button: start recording or stop+play."""
        if self._state == "recording":
            return self._stop_recording()
        if self._state == "count_in":
            # Cancel count-in
            self._cancel_count_in()
            return {"ok": True, "state": self._state}

        self._stop_playback()
        with self._lock:
            self._events = []
            self._length = 0.0

        if self._quantize == "free":
            # Immediate recording (backward compatible)
            self._state = "recording"
            self._record_start = time.monotonic()
            logger.info("Quick recorder: started recording (free)")
            return {"ok": True, "state": self._state}

        # Quantized: enter count-in
        self._state = "count_in"
        self._count_in_event.clear()
        self._subscribe_to_clock()
        logger.info(f"Quick recorder: count-in ({self._quantize} quantize)")

        # Start count-in wait in background thread
        t = threading.Thread(target=self._count_in_worker, daemon=True,
                             name="recorder-count-in")
        t.start()
        return {"ok": True, "state": self._state}

    def play(self) -> dict:
        if self._state == "stopped" and self._events:
            self._start_playback()
            return {"ok": True, "state": self._state}
        return {"ok": False, "error": f"Cannot play in state '{self._state}'"}

    def stop(self) -> dict:
        if self._state == "count_in":
            self._cancel_count_in()
            return {"ok": True, "state": self._state}
        if self._state == "recording":
            return self._stop_recording(auto_play_override=False)
        self._stop_playback()
        if self._events:
            self._state = "stopped"
        else:
            self._state = "idle"
        return {"ok": True, "state": self._state}

    def clear(self) -> dict:
        if self._state == "count_in":
            self._cancel_count_in()
        self._stop_playback()
        with self._lock:
            self._events = []
            self._length = 0.0
        self._state = "idle"
        logger.info("Quick recorder: cleared")
        return {"ok": True, "state": self._state}

    def set_auto_play(self, value: bool) -> None:
        self._auto_play = bool(value)

    # ------------------------------------------------------------------
    # Count-in
    # ------------------------------------------------------------------

    def _subscribe_to_clock(self) -> None:
        """Subscribe to the appropriate clock source."""
        if self._clock_source == "launcher" and self._launcher:
            self._launcher.register_tick_subscriber(self._on_tick)
            # If launcher transport isn't running, start it
            if not self._launcher._transport_running:
                self._launcher.transport_start()
        elif self._clock_source == "standalone":
            self._start_standalone_clock()
        # external: ticks come via on_clock_message forwarded from router

    def _unsubscribe_from_clock(self) -> None:
        """Unsubscribe from tick callbacks."""
        if self._launcher:
            self._launcher.unregister_tick_subscriber(self._on_tick)
        if self._clock_source == "standalone":
            self._stop_standalone_clock()

    def _count_in_worker(self) -> None:
        """Wait for the count-in boundary, then start recording."""
        # Wait up to 30 seconds for a quantum boundary
        triggered = self._count_in_event.wait(timeout=30.0)
        if not triggered or self._state != "count_in":
            # Timed out or cancelled
            if self._state == "count_in":
                self._state = "idle"
                logger.info("Quick recorder: count-in timed out")
            return

        self._state = "recording"
        self._record_start = time.monotonic()
        self._record_start_tick = self._tick
        logger.info(f"Quick recorder: count-in complete, recording at tick {self._tick}")

    def _cancel_count_in(self) -> None:
        """Cancel an active count-in."""
        self._count_in_event.set()  # unblock the worker
        self._unsubscribe_from_clock()
        self._state = "idle"
        logger.info("Quick recorder: count-in cancelled")

    # ------------------------------------------------------------------
    # Save / Export
    # ------------------------------------------------------------------

    def save(self, name: Optional[str] = None) -> dict:
        with self._lock:
            events = list(self._events)
        if not events:
            return {"ok": False, "error": "Nothing recorded"}

        if not name:
            name = "rec_" + datetime.now().strftime("%Y%m%d_%H%M%S")

        filename = name + ".mid"
        filepath = os.path.join(self._recordings_dir, filename)

        try:
            mid = self._to_midi_file(events)
            mid.save(filepath)
        except Exception as e:
            logger.error(f"Failed to save recording: {e}")
            return {"ok": False, "error": str(e)}

        length = round(self._length, 2)
        entry = {
            "name": name,
            "file": filename,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "length_sec": length,
            "event_count": len(events),
        }
        self._append_index(entry)
        logger.info(f"Recording saved: {filepath}")
        return {"ok": True, "name": name, "file": filename}

    def list_recordings(self) -> list:
        idx = self._read_index()
        return list(reversed(idx))  # most recent first

    def delete_recording(self, name: str) -> dict:
        idx = self._read_index()
        entry = next((e for e in idx if e["name"] == name), None)
        if not entry:
            return {"ok": False, "error": "Not found"}
        filepath = os.path.join(self._recordings_dir, entry["file"])
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            logger.warning(f"Could not delete file {filepath}: {e}")
        idx = [e for e in idx if e["name"] != name]
        self._write_index(idx)
        return {"ok": True}

    def get_recording_path(self, name: str) -> Optional[str]:
        idx = self._read_index()
        entry = next((e for e in idx if e["name"] == name), None)
        if not entry:
            return None
        path = os.path.join(self._recordings_dir, entry["file"])
        return path if os.path.exists(path) else None

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        with self._lock:
            events = list(self._events)
        recent = []
        for offset, source, msg in events[-MAX_RECENT:]:
            entry = {
                "offset": round(offset, 3),
                "source": source,
                "type": msg.type,
            }
            if hasattr(msg, "note"):
                entry["note"] = _note_name(msg.note)
                entry["velocity"] = getattr(msg, "velocity", 0)
            if hasattr(msg, "channel"):
                entry["channel"] = msg.channel + 1
            recent.append(entry)

        # Effective BPM — from launcher if synced
        bpm = self._bpm
        if self._clock_source == "launcher" and self._launcher:
            bpm = self._launcher.bpm

        return {
            "state": self._state,
            "length": round(self._length, 2),
            "event_count": len(events),
            "auto_play": self._auto_play,
            "recent_events": recent,
            "clock_source": self._clock_source,
            "bpm": bpm,
            "quantize": self._quantize,
            "beats_per_bar": self._beats_per_bar,
            "beat": self._beat,
            "bar": self._bar,
            "tick": self._tick,
            "transport_running": self._transport_running,
        }

    def close(self) -> None:
        self._cancel_count_in() if self._state == "count_in" else None
        self._stop_playback()
        self._unsubscribe_from_clock()
        self._stop_standalone_clock()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _stop_recording(self, auto_play_override: Optional[bool] = None) -> dict:
        raw_length = time.monotonic() - self._record_start

        # Quantize the loop length if needed
        if self._quantize != "free":
            bpm = self._bpm
            if self._clock_source == "launcher" and self._launcher:
                bpm = self._launcher.bpm
            qt = _quantum_ticks(self._quantize, self._beats_per_bar)
            if qt > 0 and bpm > 0:
                tick_interval = 60.0 / (bpm * INTERNAL_PPQ)
                elapsed_ticks = raw_length / tick_interval
                quantized_ticks = ((int(elapsed_ticks) // qt) + 1) * qt
                self._length = quantized_ticks * tick_interval
            else:
                self._length = raw_length
        else:
            self._length = raw_length

        self._unsubscribe_from_clock()

        with self._lock:
            has_content = bool(self._events) and self._length >= 0.1
        if not has_content:
            with self._lock:
                self._events = []
                self._length = 0.0
            self._state = "idle"
            logger.info("Quick recorder: stopped (no content)")
            return {"ok": True, "state": self._state}

        should_play = self._auto_play if auto_play_override is None else auto_play_override
        if should_play:
            self._start_playback()
        else:
            self._state = "stopped"
        logger.info(f"Quick recorder: stopped recording, {len(self._events)} events, "
                    f"{self._length:.2f}s → {self._state}")
        return {"ok": True, "state": self._state}

    def _start_playback(self) -> None:
        self._stop_playback()
        self._state = "playing"
        stop_ev = threading.Event()
        self._stop_event = stop_ev
        t = threading.Thread(
            target=self._playback_worker,
            args=(stop_ev,),
            daemon=True,
            name="quick-recorder-play",
        )
        self._thread = t
        t.start()

    def _stop_playback(self) -> None:
        ev = self._stop_event
        if ev:
            ev.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=0.5)
        self._stop_event = None
        self._thread = None

    def _playback_worker(self, stop_ev: threading.Event) -> None:
        while not stop_ev.is_set() and self._state == "playing":
            loop_start = time.monotonic()
            with self._lock:
                events = list(self._events)
            length = self._length

            for offset, source, message in events:
                wait = (loop_start + offset) - time.monotonic()
                if wait > 0 and stop_ev.wait(wait):
                    return
                if stop_ev.is_set() or self._state != "playing":
                    return
                if self._router_callback:
                    try:
                        self._router_callback(source, message)
                    except Exception as e:
                        logger.warning(f"Playback send error: {e}")

            remaining = (loop_start + length) - time.monotonic()
            if remaining > 0:
                stop_ev.wait(remaining)

    def _to_midi_file(self, events: list) -> mido.MidiFile:
        mid = mido.MidiFile(type=0, ticks_per_beat=TICKS_PER_BEAT)
        track = mido.MidiTrack()
        mid.tracks.append(track)
        track.append(mido.MetaMessage("set_tempo", tempo=DEFAULT_TEMPO, time=0))

        sorted_events = sorted(events, key=lambda e: e[0])
        prev_ticks = 0
        for offset_sec, _source, msg in sorted_events:
            if msg.type in _SKIP_TYPES:
                continue
            ticks = int(offset_sec * TICKS_PER_BEAT * 1_000_000 / DEFAULT_TEMPO)
            delta = max(0, ticks - prev_ticks)
            prev_ticks = ticks
            try:
                if hasattr(msg, "channel"):
                    track.append(msg.copy(time=delta))
                else:
                    track.append(mido.Message(msg.type, time=delta))
            except Exception:
                pass  # skip malformed messages

        return mid

    # ------------------------------------------------------------------
    # Index helpers
    # ------------------------------------------------------------------

    def _index_path(self) -> str:
        return os.path.join(self._recordings_dir, "index.json")

    def _read_index(self) -> list:
        path = self._index_path()
        if not os.path.exists(path):
            return []
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return []

    def _write_index(self, idx: list) -> None:
        try:
            with open(self._index_path(), "w") as f:
                json.dump(idx, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to write recordings index: {e}")

    def _append_index(self, entry: dict) -> None:
        idx = self._read_index()
        idx.append(entry)
        self._write_index(idx)
