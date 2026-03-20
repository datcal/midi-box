# MIDI Box Code Review — Agent 1

Review of all 20 Python files in `software/src/`. Organized by severity.

---

## BUGS

### 1. ClipLauncher double-sends MIDI clock — duplicate 0xF8 to all outputs

**File:** `software/src/clip_launcher.py:166`

`_on_clock_tick` sends MIDI clock via `_emit_midi_clock()` when source is internal. But `ClockManager._advance_tick()` already calls `_midi_clock_callback` (which is `_send_clock_to_outputs`) at the same 4-tick interval. Every internal tick produces **two** 0xF8 messages to every output device — double-clocking all connected synths.

```python
# clip_launcher.py:166 — this block should be removed entirely
if cm_source == "internal" and tick % CLOCK_EMIT_INTERVAL == 0:
    self._emit_midi_clock()  # DUPLICATE — ClockManager already does this
```

**Fix:** Delete lines 163-167 in `clip_launcher.py`. ClockManager already handles clock output. Also remove the now-dead `_emit_midi_clock` method (lines 193-202) and the `_output_devices_callback` field.

---

### 2. MidiFilter inconsistency: `"transport"` not in documented `message_types` spec

**File:** `software/src/midi_filter.py:69`

Transport messages (start/stop/continue) are filtered by checking `"transport" not in self.message_types`, but CLAUDE.md documents the valid message_types as `"start"`, `"stop"`, `"continue"` (individually). If a user sets `message_types: ["start"]`, this code blocks it because `"transport"` is not in the list — there's no way to allow just `start` without also allowing `stop` and `continue`.

```python
# midi_filter.py:69 — checks for undocumented "transport" category
if self.message_types and "transport" not in self.message_types:
    return None
```

**Fix:** Check individual types instead:

```python
if self.message_types and message.type not in self.message_types:
    return None
```

---

### 3. Router `_record_activity` is not thread-safe — dict mutation from multiple threads

**File:** `software/src/router.py:196-200`

`_record_activity` does a check-then-set on `self._activity` without locking. Called from rtmidi's callback thread (USB MIDI), hw_midi read thread, and the main loop (gadget). Two threads could both see the key missing and create duplicate `PortActivity` objects, losing counts.

```python
def _record_activity(self, port_name: str, msg_type: str, is_input: bool):
    key = f"{'in' if is_input else 'out'}:{port_name}"
    if key not in self._activity:       # Thread A reads: not present
        self._activity[key] = PortActivity()  # Thread B also writes here
    self._activity[key].record(msg_type)
```

**Fix:** Use `defaultdict(PortActivity)` or pre-initialize entries under lock:

```python
from collections import defaultdict

# In __init__:
self._activity: dict[str, PortActivity] = defaultdict(PortActivity)

# Then _record_activity simplifies to:
def _record_activity(self, port_name: str, msg_type: str, is_input: bool):
    key = f"{'in' if is_input else 'out'}:{port_name}"
    self._activity[key].record(msg_type)
```

---

### 4. Looper `stop_recording` during overdub doesn't check `overdubbing` state for unsubscribe

**File:** `software/src/midi_looper.py:322-323`

When `stop_recording` is called for a `recording` slot, the code checks if any other slots still need the clock subscription. But it only checks for `("count_in", "recording")`, not `"overdubbing"`. If slot 0 is overdubbing and slot 1 finishes recording, the clock subscription gets removed — slot 0's overdub loses tick updates.

```python
# midi_looper.py:322
if not any(s.state in ("count_in", "recording") for s in self.slots):
    self._unsubscribe_from_clock()
# Missing: "overdubbing" — if another slot is overdubbing, it needs ticks too
```

**Fix:** Include `"overdubbing"` in the state check:

```python
if not any(s.state in ("count_in", "recording", "overdubbing") for s in self.slots):
    self._unsubscribe_from_clock()
```

---

### 5. Flask API endpoints crash on missing JSON keys

**File:** `software/src/ui_web.py:274-275`, `software/src/ui_web.py:283-285`

Several POST endpoints access `data["from"]` and `data["to"]` without `.get()`. If `request.json` is missing these keys, Flask returns an unhandled 500 error instead of a clean 400.

```python
# ui_web.py:274 — KeyError if "from" missing
result = _cmd("route.add", {
    "from": data["from"],  # KeyError crash
    "to": data["to"],      # KeyError crash
```

**Fix:** Add validation:

```python
@app.route("/api/routes", methods=["POST"])
def api_routes_add():
    data = request.json
    if not data or "from" not in data or "to" not in data:
        return jsonify({"ok": False, "error": "missing 'from' and 'to' fields"}), 400
    result = _cmd("route.add", {
        "from": data["from"],
        "to": data["to"],
        "filter": data.get("filter", {}),
        "name": data.get("name", ""),
    })
    return jsonify({"ok": result.get("ok", False), "route": result.get("route", "")})
```

Apply the same pattern to `api_routes_remove` and `api_routes_toggle`.

---

## RISKS

### 6. IPC shared state read-modify-write race on `wifi_config`

