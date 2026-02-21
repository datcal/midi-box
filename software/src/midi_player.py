"""
MIDI File Player - Plays MIDI files and sends messages to destinations.
Supports play, stop, pause, loop, and tempo control.
"""

import time
import threading
import logging
from pathlib import Path

import mido

logger = logging.getLogger("midi-box.player")

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "midi_files"


class MidiPlayer:
    def __init__(self, send_callback=None):
        self._send_callback = send_callback  # fn(destination, mido.Message)
        self._thread: threading.Thread | None = None
        self._running = False
        self._paused = False
        self._loop = False
        self._tempo_factor = 1.0
        self._current_file: str | None = None
        self._destination: str | None = None
        self._position = 0.0  # seconds elapsed
        self._duration = 0.0
        self._lock = threading.Lock()
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def is_playing(self) -> bool:
        return self._running and not self._paused

    @property
    def is_paused(self) -> bool:
        return self._running and self._paused

    @property
    def status(self) -> dict:
        return {
            "playing": self._running and not self._paused,
            "paused": self._paused,
            "loop": self._loop,
            "tempo_factor": self._tempo_factor,
            "file": self._current_file,
            "destination": self._destination,
            "position": round(self._position, 1),
            "duration": round(self._duration, 1),
        }

    def list_files(self) -> list[dict]:
        """List available MIDI files."""
        files = []
        for f in sorted(UPLOAD_DIR.glob("*.mid")):
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
        # Sanitize filename
        safe_name = "".join(c for c in filename if c.isalnum() or c in ".-_ ").strip()
        if not safe_name:
            return False
        try:
            path = UPLOAD_DIR / safe_name
            path.write_bytes(data)
            logger.info(f"MIDI file uploaded: {safe_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to save MIDI file: {e}")
            return False

    def delete(self, filename: str) -> bool:
        """Delete a MIDI file."""
        path = UPLOAD_DIR / filename
        if path.exists() and path.parent == UPLOAD_DIR:
            path.unlink()
            logger.info(f"MIDI file deleted: {filename}")
            return True
        return False

    def play(self, filename: str, destination: str, loop: bool = False,
             tempo_factor: float = 1.0) -> bool:
        """Start playing a MIDI file to a destination."""
        path = UPLOAD_DIR / filename
        if not path.exists():
            logger.error(f"MIDI file not found: {filename}")
            return False

        # Stop current playback
        self.stop()

        self._current_file = filename
        self._destination = destination
        self._loop = loop
        self._tempo_factor = max(0.25, min(4.0, tempo_factor))
        self._position = 0.0

        try:
            mid = mido.MidiFile(str(path))
            self._duration = mid.length
        except Exception as e:
            logger.error(f"Failed to load MIDI file: {e}")
            return False

        self._running = True
        self._paused = False
        self._thread = threading.Thread(
            target=self._play_loop, args=(str(path),), daemon=True
        )
        self._thread.start()
        logger.info(f"Playing {filename} -> {destination} (loop={loop}, tempo={self._tempo_factor}x)")
        return True

    def stop(self):
        """Stop playback."""
        self._running = False
        self._paused = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        # Send all-notes-off to destination
        if self._destination and self._send_callback:
            for ch in range(16):
                try:
                    msg = mido.Message("control_change", channel=ch, control=123, value=0)
                    self._send_callback(self._destination, msg)
                except Exception:
                    pass
        self._position = 0.0
        logger.info("Player stopped")

    def pause(self):
        """Pause playback."""
        self._paused = True

    def resume(self):
        """Resume from pause."""
        self._paused = False

    def set_loop(self, loop: bool):
        self._loop = loop

    def set_tempo(self, factor: float):
        self._tempo_factor = max(0.25, min(4.0, factor))

    def _play_loop(self, filepath: str):
        """Background thread: play the MIDI file with tempo control."""
        # Pre-load all messages once to avoid re-reading disk on every loop restart
        try:
            mid = mido.MidiFile(filepath)
            messages = list(mid)
        except Exception as e:
            logger.error(f"Failed to load MIDI file: {e}")
            self._running = False
            return

        while self._running:
            try:
                self._position = 0.0
                start_time = time.time()

                for msg in messages:
                    if not self._running:
                        return

                    # Handle pause
                    while self._paused and self._running:
                        time.sleep(0.05)

                    if not self._running:
                        return

                    # Wait with tempo adjustment
                    if msg.time > 0:
                        time.sleep(msg.time / self._tempo_factor)

                    self._position = time.time() - start_time

                    # Send non-meta messages
                    if not msg.is_meta and self._send_callback and self._destination:
                        self._send_callback(self._destination, msg)

                # End of file
                if not self._loop:
                    self._running = False
                    logger.info(f"Playback finished: {self._current_file}")
                else:
                    logger.debug(f"Looping: {self._current_file}")

            except Exception as e:
                logger.error(f"Player error: {e}")
                self._running = False
