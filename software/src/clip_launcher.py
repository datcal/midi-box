"""
Clip Launcher — Ableton-style session view for MIDI Box.

Manages multiple layers (one per synth), each with up to 10 MIDI clip slots.
Clips launch quantized to beat/bar boundaries.

Clock is provided externally by ClockManager — the Launcher is a tick subscriber
and no longer owns a clock thread or BPM value.
"""

import threading
import logging
from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path

import mido

logger = logging.getLogger("midi-box.launcher")

MIDI_FILES_DIR = Path(__file__).resolve().parent.parent / "data" / "midi_files"

# Internal resolution: 96 ticks per beat (4× MIDI clock's 24 PPQ)
INTERNAL_PPQ = 96
# MIDI clock (0xF8) emits every 4 internal ticks = standard 24 PPQ
CLOCK_EMIT_INTERVAL = INTERNAL_PPQ // 24  # = 4

MAX_CLIPS_PER_LAYER = 10


class ClipState(Enum):
    EMPTY = "empty"
    STOPPED = "stopped"
    QUEUED = "queued"
    PLAYING = "playing"
    STOPPING = "stopping"


@dataclass
class Clip:
    slot: int
    filename: str = ""
    name: str = ""
    loop: bool = True
    state: ClipState = ClipState.EMPTY
    # Pre-processed MIDI events: list of (absolute_tick, mido.Message)
    events: list = field(default_factory=list)
    total_ticks: int = 0
    play_head: int = 0
    event_cursor: int = 0


@dataclass
class Layer:
    layer_id: int
    name: str = ""
    destination: str = ""
    midi_channel: int | None = None  # None = use file's channels
    clips: list = field(default_factory=list)
    active_clip: int | None = None  # slot index of playing clip
    queued_clip: int | None = None  # slot index queued for next quantum
    active_notes: set = field(default_factory=set)  # (channel, note) pairs

    def __post_init__(self):
        if not self.clips:
            self.clips = [Clip(slot=i) for i in range(MAX_CLIPS_PER_LAYER)]