**File:** `software/src/ui_web.py:158-161`

The network update endpoint reads the shared state dict, modifies the copy, and writes it back. If two requests arrive concurrently (or the engine writes `wifi_config` at the same time), one update is silently lost. The multiprocessing Manager dict is not atomic for read-modify-write.

```python
wifi = dict(bridge.state.get("wifi_config", {}))  # read
wifi["ssid"] = ssid                                # modify
bridge.state["wifi_config"] = wifi                  # write (not atomic)
```

**Impact:** Low — WiFi config changes are rare and single-user. But technically a race.

**Fix:** Route WiFi config changes through the IPC command queue like other mutations, so the engine process handles them atomically.

---

### 7. `_update_shared_state` parses MIDI files from disk 10x/sec — IPC bottleneck

**File:** `software/src/main.py:1105`, `software/src/main.py:1112`

Every 100ms, the engine serializes all devices, routes, launcher status, player file list, looper status, etc. into the Manager dict. The `list_files()` calls in particular do `mido.MidiFile(str(f))` for every `.mid` file on disk — on each state push.

```python
# main.py:1105 — parses every MIDI file on disk, 10x/sec
status["files"] = self.launcher.list_files()  # opens and parses all .mid files
# main.py:1112 — same for player
"files": self.player.list_files(),
```

**Fix:** Cache file listings and only refresh when files change (upload/delete/rename):

```python
# In ClipLauncher and MidiPlayer, add:
self._files_cache = None
self._files_dirty = True

def invalidate_file_cache(self):
    self._files_dirty = True

def list_files(self, ...):
    if self._files_dirty or self._files_cache is None:
        self._files_cache = self._scan_files(...)
        self._files_dirty = False
    return self._files_cache
```

Call `invalidate_file_cache()` after upload/delete/rename operations.

---

### 8. Recorder count-in race: state set to `"recording"` from background thread without lock

**File:** `software/src/quick_recorder.py:248`

`_count_in_worker` runs in a background thread and sets `self._state = "recording"` without holding `self._lock`. Meanwhile, `toggle()` checks `self._state` without a lock too. If the user presses Record exactly as the count-in completes, both paths could execute simultaneously.

```python
# quick_recorder.py:248 — no lock
self._state = "recording"
self._record_start = time.monotonic()
```

**Impact:** Could result in a double-start or recording starting with stale `_record_start`. The timing window is narrow but real with a foot pedal.

**Fix:** Guard state transitions with `self._lock`:

```python
def _count_in_worker(self) -> None:
    triggered = self._count_in_event.wait(timeout=30.0)
    with self._lock:
        if not triggered or self._state != "count_in":
            if self._state == "count_in":
                self._state = "idle"
            return
        self._state = "recording"
        self._record_start = time.monotonic()
        self._record_start_tick = self._tick
```

---

### 9. Player `_play_loop` doesn't respect `_paused` during `time.sleep` for message timing

**File:** `software/src/midi_player.py:402-403`

When `time.sleep(msg.time / self._tempo_factor)` is sleeping for a long gap between messages (common in MIDI files with rests), `pause()` won't take effect until the sleep finishes. For a whole-note rest at 60 BPM, that's a 4-second delay before pause responds.

```python
# midi_player.py:402 — non-interruptible sleep
if msg.time > 0:
    time.sleep(msg.time / self._tempo_factor)  # blocks pause for duration
```

**Fix:** Use a `threading.Event` for stop/pause and `.wait()` instead of `sleep()` — same pattern used by the looper and recorder:

```python
# In __init__:
self._stop_event = threading.Event()

# In _play_loop:
if msg.time > 0:
    delay = msg.time / self._tempo_factor
    if self._stop_event.wait(delay):
        return  # stopped

# Handle pause separately with a tighter loop:
while self._paused and self._running:
    if self._stop_event.wait(0.05):
        return

# In stop():
self._stop_event.set()
```

---

### 10. Hotplug monitor `known_ports` can go stale if `rescan()` is called concurrently

**File:** `software/src/alsa_midi.py:188-223`

`_hotplug_loop` reads `known_ports` from `self.ports` under lock initially, but then the variable is updated without synchronization. If `rescan()` is called from another thread (via the `device.rescan` IPC command), `known_ports` could become stale and trigger false connect/disconnect events.

**Fix:** Re-read `self.ports` under lock at the top of each hotplug iteration instead of relying on the local `known_ports` variable:

```python
while self._running:
    try:
        with self._lock:
            known_ports = set(self.ports.keys())
        current_ports = set(self.scan_devices())
        # ... rest of detection logic
```

---

### 11. `SECRET_KEY` is hardcoded

**File:** `software/src/ui_web.py:67`

```python
app.config["SECRET_KEY"] = "midi-box-dev"
```

Flask uses this for session signing. Since there are no user sessions or CSRF tokens in this app, impact is nil — but if Flask sessions are ever added, this is an immediate vulnerability.

**Fix:** Generate a random key at startup:

```python
import os
app.config["SECRET_KEY"] = os.urandom(24).hex()
```

