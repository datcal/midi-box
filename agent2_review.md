# MIDI Box Code Review

## Summary

A well-structured two-process MIDI router for Raspberry Pi 4. Process 1 (MIDI engine) owns all hardware via rtmidi/ALSA and pyserial. Process 2 (Flask) serves a web UI. IPC uses `multiprocessing.Manager` dict/queue. The codebase includes a clip launcher, MIDI player, looper, recorder, RTP-MIDI server, and USB gadget support. Overall quality is good — the architecture is sound, the clock system is well-designed, and the separation of concerns is clean. Below are the issues found.

---

## BUGS — Actually broken or will break under specific conditions

### 1. `_update_shared_state` calls `list_files()` on every 100ms tick — disk I/O in hot path

**File:** `src/main.py:1105` and `src/main.py:1112`

```python
status["files"] = self.launcher.list_files()    # line 1105
"files": self.player.list_files(),              # line 1112
```

`launcher.list_files()` and `player.list_files()` both do `mido.MidiFile(str(f))` on every `.mid` file to get duration/tracks. This parses MIDI headers from disk **10 times per second**. With many files, this adds significant latency to the state update cycle and can cause the 100ms interval to slip, making the UI feel sluggish.

**Fix:** Cache file listings, invalidate on upload/delete/rename operations only.

```python
# In ClipLauncher and MidiPlayer, add a cached file list:
class ClipLauncher:
    def __init__(self, ...):
        ...
        self._file_cache = None

    def list_files(self) -> list[dict]:
        if self._file_cache is not None:
            return self._file_cache
        files = []
        for f in sorted(MIDI_FILES_DIR.glob("*.mid")):
            try:
                mid = mido.MidiFile(str(f))
                files.append({"name": f.name, "duration": round(mid.length, 1), "tracks": len(mid.tracks)})
            except Exception:
                files.append({"name": f.name, "duration": 0, "tracks": 0})
        self._file_cache = files
        return files

    def _invalidate_file_cache(self):
        self._file_cache = None

    # Call _invalidate_file_cache() in upload(), delete_file(), etc.
```

---

### 2. Clip launcher `_advance_clip` has off-by-one: first event at tick 0 is skipped on loop restart

**File:** `src/clip_launcher.py:384-394`

```python
if clip.play_head >= clip.total_ticks:
    if clip.loop:
        clip.play_head = 0
        clip.event_cursor = 0
    ...
    return

clip.play_head += 1  # line 394
```

When the clip loops, `play_head` resets to 0 then the method returns without processing events at tick 0. On the next call, `play_head` increments to 1 before any events are checked. Events at absolute tick 0 are **never played on loop iterations after the first**.

**Fix:** After resetting `play_head = 0`, fall through to the event processing logic instead of returning:

```python
def _advance_clip(self, layer: Layer):
    clip = layer.clips[layer.active_clip]
    if clip.state != ClipState.PLAYING:
        return
    if not clip.events:
        return

    # End of clip check — do this BEFORE processing events
    if clip.play_head >= clip.total_ticks:
        if clip.loop:
            clip.play_head = 0
            clip.event_cursor = 0
            # Fall through to process tick-0 events
        else:
            self._stop_clip_clean(layer)
            clip.state = ClipState.STOPPED
            layer.active_clip = None
            return

    # Send all events at current play_head
    while clip.event_cursor < len(clip.events):
        ev_tick, msg = clip.events[clip.event_cursor]
        if ev_tick > clip.play_head:
            break
        self._send_clip_event(layer, msg)
        clip.event_cursor += 1

    clip.play_head += 1
```

---

### 3. `MidiFilter` transport filtering inconsistency with CLAUDE.md spec

**File:** `src/midi_filter.py:69`

```python
if self.message_types and "transport" not in self.message_types:
    return None
```

The filter checks for `"transport"` in `message_types`, but CLAUDE.md documents `"start"`, `"stop"`, `"continue"` as valid message_types — not `"transport"`. A user setting `message_types: ["start"]` would have their start messages **blocked** because `"transport" not in ["start"]` is True.

**Fix:** Check for both the meta-type and the specific type:

```python
# Handle transport
if message.type in ("start", "stop", "continue"):
    if self.block_clock:
        return None
    if self.message_types:
        # Accept if "transport" meta-type OR specific type is listed
        if "transport" not in self.message_types and message.type not in self.message_types:
            return None
    return message
```

---

### 4. IPC `send_command` result cleanup race and memory leak

**File:** `src/ipc.py:81-84`

```python
if cmd_id in self.results:
    result = dict(self.results[cmd_id])
    del self.results[cmd_id]
    return result
```

The `in` check and `del` are two separate proxy operations over the Manager connection. If the engine writes the result after the timeout at line 89, the `pop` there may miss it, leaving a stale entry in `results` forever. Over months of uptime, this leaks memory.