class ClipLauncher:
    def __init__(self, clock_manager=None):
        self.layers: list[Layer] = []
        self._send_callback = None  # fn(destination, mido.Message)
        self._output_devices_callback = None  # fn() -> list[str], for clock output

        # Reference to the shared ClockManager (injected from main.py)
        self._clock_manager = clock_manager

        # Launcher-owned settings (BPM lives in ClockManager)
        self.beats_per_bar = 4
        self.quantum = "bar"  # "beat", "bar", "2bar", "4bar"

        # Transport state (separate from clock — clock always ticks)
        self._tick = 0   # last tick received from ClockManager
        self._beat = 0
        self._bar = 0
        self._transport_running = False

        # Start-point selection (mutually exclusive)
        self.start_column: int | None = None
        self.start_cell: tuple | None = None  # (layer_id, slot)

        self._lock = threading.Lock()

        MIDI_FILES_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """Subscribe to ClockManager ticks."""
        if self._clock_manager:
            self._clock_manager.register_tick_subscriber(self._on_clock_tick)
        logger.info("Clip launcher started")

    def stop(self):
        """Stop all clips and unsubscribe from clock."""
        self.stop_all()
        if self._clock_manager:
            self._clock_manager.unregister_tick_subscriber(self._on_clock_tick)
        logger.info("Clip launcher stopped")

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def transport_start(self):
        """Start transport (clips can play on next quantum boundary)."""
        with self._lock:
            self._transport_running = True
            self._apply_start_point()
        bpm = self._clock_manager.bpm if self._clock_manager else "?"
        logger.info(f"Transport START — {bpm} BPM, {self.quantum} quantize")

    def transport_stop(self):
        """Stop transport — stop all clips."""
        with self._lock:
            self._transport_running = False
            self._stop_all_clips()
        logger.info("Transport STOP")

    def on_transport_message(self, message: mido.Message):
        """Handle external MIDI transport messages (start/stop/continue)."""
        if message.type == "start":
            with self._lock:
                self._transport_running = True
                self._apply_start_point()
            logger.info("External transport START")
        elif message.type == "stop":
            with self._lock:
                self._transport_running = False
                self._stop_all_clips()
            logger.info("External transport STOP")
        elif message.type == "continue":
            with self._lock:
                self._transport_running = True
            logger.info("External transport CONTINUE")

    # ------------------------------------------------------------------
    # Clock tick handler (called by ClockManager subscription)
    # ------------------------------------------------------------------

    def _on_clock_tick(self, tick: int, beat: int, bar: int, running: bool):
        """Receive a tick from ClockManager and advance transport logic."""
        with self._lock:
            self._tick = tick
            self._beat = beat
            self._bar = bar

            if not self._transport_running:
                return

            # Emit MIDI clock (0xF8) to all output devices every 4 internal ticks
            # when running in internal mode (ClockManager owns the timing source)
            cm_source = self._clock_manager.source if self._clock_manager else "internal"
            if cm_source == "internal" and tick % CLOCK_EMIT_INTERVAL == 0:
                self._emit_midi_clock()

            # Check quantum boundary for queued launches
            if self._is_quantum_boundary():
                self._process_queued_launches()

            # Advance all active clips
            for layer in self.layers:
                if layer.active_clip is not None:
                    self._advance_clip(layer)

    def _is_quantum_boundary(self) -> bool:
        """Check if current tick is on a quantum boundary."""
        t = self._tick
        tpbar = INTERNAL_PPQ * self.beats_per_bar

        if self.quantum == "beat":
            return t % INTERNAL_PPQ == 0
        elif self.quantum == "bar":
            return t % tpbar == 0
        elif self.quantum == "2bar":
            return t % (tpbar * 2) == 0
        elif self.quantum == "4bar":
            return t % (tpbar * 4) == 0
        return False

    def _emit_midi_clock(self):
        """Send 0xF8 to all output devices."""
        if not self._send_callback or not self._output_devices_callback:
            return
        clock_msg = mido.Message("clock")
        for dest in self._output_devices_callback():
            try:
                self._send_callback(dest, clock_msg)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Quantized launch / stop
    # ------------------------------------------------------------------

    def launch_clip(self, layer_id: int, slot: int):
        """Queue a clip to launch at the next quantum boundary."""
        with self._lock:
            layer = self._get_layer(layer_id)
            if not layer or slot < 0 or slot >= MAX_CLIPS_PER_LAYER:
                return
            clip = layer.clips[slot]
            if clip.state == ClipState.EMPTY:
                return

            # Toggle: if already queued, cancel
            if layer.queued_clip == slot:
                layer.clips[slot].state = ClipState.STOPPED
                layer.queued_clip = None
                return

            # If already playing this clip, queue stop
            if layer.active_clip == slot:
                clip.state = ClipState.STOPPING
                layer.queued_clip = None
                return

            # Queue the clip
            # Cancel any previous queue
            if layer.queued_clip is not None:
                layer.clips[layer.queued_clip].state = ClipState.STOPPED
            clip.state = ClipState.QUEUED
            layer.queued_clip = slot

            # Mark current clip as stopping
            if layer.active_clip is not None:
                layer.clips[layer.active_clip].state = ClipState.STOPPING

            # If transport not running, start immediately
            if not self._transport_running:
                self._transport_running = True
                self._process_queued_launches()

    def stop_layer(self, layer_id: int):
        """Queue the active clip on a layer to stop at next quantum."""
        with self._lock:
            layer = self._get_layer(layer_id)
            if not layer:
                return
            if layer.active_clip is not None:
                layer.clips[layer.active_clip].state = ClipState.STOPPING
            if layer.queued_clip is not None:
                layer.clips[layer.queued_clip].state = ClipState.STOPPED
                layer.queued_clip = None

    def stop_all(self):
        """Immediately stop all clips on all layers."""
        with self._lock:
            self._stop_all_clips()

    def launch_column(self, slot: int):
        """Queue all layers to play the clip at this slot (scene launch)."""
        with self._lock:
            for layer in self.layers:
                clip = layer.clips[slot]
                if clip.state == ClipState.EMPTY:
                    continue
                if layer.active_clip == slot:
                    continue  # already playing this slot
                if layer.queued_clip is not None:
                    layer.clips[layer.queued_clip].state = ClipState.STOPPED
                clip.state = ClipState.QUEUED
                layer.queued_clip = slot
                if layer.active_clip is not None:
                    layer.clips[layer.active_clip].state = ClipState.STOPPING
            if not self._transport_running:
                self._transport_running = True
                self._process_queued_launches()

    def set_start_point(self, column=None, layer_id=None, slot=None):
        """Set column or cell as transport start point (mutually exclusive).
        Toggle: calling with the same value again clears the selection.
        Call with no args to clear entirely.
        """
        with self._lock:
            if column is not None:
                self.start_column = None if self.start_column == column else column
                self.start_cell = None
            elif layer_id is not None and slot is not None:
                new_cell = (layer_id, slot)
                self.start_cell = None if self.start_cell == new_cell else new_cell
                self.start_column = None
            else:
                self.start_column = None
                self.start_cell = None

    def _apply_start_point(self):
        """Queue clips for the configured start point. Must hold _lock."""
        if self.start_column is not None:
            slot = self.start_column
            for layer in self.layers:
                clip = layer.clips[slot]
                if clip.state == ClipState.EMPTY:
                    continue
                if layer.active_clip == slot:
                    continue
                if layer.queued_clip is not None:
                    layer.clips[layer.queued_clip].state = ClipState.STOPPED
                clip.state = ClipState.QUEUED
                layer.queued_clip = slot
                if layer.active_clip is not None:
                    layer.clips[layer.active_clip].state = ClipState.STOPPING
        elif self.start_cell is not None:
            sc_layer_id, sc_slot = self.start_cell
            layer = self._get_layer(sc_layer_id)
            if layer:
                clip = layer.clips[sc_slot]
                if clip.state != ClipState.EMPTY:
                    if layer.queued_clip is not None:
                        layer.clips[layer.queued_clip].state = ClipState.STOPPED
                    clip.state = ClipState.QUEUED
                    layer.queued_clip = sc_slot
                    if layer.active_clip is not None and layer.active_clip != sc_slot:
                        layer.clips[layer.active_clip].state = ClipState.STOPPING

    def _stop_all_clips(self):
        """Stop all clips — must hold lock."""
        for layer in self.layers:
            self._stop_clip_clean(layer)
            layer.active_clip = None
            layer.queued_clip = None
            for clip in layer.clips:
                if clip.state in (ClipState.PLAYING, ClipState.QUEUED, ClipState.STOPPING):
                    clip.state = ClipState.STOPPED

    def _process_queued_launches(self):
        """At quantum boundary: switch clips. Must hold lock."""
        for layer in self.layers:
            if layer.queued_clip is not None:
                # Stop current clip cleanly
                if layer.active_clip is not None:
                    self._stop_clip_clean(layer)
                    layer.clips[layer.active_clip].state = ClipState.STOPPED

                # Start queued clip
                slot = layer.queued_clip
                clip = layer.clips[slot]
                clip.state = ClipState.PLAYING
                clip.play_head = 0
                clip.event_cursor = 0
                layer.active_clip = slot
                layer.queued_clip = None

            elif layer.active_clip is not None:
                clip = layer.clips[layer.active_clip]
                if clip.state == ClipState.STOPPING:
                    self._stop_clip_clean(layer)
                    clip.state = ClipState.STOPPED
                    layer.active_clip = None

    # ------------------------------------------------------------------
    # Clip playback
    # ------------------------------------------------------------------

    def _advance_clip(self, layer: Layer):
        """Advance a layer's active clip by one tick. Must hold lock."""
        clip = layer.clips[layer.active_clip]
        if clip.state != ClipState.PLAYING:
            return
        if not clip.events:
            return

        # Send all events at current play_head
        while clip.event_cursor < len(clip.events):
            ev_tick, msg = clip.events[clip.event_cursor]
            if ev_tick > clip.play_head:
                break
            self._send_clip_event(layer, msg)
            clip.event_cursor += 1

        # End of clip: check before advancing so there is no extra tick of silence
        if clip.play_head >= clip.total_ticks:
            if clip.loop:
                clip.play_head = 0
                clip.event_cursor = 0
            else:
                self._stop_clip_clean(layer)
                clip.state = ClipState.STOPPED
                layer.active_clip = None
            return

        clip.play_head += 1

    def _send_clip_event(self, layer: Layer, msg: mido.Message):
        """Send a MIDI event from a clip, tracking notes."""
        if not self._send_callback:
            return

        # Track active notes for clean stop
        if msg.type == "note_on" and msg.velocity > 0:
            layer.active_notes.add((msg.channel, msg.note))
        elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            layer.active_notes.discard((msg.channel, msg.note))

        # Apply channel override
        out_msg = msg
        if layer.midi_channel is not None and hasattr(msg, "channel"):
            out_msg = msg.copy(channel=max(0, layer.midi_channel - 1))

        self._send_callback(layer.destination, out_msg)

    def _stop_clip_clean(self, layer: Layer):
        """Send note-off for all active notes on this layer."""
        if not self._send_callback:
            return
        for ch, note in layer.active_notes:
            try:
                msg = mido.Message("note_off", channel=ch, note=note, velocity=0)
                self._send_callback(layer.destination, msg)
            except Exception:
                pass
        layer.active_notes.clear()

    # ------------------------------------------------------------------
    # Layer management
    # ------------------------------------------------------------------

    def add_layer(self, name: str, destination: str,
                  midi_channel: int | None = None) -> Layer:
        """Add a new layer."""
        with self._lock:
            layer_id = len(self.layers)
            layer = Layer(layer_id=layer_id, name=name, destination=destination,
                          midi_channel=midi_channel)
            self.layers.append(layer)
        logger.info(f"Layer added: {name} -> {destination}")
        return layer

    def remove_layer(self, layer_id: int) -> bool:
        """Remove a layer by ID."""
        with self._lock:
            layer = self._get_layer(layer_id)
            if not layer:
                return False
            self._stop_clip_clean(layer)
            self.layers = [l for l in self.layers if l.layer_id != layer_id]
            # Re-index
            for i, l in enumerate(self.layers):
                l.layer_id = i
        return True

    def update_layer(self, layer_id: int, name: str = None,
                     destination: str = None, midi_channel: int = None):
        """Update layer properties."""
        with self._lock:
            layer = self._get_layer(layer_id)
            if not layer:
                return
            if name is not None:
                layer.name = name
            if destination is not None:
                layer.destination = destination
            if midi_channel is not None:
                layer.midi_channel = midi_channel if midi_channel > 0 else None

    def _get_layer(self, layer_id: int) -> Layer | None:
        for layer in self.layers:
            if layer.layer_id == layer_id:
                return layer
        return None

    # ------------------------------------------------------------------
    # Clip management
    # ------------------------------------------------------------------

    def assign_clip(self, layer_id: int, slot: int, filename: str,
                    name: str = "", loop: bool = True) -> bool:
        """Assign a MIDI file to a clip slot, pre-processing the events."""
        with self._lock:
            layer = self._get_layer(layer_id)
            if not layer or slot < 0 or slot >= MAX_CLIPS_PER_LAYER:
                return False

        filepath = MIDI_FILES_DIR / filename
        if not filepath.exists():
            logger.error(f"MIDI file not found: {filename}")
            return False

        events, total_ticks = self._preprocess_midi(filepath)
        if not events:
            logger.warning(f"No events in MIDI file: {filename}")

        with self._lock:
            clip = layer.clips[slot]
            clip.filename = filename
            clip.name = name or filename
            clip.loop = loop
            clip.state = ClipState.STOPPED
            clip.events = events
            clip.total_ticks = total_ticks
            clip.play_head = 0
            clip.event_cursor = 0

        logger.info(f"Clip assigned: layer {layer_id} slot {slot} <- {filename} "
                     f"({total_ticks} ticks, {len(events)} events)")
        return True

    def remove_clip(self, layer_id: int, slot: int) -> bool:
        """Remove a clip from a slot."""
        with self._lock:
            layer = self._get_layer(layer_id)
            if not layer or slot < 0 or slot >= MAX_CLIPS_PER_LAYER:
                return False
            # Stop if playing
            if layer.active_clip == slot:
                self._stop_clip_clean(layer)
                layer.active_clip = None
            if layer.queued_clip == slot:
                layer.queued_clip = None
            layer.clips[slot] = Clip(slot=slot)
        return True

    @staticmethod
    def _preprocess_midi(filepath: Path) -> tuple[list, int]:
        """Parse MIDI file and convert to (abs_tick, msg) list at INTERNAL_PPQ."""
        try:
            mid = mido.MidiFile(str(filepath))
        except Exception as e:
            logger.error(f"Failed to parse MIDI file {filepath}: {e}")
            return [], 0

        file_ppq = mid.ticks_per_beat or 480
        ratio = INTERNAL_PPQ / file_ppq

        events = []
        for track in mid.tracks:
            abs_tick = 0
            for msg in track:
                abs_tick += msg.time
                if not msg.is_meta:
                    scaled_tick = round(abs_tick * ratio)
                    events.append((scaled_tick, msg.copy(time=0)))

        events.sort(key=lambda e: e[0])
        total_ticks = events[-1][0] if events else 0
        return events, total_ticks

    # ------------------------------------------------------------------
    # Clock configuration
    # ------------------------------------------------------------------

    def set_bpm(self, bpm: float):
        """Delegate BPM change to ClockManager (global BPM)."""
        if self._clock_manager:
            self._clock_manager.set_bpm(bpm)

    def set_quantum(self, quantum: str):
        if quantum in ("beat", "bar", "2bar", "4bar"):
            self.quantum = quantum
            logger.info(f"Quantum: {quantum}")

    def set_beats_per_bar(self, beats: int):
        self.beats_per_bar = max(1, min(16, beats))

    # ------------------------------------------------------------------
    # File management (shared with MidiPlayer)
    # ------------------------------------------------------------------

    def list_files(self) -> list[dict]:
        """List available MIDI files."""
        files = []
        for f in sorted(MIDI_FILES_DIR.glob("*.mid")):
            try:
                mid = mido.MidiFile(str(f))
                files.append({
                    "name": f.name,
                    "duration": round(mid.length, 1),
                    "tracks": len(mid.tracks),
                })
            except Exception:
                files.append({"name": f.name, "duration": 0, "tracks": 0})
        return files

    def upload(self, filename: str, data: bytes) -> bool:
        """Save an uploaded MIDI file."""
        if not filename.lower().endswith(".mid"):
            filename += ".mid"
        safe_name = "".join(c for c in filename if c.isalnum() or c in ".-_ ").strip()
        if not safe_name:
            return False
        try:
            (MIDI_FILES_DIR / safe_name).write_bytes(data)
            logger.info(f"MIDI file uploaded: {safe_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to save MIDI file: {e}")
            return False

    def delete_file(self, filename: str) -> bool:
        """Delete a MIDI file."""
        path = MIDI_FILES_DIR / filename
        if path.exists() and path.parent == MIDI_FILES_DIR:
            path.unlink()
            return True
        return False

    # ------------------------------------------------------------------
    # Status & persistence
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Full status for API."""
        cm = self._clock_manager
        with self._lock:
            return {
                "clock": {
                    "beats_per_bar": self.beats_per_bar,
                    "quantum": self.quantum,
                    "tick": self._tick,
                    "beat": self._beat,
                    "bar": self._bar,
                    "running": self._transport_running,
                },
                "start_column": self.start_column,
                "start_cell": list(self.start_cell) if self.start_cell else None,
                "layers": [self._layer_status(l) for l in self.layers],
            }

    def get_poll(self) -> dict:
        """Lightweight status for UI polling."""
        cm = self._clock_manager
        bpm = cm.bpm if cm else 120.0
        with self._lock:
            return {
                "tick": self._tick,
                "beat": self._beat,
                "bar": self._bar,
                "bpm": bpm,
                "running": self._transport_running,
                "start_column": self.start_column,
                "start_cell": list(self.start_cell) if self.start_cell else None,
                "layers": [
                    {
                        "id": l.layer_id,
                        "active_clip": l.active_clip,
                        "queued_clip": l.queued_clip,
                        "clip_states": [c.state.value for c in l.clips],
                    }
                    for l in self.layers
                ],
            }

    def _layer_status(self, layer: Layer) -> dict:
        return {
            "id": layer.layer_id,
            "name": layer.name,
            "destination": layer.destination,
            "midi_channel": layer.midi_channel,
            "active_clip": layer.active_clip,
            "queued_clip": layer.queued_clip,
            "clips": [
                {
                    "slot": c.slot,
                    "filename": c.filename,
                    "name": c.name,
                    "loop": c.loop,
                    "state": c.state.value,
                    "total_ticks": c.total_ticks,
                    "play_head": c.play_head,
                }
                for c in layer.clips
            ],
        }

    def save_state(self) -> dict:
        """Serialize launcher config for persistence (BPM is in unified clock state)."""
        with self._lock:
            return {
                "beats_per_bar": self.beats_per_bar,
                "quantum": self.quantum,
                "start_column": self.start_column,
                "start_cell": list(self.start_cell) if self.start_cell else None,
                "layers": [
                    {
                        "id": l.layer_id,
                        "name": l.name,
                        "destination": l.destination,
                        "midi_channel": l.midi_channel,
                        "clips": [
                            {
                                "slot": c.slot,
                                "filename": c.filename,
                                "name": c.name,
                                "loop": c.loop,
                            }
                            if c.state != ClipState.EMPTY else None
                            for c in l.clips
                        ],
                    }
                    for l in self.layers
                ],
            }

    def load_state(self, data: dict):
        """Restore launcher config from saved state (BPM comes from ClockManager)."""
        if not data:
            return

        # Support both old format (nested clock dict) and new flat format
        clock = data.get("clock", {})
        self.beats_per_bar = data.get("beats_per_bar", clock.get("beats_per_bar", 4))
        self.quantum = data.get("quantum", clock.get("quantum", "bar"))

        sc = data.get("start_column")
        self.start_column = int(sc) if sc is not None else None
        cell = data.get("start_cell")
        self.start_cell = tuple(cell) if cell else None

        self.layers.clear()
        for ldata in data.get("layers", []):
            layer = self.add_layer(
                name=ldata.get("name", ""),
                destination=ldata.get("destination", ""),
                midi_channel=ldata.get("midi_channel"),
            )
            for cdata in ldata.get("clips", []):
                if cdata and cdata.get("filename"):
                    self.assign_clip(
                        layer.layer_id,
                        cdata["slot"],
                        cdata["filename"],
                        name=cdata.get("name", ""),
                        loop=cdata.get("loop", True),
                    )

        logger.info(f"Launcher state loaded: {len(self.layers)} layers")
