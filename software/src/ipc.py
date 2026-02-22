"""
IPC Bridge - Shared state and command bus between MIDI engine and Flask.

The MIDI engine process owns all hardware and MIDI objects.
The Flask web process is a pure consumer: reads from shared state,
sends commands via queue, and waits for results.

Communication:
  shared_state : Manager().dict()  — MIDI writes, Flask reads (updated ~5×/sec)
  cmd_queue    : Manager().Queue() — Flask sends commands, MIDI processes
  results      : Manager().dict()  — MIDI writes results, Flask polls/removes
"""

import uuid
import time
import logging
from multiprocessing import Manager

logger = logging.getLogger("midi-box.ipc")

# How often (seconds) the MIDI process pushes state to the shared dict.
STATE_UPDATE_INTERVAL = 0.2

# Command wait timeout (seconds).
COMMAND_TIMEOUT = 5.0

_DEFAULT_STATE = {
    "devices": [],          # list of device dicts
    "routes": [],           # list of route dicts
    "mode": "standalone",
    "preset": "default",
    "clock_source": None,
    "platform": "unknown",
    "wifi_config": {},
    "midi_log": [],         # recent MIDI messages (last 100)
    "midi_stats": {},
    "midi_paused": False,
    "performance_mode": False,  # When True: all logging suppressed for lower latency
    "log_entries": [],      # Python log ring buffer (last 200)
    "launcher": {},
    "launcher_poll": {},
    "player": {},
    "presets": [],
    "current_preset": "default",
    "activity": [],         # per-device activity for /api/poll
    "midi_pid": None,       # PID of MIDI process (for restart)
}


class IpcBridge:
    """
    Shared state + command bus for inter-process communication.
    Create this in the main process BEFORE forking.
    """

    def __init__(self):
        self._manager = Manager()
        self.state = self._manager.dict(_DEFAULT_STATE)
        self.cmd_queue = self._manager.Queue()
        self.results = self._manager.dict()

    def send_command(self, action: str, params: dict = None,
                     timeout: float = COMMAND_TIMEOUT) -> dict:
        """
        Send a command from Flask to the MIDI process.
        Blocks until a result arrives or timeout is reached.
        """
        cmd_id = str(uuid.uuid4())
        self.cmd_queue.put({"id": cmd_id, "action": action, "params": params or {}})

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cmd_id in self.results:
                result = dict(self.results[cmd_id])
                del self.results[cmd_id]
                return result
            time.sleep(0.005)

        logger.error(f"IPC command timeout: {action}")
        # Remove stale result if the engine writes it after we gave up
        self.results.pop(cmd_id, None)
        return {"ok": False, "error": "timeout"}

    def close(self):
        try:
            self._manager.shutdown()
        except Exception:
            pass