**Fix:** Add periodic cleanup of stale results, or use a timestamp-based eviction:

```python
def send_command(self, action: str, params: dict = None,
                 timeout: float = COMMAND_TIMEOUT) -> dict:
    cmd_id = str(uuid.uuid4())
    self.cmd_queue.put({"id": cmd_id, "action": action, "params": params or {}})

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = dict(self.results.pop(cmd_id))  # atomic pop
            return result
        except KeyError:
            pass
        time.sleep(0.005)

    logger.error(f"IPC command timeout: {action}")
    return {"ok": False, "error": "timeout"}
```

---

### 5. Double clock broadcast — launcher and ClockManager both send 0xF8

**File:** `src/clip_launcher.py:163-167`

```python
cm_source = self._clock_manager.source if self._clock_manager else "internal"
if cm_source == "internal" and tick % CLOCK_EMIT_INTERVAL == 0:
    self._emit_midi_clock()
```

`ClipLauncher._emit_midi_clock()` sends clock to all output devices. But `ClockManager` already calls `self._midi_clock_callback()` at 24 PPQ (line 338 of `clock_manager.py`), which is wired to `MidiBox._send_clock_to_outputs()`. Devices receive **double clock ticks** — 48 PPQ instead of 24.

**Fix:** Remove the clock emission from the launcher entirely. It's legacy code from before ClockManager was introduced:

```python
def _on_clock_tick(self, tick: int, beat: int, bar: int, running: bool):
    with self._lock:
        self._tick = tick
        self._beat = beat
        self._bar = bar

        if not self._transport_running:
            return

        # ClockManager handles MIDI clock broadcast — don't duplicate here

        if self._is_quantum_boundary():
            self._process_queued_launches()

        for layer in self.layers:
            if layer.active_clip is not None:
                self._advance_clip(layer)
```

Also remove `_emit_midi_clock()` method and `_output_devices_callback` since they become unused.

---

### 6. Looper `_on_tick` doesn't unsubscribe after all count-ins complete

**File:** `src/midi_looper.py:232-246`

The `_on_tick` callback is registered when any slot enters count-in. When recording completes, unsubscribe happens at line 322-323:

```python
if not any(s.state in ("count_in", "recording") for s in self.slots):
    self._unsubscribe_from_clock()
```

But `_on_tick` continues to fire for every tick while slots are in "playing" state, doing unnecessary work (iterating all slots checking for "count_in" state on every single tick). Not a correctness bug but wastes cycles on the clock hot path (~192 calls/sec at 120 BPM).

**Fix:** Add unsubscribe in the stop path as well, or make the tick callback a no-op early:

```python
def _on_tick(self, tick: int, beat: int, bar: int, running: bool) -> None:
    self._tick = tick
    self._beat = beat
    self._bar = bar
    self._transport_running = running

    # Quick exit if no slots need clock-based triggering
    if not any(s.state == "count_in" for s in self.slots):
        return

    qt = _quantum_ticks(self._quantize, self._beats_per_bar)
    if qt <= 0 or tick == 0:
        return

    if tick % qt == 0:
        for slot in self.slots:
            if slot.state == "count_in":
                slot._count_in_event.set()
```

---

## RISKS — Works now but fragile under edge cases

### 7. Router `_rebuild_index` called outside the lock

**File:** `src/router.py:105-108`

```python
with self._lock:
    self.routes.append(route)
self._rebuild_index()   # ← outside lock
```

If two routes are added concurrently, the index could be rebuilt from an inconsistent `self.routes` state. The comment says "Assignment is atomic in CPython" but the **read** of `self.routes` in `_rebuild_index` happens without a lock while another thread could be mid-`list.append`.

**Fix:** Move `_rebuild_index()` inside the lock:

```python
def add_route(self, source, destination, midi_filter=None, name="") -> Route:
    route = Route(source=source, destination=destination,
                  midi_filter=midi_filter or MidiFilter.pass_all(), name=name)
    with self._lock:
        self.routes.append(route)
        self._rebuild_index()
    logger.info(f"Route added: {route.name}")
    return route
```

---

### 8. `LoopSlot` has no lock — state mutations from multiple threads

**File:** `src/midi_looper.py:74-180`

`LoopSlot.record_event()` is called from rtmidi's callback thread (via `on_midi_message`). `start_recording()` and `stop_recording()` are called from the main loop thread (via IPC commands). `_playback_worker` reads `slot._events` from yet another thread. The `snapshot_events()` does `list(self._events)` which is safe for iteration under CPython's GIL but fragile.

**Fix:** Add a threading lock to LoopSlot for event list mutations:

