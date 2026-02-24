"""
MIDI File Player - Plays MIDI files and sends messages to destinations.
Supports play, stop, pause, loop, and tempo control.
Supports one-level folder organisation inside the upload directory.
"""

import re
import time
import threading
import logging
from pathlib import Path

import mido

logger = logging.getLogger("midi-box.player")

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "midi_files"

_SAFE_NAME_RE = re.compile(r"[^\w.\-\s]")


def _sanitize(name: str) -> str:
    """Return a filesystem-safe version of *name* (file or folder)."""
    safe = _SAFE_NAME_RE.sub("", name).strip()
    return safe


def _resolve_dir(folder: str | None) -> Path | None:
    """
    Resolve the target directory for *folder*.
    Returns the resolved Path or None if the folder is invalid / path-traversal detected.
    """
    if folder is None:
        return UPLOAD_DIR
    safe_folder = _sanitize(folder)
    if not safe_folder:
        return None
    target = (UPLOAD_DIR / safe_folder).resolve()
    if target.parent != UPLOAD_DIR.resolve():
        logger.warning("Path traversal attempt for folder: %s", folder)
        return None
    return target


def _file_meta(path: Path, folder: str | None) -> dict:
    try:
        mid = mido.MidiFile(str(path))
        return {
            "name": path.name,
            "duration": round(mid.length, 1),
            "tracks": len(mid.tracks),
            "folder": folder,
        }
    except Exception:
        return {"name": path.name, "duration": 0, "tracks": 0, "folder": folder}