---

## IMPROVEMENTS

### 12. Bare `except: pass` silently swallows errors in ClockManager tick subscribers

**File:** `software/src/clock_manager.py:347-348`

```python
for sub in list(self._tick_subs):
    try:
        sub(tick, beat, bar, True)
    except Exception:
        pass  # a crashing subscriber is silently ignored forever
```

Same pattern at lines 112-114, 241-243, 341-342. If a subscriber throws repeatedly, there's no log, no error count, nothing.

**Fix:** Log at DEBUG level at minimum:

```python
except Exception as e:
    logger.debug("Tick subscriber error: %s", e)
```

---

### 13. State is saved to disk on every single route/preset/config change

**File:** `software/src/state.py:105-109`

Every `set_preset()`, `set_routes()`, `set_clock()`, `set_device_override()`, `set_launcher_state()`, etc. calls `self.save()` immediately. During startup restore or bulk operations, this can write the state file dozens of times in rapid succession. Each save also copies the current file to a backup first.

**Fix:** Add a dirty flag and debounce saves:

```python
import threading

class StateManager:
    def __init__(self, ...):
        ...
        self._save_timer = None
        self._save_lock = threading.Lock()

    def _schedule_save(self, delay=1.0):
        """Debounce saves — write at most once per second."""
        with self._save_lock:
            if self._save_timer:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(delay, self.save)
            self._save_timer.daemon = True
            self._save_timer.start()

    def set_routes(self, routes):
        self.state["routes"] = routes
        self._schedule_save()

    # ... same for other setters
```

Keep the explicit `save()` call in `_save_state()` (shutdown) to flush immediately.

---

### 14. `updater._detect_update_type` runs `git show` on tags that may not be fetched locally

**File:** `software/src/updater.py:109-114`

`git show {latest_tag}:scripts/pi_setup.sh` will fail if the tag hasn't been fetched yet (only `ls-remote` was called, not `fetch`). The function falls back to `"simple"`, which is safe, but the detection is basically always wrong for new remote tags.

**Fix:** Run `git fetch --tags origin` before the `git show` comparison, or use `git diff` against the remote ref directly:

```python
subprocess.run(
    ["git", "fetch", "--tags", "origin"],
    capture_output=True, timeout=30, cwd=str(_REPO_ROOT),
)
```

---

### 15. Dead `_emit_midi_clock` method in ClipLauncher (related to Bug #1)

**File:** `software/src/clip_launcher.py:193-202`

`_emit_midi_clock` and `_output_devices_callback` are dead code once Bug #1 is fixed. ClockManager handles all clock output. These can be removed along with the duplicate clock emission.

**Fix:** After fixing Bug #1, delete:
- `_emit_midi_clock` method (lines 193-202)
- `self._output_devices_callback` field (line 73)
- The assignment in `main.py:146`: `self.launcher._output_devices_callback = self._get_output_device_names`

---

### 16. Recorder `_to_midi_file` uses hardcoded 120 BPM tempo instead of actual recording BPM

**File:** `software/src/quick_recorder.py:459`

```python
track.append(mido.MetaMessage("set_tempo", tempo=DEFAULT_TEMPO, time=0))
# DEFAULT_TEMPO = 500_000 = 120 BPM, regardless of actual ClockManager BPM
```

The saved `.mid` file always claims 120 BPM regardless of the actual tempo during recording. Since the recorder stores real-time offsets (seconds) and converts to ticks using 120 BPM math, the timing is preserved — but the tempo metadata in the file is wrong, which affects how other DAWs display the file.

**Fix:** Use the actual BPM from ClockManager:

```python
def _to_midi_file(self, events: list) -> mido.MidiFile:
    bpm = self._clock_manager.bpm if self._clock_manager else 120.0
    tempo = int(60_000_000 / bpm)  # microseconds per beat
    mid = mido.MidiFile(type=0, ticks_per_beat=TICKS_PER_BEAT)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
    # ... also update tick conversion to use actual tempo:
    ticks = int(offset_sec * TICKS_PER_BEAT * 1_000_000 / tempo)
```

---

## Priority Summary

| # | Severity | Issue | Impact |
|---|----------|-------|--------|
| 1 | **BUG** | Double clock output | All synths receive 2x tempo |
| 2 | **BUG** | Filter transport mismatch | Filtering doesn't work as documented |
| 5 | **BUG** | Flask KeyError crashes | API returns 500 on bad input |
| 3 | **BUG** | Activity tracking race | Lost message counts (cosmetic) |
| 4 | **BUG** | Looper unsubscribe miss | Overdub loses ticks if another slot stops |
| 7 | **RISK** | File parsing 10x/sec | Unnecessary CPU/disk I/O |
| 9 | **RISK** | Player pause latency | Pause unresponsive for seconds |
| 8 | **RISK** | Recorder state race | Double-start on fast pedal press |
| 13 | **IMPROVE** | Excessive disk writes | State file written dozens of times on changes |
| 12 | **IMPROVE** | Silent subscriber errors | Bugs hidden by bare except:pass |