```python
class LoopSlot:
    def __init__(self, slot_id: int):
        ...
        self._lock = threading.Lock()

    def record_event(self, message):
        if self.state not in ("recording", "overdubbing"):
            return
        offset = time.monotonic() - self._record_start
        with self._lock:
            if self.state == "overdubbing":
                offset = offset % self.length if self.length else 0.0
                self._overdub.append((offset, message))
            elif offset <= MAX_LOOP_SECONDS:
                self._events.append((offset, message))

    def snapshot_events(self) -> list[tuple]:
        with self._lock:
            return list(self._events)
```

---

### 9. Clock source device disconnect doesn't reset clock source

**File:** `src/main.py:1300-1308`

If the user sets clock source to "KeyLab 88 MK2" and then unplugs it, `_on_usb_device_disconnected` unregisters the device but doesn't reset `clock_manager.source` or `router._clock_source`. The watchdog will detect clock loss after 2 seconds and fall back to internal, but the UI will still show the disconnected device as the clock source. On reconnect, the ALSA port name changes (new client number), so clock won't resume.

**Fix:**

```python
def _on_usb_device_disconnected(self, port_name: str):
    device = self.registry.find_by_port_id(port_name)
    if device:
        dev_name = device.name
        self.registry.unregister_device(dev_name)
        logger.info(f"Hotplug: {dev_name} disconnected")
        # If this was the clock source, fall back to internal
        if self.clock_manager.source == dev_name:
            logger.warning(f"Clock source '{dev_name}' disconnected — switching to internal")
            self.clock_manager.set_source("internal")
            self.router.set_clock_source(None)
            self.state.set_clock({"bpm": self.clock_manager.bpm, "source": "internal"})
    else:
        self.registry.unregister_device(port_name)
        logger.info(f"Hotplug: {port_name} disconnected")
    self._refresh_clock_outputs()
```

---

### 10. `_state()` returns the live proxy dict, not a snapshot

**File:** `src/ui_web.py:73-74`

```python
def _state():
    return bridge.state
```

Every Flask endpoint reads keys from the shared Manager dict directly. Each key access is a separate IPC round-trip to the Manager process. Under load with many concurrent requests, this adds latency. More importantly, reads of different keys within a single request can see different state snapshots.

**Fix:** For frequently-polled endpoints like `/api/poll`, take a snapshot once:

```python
@app.route("/api/poll")
def api_poll():
    st = dict(bridge.state)  # single IPC call, consistent snapshot
    clock = st.get("clock", {})
    return jsonify({
        "devices": list(st.get("activity", [])),
        "mode": st.get("mode", "standalone"),
        ...
    })
```

Note: `dict(bridge.state)` does a shallow copy of all keys in one Manager call.

---

### 11. Flask API endpoints don't validate `request.json` — will crash on malformed input

**File:** `src/ui_web.py:273-279`

```python
data = request.json
result = _cmd("route.add", {
    "from": data["from"],
    "to": data["to"],
```

If the request body is not valid JSON or missing required keys, `request.json` returns `None` and `data["from"]` throws `TypeError`. Several endpoints have this pattern.

**Fix:** Add a guard at the top of mutation endpoints:

```python
@app.route("/api/routes", methods=["POST"])
def api_routes_add():
    data = request.json
    if not data or "from" not in data or "to" not in data:
        return jsonify({"ok": False, "error": "Missing 'from' and 'to' fields"}), 400
    result = _cmd("route.add", {
        "from": data["from"],
        "to": data["to"],
        "filter": data.get("filter", {}),
        "name": data.get("name", ""),
    })
    return jsonify({"ok": result.get("ok", False), "route": result.get("route", "")})
```

---

### 12. `QuickRecorder._cancel_count_in` has TOCTOU race

**File:** `src/quick_recorder.py:255-257`

```python
self._count_in_event.set()      # unblock the worker
self._unsubscribe_from_clock()
self._state = "idle"
```

The worker thread at line 248 checks `self._state != "count_in"` after waking, but there's a small window where the worker wakes (event set), sees `_state` is still `"count_in"` (hasn't been set to `"idle"` yet), and proceeds to start recording.

**Fix:** Set state before signaling the event:

```python
def _cancel_count_in(self) -> None:
    self._state = "idle"              # set state FIRST
    self._count_in_event.set()        # THEN unblock the worker
    self._unsubscribe_from_clock()
    logger.info("Quick recorder: count-in cancelled")
```

---

## IMPROVEMENTS — Non-critical issues

### 13. Silent exception swallowing in clock tick subscribers

**File:** `src/clock_manager.py:347-348`

```python
for sub in list(self._tick_subs):
    try:
        sub(tick, beat, bar, True)
    except Exception:
        pass
```

If a subscriber raises, the error is silently swallowed. A broken launcher or recorder subscriber could silently stop working with no indication.