class MidiPlayer:
    def __init__(self, send_callback=None, clock_manager=None):
        self._send_callback = send_callback  # fn(destination, mido.Message)
        self._clock_manager = clock_manager  # for BPM display only
        self._thread: threading.Thread | None = None
        self._running = False
        self._paused = False
        self._loop = False
        self._tempo_factor = 1.0
        self._current_file: str | None = None
        self._current_folder: str | None = None
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
            "bpm": round(self._tempo_factor * 120.0),
            "file": self._current_file,
            "folder": self._current_folder,
            "destination": self._destination,
            "position": round(self._position, 1),
            "duration": round(self._duration, 1),
        }

    # ------------------------------------------------------------------
    # File listing
    # ------------------------------------------------------------------

    def list_files(self, folder: str | None = None) -> dict:
        """
        List MIDI files (and folders at root level).

        folder=None  → returns root-level files + all subfolder names/counts.
        folder="x"   → returns files inside UPLOAD_DIR/x only.
        """
        if folder is None:
            # Root level
            folders = []
            for d in sorted(UPLOAD_DIR.iterdir()):
                if d.is_dir() and not d.name.startswith("."):
                    count = len(list(d.glob("*.mid")))
                    folders.append({"name": d.name, "file_count": count})
            files = [_file_meta(f, None) for f in sorted(UPLOAD_DIR.glob("*.mid"))]
            return {"folders": folders, "files": files}
        else:
            target = _resolve_dir(folder)
            if target is None or not target.is_dir():
                return {"folders": [], "files": []}
            files = [_file_meta(f, folder) for f in sorted(target.glob("*.mid"))]
            return {"folders": [], "files": files}

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def upload(self, filename: str, data: bytes, folder: str | None = None) -> dict:
        """Save an uploaded MIDI file. Returns {"ok", "filename", "error"}."""
        if not filename.lower().endswith((".mid", ".midi")):
            filename += ".mid"
        elif filename.lower().endswith(".midi"):
            filename = filename[:-5] + ".mid"

        safe_name = _sanitize(filename)
        if not safe_name:
            return {"ok": False, "error": "Invalid filename"}

        target_dir = _resolve_dir(folder)
        if target_dir is None:
            return {"ok": False, "error": "Invalid folder"}
        if folder is not None and not target_dir.is_dir():
            return {"ok": False, "error": "Folder not found"}

        try:
            path = target_dir / safe_name
            path.write_bytes(data)
            logger.info("MIDI file uploaded: %s (folder=%s)", safe_name, folder)
            return {"ok": True, "filename": safe_name}
        except Exception as e:
            logger.error("Failed to save MIDI file: %s", e)
            return {"ok": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, filename: str, folder: str | None = None) -> bool:
        """Delete a MIDI file."""
        target_dir = _resolve_dir(folder)
        if target_dir is None:
            return False
        path = (target_dir / filename).resolve()
        if path.parent != target_dir.resolve():
            return False
        if not path.exists():
            return False
        # Stop if this is the currently playing file
        if self._current_file == filename and self._current_folder == folder:
            self.stop()
        path.unlink()
        logger.info("MIDI file deleted: %s (folder=%s)", filename, folder)
        return True

    # ------------------------------------------------------------------
    # Rename file
    # ------------------------------------------------------------------

    def rename(self, old_name: str, new_name: str, folder: str | None = None) -> dict:
        """Rename a MIDI file within the same directory."""
        target_dir = _resolve_dir(folder)
        if target_dir is None:
            return {"ok": False, "error": "Invalid folder"}

        old_path = (target_dir / old_name).resolve()
        if old_path.parent != target_dir.resolve() or not old_path.exists():
            return {"ok": False, "error": "File not found"}

        safe_new = _sanitize(new_name)
        if not safe_new.lower().endswith(".mid"):
            safe_new += ".mid"

        new_path = target_dir / safe_new
        if new_path.exists():
            return {"ok": False, "error": "A file with that name already exists"}

        old_path.rename(new_path)
        # Update current file reference if needed
        if self._current_file == old_name and self._current_folder == folder:
            self._current_file = safe_new
        logger.info("MIDI file renamed: %s → %s (folder=%s)", old_name, safe_new, folder)
        return {"ok": True}

    # ------------------------------------------------------------------
    # Folder operations
    # ------------------------------------------------------------------

    def mkdir(self, name: str) -> dict:
        """Create a new subfolder."""
        safe_name = _sanitize(name)
        if not safe_name or safe_name.startswith("."):
            return {"ok": False, "error": "Invalid folder name"}

        target = (UPLOAD_DIR / safe_name).resolve()
        if target.parent != UPLOAD_DIR.resolve():
            return {"ok": False, "error": "Invalid folder name"}
        if target.exists():
            return {"ok": False, "error": "Folder already exists"}

        target.mkdir()
        logger.info("Folder created: %s", safe_name)
        return {"ok": True, "name": safe_name}

    def rename_folder(self, old_name: str, new_name: str) -> dict:
        """Rename a subfolder."""
        old_path = (UPLOAD_DIR / _sanitize(old_name)).resolve()
        if old_path.parent != UPLOAD_DIR.resolve() or not old_path.is_dir():
            return {"ok": False, "error": "Folder not found"}

        safe_new = _sanitize(new_name)
        if not safe_new or safe_new.startswith("."):
            return {"ok": False, "error": "Invalid folder name"}

        new_path = (UPLOAD_DIR / safe_new).resolve()
        if new_path.parent != UPLOAD_DIR.resolve():
            return {"ok": False, "error": "Invalid folder name"}
        if new_path.exists():
            return {"ok": False, "error": "A folder with that name already exists"}

        # Stop if playing a file from this folder
        if self._current_folder == old_name:
            self.stop()

        old_path.rename(new_path)
        logger.info("Folder renamed: %s → %s", old_name, safe_new)
        return {"ok": True}

    def delete_folder(self, name: str) -> dict:
        """Delete a folder and all .mid files inside it."""
        target = _resolve_dir(name)
        if target is None or not target.is_dir():
            return {"ok": False, "error": "Folder not found"}

        # Stop if playing from this folder
        if self._current_folder == name:
            self.stop()

        try:
            for f in target.glob("*.mid"):
                f.unlink()
            target.rmdir()
            logger.info("Folder deleted: %s", name)
            return {"ok": True}
        except Exception as e:
            logger.error("Failed to delete folder %s: %s", name, e)
            return {"ok": False, "error": str(e)}

    def move(self, filename: str, src_folder: str | None, dst_folder: str | None) -> dict:
        """Move a .mid file between directories."""
        src_dir = _resolve_dir(src_folder)
        dst_dir = _resolve_dir(dst_folder)

        if src_dir is None:
            return {"ok": False, "error": "Invalid source folder"}
        if dst_dir is None:
            return {"ok": False, "error": "Invalid destination folder"}
        if dst_folder is not None and not dst_dir.is_dir():
            return {"ok": False, "error": "Destination folder not found"}

        src_path = (src_dir / filename).resolve()
        if src_path.parent != src_dir.resolve() or not src_path.exists():
            return {"ok": False, "error": "File not found"}

        dst_path = dst_dir / filename
        if dst_path.exists():
            return {"ok": False, "error": "A file with that name already exists in the destination"}

        src_path.rename(dst_path)

        # Update current file reference if needed
        if self._current_file == filename and self._current_folder == src_folder:
            self._current_folder = dst_folder

        logger.info("MIDI file moved: %s (%s → %s)", filename, src_folder, dst_folder)
        return {"ok": True}

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def play(self, filename: str, destination: str, folder: str | None = None,
             loop: bool = False, tempo_factor: float = 1.0) -> bool:
        """Start playing a MIDI file to a destination."""
        target_dir = _resolve_dir(folder)
        if target_dir is None:
            logger.error("Invalid folder: %s", folder)
            return False

        path = target_dir / filename
        if not path.exists():
            logger.error("MIDI file not found: %s (folder=%s)", filename, folder)
            return False

        # Stop current playback
        self.stop()

        self._current_file = filename
        self._current_folder = folder
        self._destination = destination
        self._loop = loop
        self._tempo_factor = max(0.25, min(4.0, tempo_factor))
        self._position = 0.0

        try:
            mid = mido.MidiFile(str(path))
            self._duration = mid.length
        except Exception as e:
            logger.error("Failed to load MIDI file: %s", e)
            return False

        self._running = True
        self._paused = False
        self._thread = threading.Thread(
            target=self._play_loop, args=(str(path),), daemon=True
        )
        self._thread.start()
        logger.info("Playing %s (folder=%s) → %s (loop=%s, tempo=%sx)",
                    filename, folder, destination, loop, self._tempo_factor)
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
            logger.error("Failed to load MIDI file: %s", e)
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
                    logger.info("Playback finished: %s", self._current_file)
                else:
                    logger.debug("Looping: %s", self._current_file)

            except Exception as e:
                logger.error("Player error: %s", e)
                self._running = False