**Fix:** Log at debug level:

```python
for sub in list(self._tick_subs):
    try:
        sub(tick, beat, bar, True)
    except Exception as e:
        logger.debug("Tick subscriber %s raised: %s", sub, e)
```

---

### 14. `_CLOCK_MSG` is a mutable shared object used across threads

**File:** `src/main.py:33`

```python
_CLOCK_MSG = mido.Message("clock")
```

`mido.Message` objects are mutable. If any code path calls `.copy(channel=...)` or modifies it, the shared object is corrupted. In practice, clock messages have no mutable fields that get modified, so this is safe currently — but it's a latent hazard.

**Fix:** No immediate action needed, but add a comment warning against modification:

```python
# Pre-allocated clock message — reused on every tick to avoid GC churn.
# WARNING: Do not modify this object. It is shared across threads.
_CLOCK_MSG = mido.Message("clock")
```

---

### 15. `PresetManager` instantiated directly in Flask process

**File:** `src/ui_web.py:317-319`

```python
from preset_manager import PresetManager
pm = PresetManager()
data = pm.load(name)
```

The Flask process creates its own `PresetManager` to read preset files. This bypasses the IPC command pattern used everywhere else. If the preset directory changes or files are being written concurrently by the MIDI process, this could read a partially-written file.

**Fix:** Route through the IPC command queue like all other operations:

```python
@app.route("/api/presets/<name>")
def api_preset_get(name):
    result = _cmd("preset.get", {"name": name})
    if result.get("error"):
        return jsonify({"error": "not found"}), 404
    return jsonify(result.get("data", {}))
```

---

### 16. `updater._detect_update_type` runs `git show` on potentially unfetched tags

**File:** `src/updater.py:109-113`

`git show current_tag:scripts/pi_setup.sh` and `git show latest_tag:...` assume both tags exist locally. `git ls-remote` only queries the remote — the latest tag may not be fetched yet. This would fail silently and default to "simple".

**Fix:** Run `git fetch --tags` before comparing, or accept "simple" as the safe default (which the code already does).

---

### 17. `StateManager.save()` is called on every single state mutation

**File:** `src/state.py:103-114`

Every `set_preset()`, `set_routes()`, `set_clock()`, etc. calls `self.save()` which does a full JSON serialize + write + fsync cycle. During a preset load that sets routes and clock source, this writes to disk 2-3 times in quick succession. On an SD card this adds unnecessary wear.

**Fix:** Add a debounced save mechanism:

```python
class StateManager:
    def __init__(self, ...):
        ...
        self._dirty = False
        self._save_timer = None

    def _mark_dirty(self):
        self._dirty = True
        if self._save_timer is None:
            self._save_timer = threading.Timer(1.0, self._flush)
            self._save_timer.daemon = True
            self._save_timer.start()

    def _flush(self):
        self._save_timer = None
        if self._dirty:
            self.save()

    def set_preset(self, name: str):
        self.state["current_preset"] = name
        self._mark_dirty()   # instead of self.save()
```

---

### 18. `HardwareMidi._read_loop` builds the input port list once at startup

**File:** `src/hw_midi.py:188-191`

```python
input_ports = [
    p for p in self.ports.values()
    if p.direction in ("in", "both") and p.is_open
]
```

If a hardware port is opened after `start_reading()` is called, it won't be included in the read loop. Currently all HW ports are DIN-out only so this doesn't matter, but it would if bidirectional DIN were added.

**Fix:** Re-scan the port list periodically or on demand within the read loop.

---

## Priority List

### Critical
1. **Clip launcher tick-0 loop bug** (#2) — notes at beat 1 are dropped on every loop restart
2. **Double clock broadcast** (#5) — launcher and ClockManager both send 0xF8, devices get 48 PPQ instead of 24

### Should Fix
3. **Disk I/O in state update** (#1) — `list_files()` with MIDI parsing 10x/sec
4. **MidiFilter transport type mismatch** (#3) — filtering spec doesn't match code
5. **Count-in cancel race** (#12) — can start recording after cancel
6. **Clock source not reset on device disconnect** (#9)
7. **IPC result dict leak** (#4) — slow memory leak over weeks of uptime
8. **Flask JSON validation** (#11) — 500 errors on malformed requests

### Nice to Have
9. **Silent exception swallowing** (#13) — makes debugging clock issues very hard
10. **Router index outside lock** (#7)
11. **Looper thread safety** (#8)
12. **State manager write batching** (#17)
13. **PresetManager in Flask process** (#15)
14. **Unfetched tags in updater** (#16)
15. **IPC state snapshot** (#10)
16. **Looper tick unsubscribe** (#6)
17. **Shared mutable clock message** (#14)
18. **HW MIDI read loop port list** (#18)
