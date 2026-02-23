# CLAUDE.md — MIDI Box Project Reference

## What Is This?

A custom MIDI router/patchbay running on a Raspberry Pi 4. Routes MIDI between 10 connected devices (6 USB + 4 hardware 5-Pin DIN). Controlled via a web UI from a phone or laptop. Can also act as a USB MIDI interface for a Mac (DAW mode).

## Operating Modes

- **Standalone**: Pi routes MIDI internally. User controls routing via web UI (WiFi hotspot).
- **DAW**: Pi appears as a USB MIDI device to Mac (Logic Pro). Routes hardware ↔ Mac.
- **Dev**: Runs on macOS without hardware. Use `--mock` flag.

Auto-detected at startup; override with `--mode standalone|daw` and `--platform mac|pi`.

## Project Structure

```
midi-box/
├── CLAUDE.md                      ← you are here
├── README.md
├── docs/
│   ├── software-arch.md           ← architecture decisions, latency targets
│   ├── gear-inventory.md          ← MIDI specs of all 10 devices
│   └── build-phases.md
├── hardware/                      ← schematics, PCB, BOM
└── software/
    ├── src/                       ← all Python source (15 modules)
    ├── config/
    │   ├── devices.yaml           ← USB IDs → device names, serial ports → DIN connectors
    │   └── midi_box.yaml          ← app settings (platform, WiFi, web UI port)
    ├── presets/                   ← JSON routing presets
    ├── data/
    │   └── state.json             ← persisted state (routes, preset, device overrides)
    ├── web_ui/
    │   ├── templates/             ← index.html, display.html (Jinja2)
    │   └── static/                ← app.js, style.css
    └── requirements.txt
```

## Tech Stack

- **Backend**: Python 3, Flask, mido, python-rtmidi, pyserial, pyyaml, psutil
- **Frontend**: Vanilla JS + HTML/CSS (no build step needed)
- **Hardware**: Pi native UARTs for 4× MIDI OUT (DIN-5), Linux libcomposite (USB gadget), Raspberry Pi 7" touchscreen (DSI + Chromium kiosk)
- **Platform**: Raspberry Pi 4 (production), macOS (dev/testing)

## Architecture — Dual Process

```
Process 1: MIDI Engine (src/main.py)
  └── owns all hardware: USB MIDI (rtmidi/ALSA), Pi native UARTs (MIDI OUT), USB gadget port
  └── core routing loop: poll inputs → route → send outputs
  └── handles commands from Flask via Queue

Process 2: Flask Web UI (src/ui_web.py)
  └── reads shared state dict (~5 Hz updates from engine)
  └── sends commands to engine via Queue
  └── serves REST API + HTML pages

IPC (src/ipc.py)
  └── multiprocessing.Manager().dict()   ← shared state (devices, routes, MIDI log)
  └── multiprocessing.Manager().Queue()  ← Flask → engine commands
  └── results dict                       ← engine → Flask responses
```

## Key Source Files

| File | Responsibility |
|------|---------------|
| `src/main.py` | Entry point, process spawner, main MIDI loop |
| `src/clock_manager.py` | **Unified clock** — single BPM + source for all modules; 96 PPQ tick distribution; ext clock watchdog |
| `src/router.py` | Route table, routing logic, port activity tracking |
| `src/midi_filter.py` | Per-route filtering (channel, message type, velocity, CC) |
| `src/alsa_midi.py` | USB MIDI via ALSA/rtmidi, hotplug detection |
| `src/hw_midi.py` | 5-Pin DIN MIDI OUT via Pi native UARTs (/dev/ttyAMA0,2,3,4) |
| `src/gadget.py` | USB gadget config (Pi as MIDI device to Mac) |
| `src/device_registry.py` | USB ID → friendly name mapping, direction/channel overrides |
| `src/preset_manager.py` | Load/save routing presets from JSON |
| `src/state.py` | Persist/restore app state to `data/state.json` |
| `src/clip_launcher.py` | Ableton-style clip playback, quantized launching, subscribes to ClockManager ticks |
| `src/midi_player.py` | MIDI file playback with tempo/loop control |
| `src/quick_recorder.py` | Live MIDI capture with quantize, count-in, save to .mid; syncs to ClockManager |
| `src/midi_looper.py` | 4-slot MIDI looper with overdub, quantize, count-in; syncs to ClockManager |
| `src/midi_logger.py` | Ring buffer MIDI monitor (500 messages), thread-safe |
| `src/ipc.py` | IPC bridge (shared state, command queue, results) |
| `src/ui_web.py` | Flask app, REST API, web UI serving |

## Connected Gear

**USB MIDI (6 devices):**
- Arturia KeyLab 88 MK2 — master controller
- Arturia KeyStep — step sequencer
- Behringer Model D — mono synth
- Roland JP-08 — polysynth
- Arturia MicroBrute — mono synth
- Roland SP-404 MK2 — sampler

**5-Pin DIN (4 devices, MIDI OUT only, Pi native UARTs):**
- Korg MS-20 Mini (/dev/ttyAMA0, GPIO 14)
- Korg Volca #1   (/dev/ttyAMA2, GPIO 4)
- Korg Volca #2   (/dev/ttyAMA3, GPIO 8)
- Korg Volca #3   (/dev/ttyAMA4, GPIO 12)

## Route / Preset Format

```json
{
  "name": "My Preset",
  "routes": [
    { "from": "KeyLab 88 MK2", "to": "MS-20 Mini", "filter": {} },
    { "from": "KeyLab 88 MK2", "to": "Roland JP-08", "filter": { "channel": 3 } }
  ],
  "clock_source": "KeyLab 88 MK2"
}
```

Filter options: `channels` (list, 1-16), `remap_channel` (1-16), `message_types` (list: `"note"`, `"cc"`, `"program_change"`, `"pitchwheel"`, `"aftertouch"`, `"clock"`, `"sysex"`), `velocity_min/max` (0-127), `cc_numbers` (list), `block_clock` (bool), `block_sysex` (bool).

## Recording / Looper

Both the Quick Recorder and MIDI Looper support clock-synced recording.

**Unified Clock (ClockManager):**

All modules share a single `ClockManager` instance as the source of truth for BPM and clock source:

- `internal` — Pi generates its own clock. Set BPM anywhere (Launcher page, Settings page) and it propagates everywhere.
- `<device_name>` — sync to 0xF8 MIDI clock from a named hardware device. BPM auto-detected from tick interval. If the device stops sending for 2 seconds, the system falls back to internal clock automatically and shows a warning banner.

**Quantize Options** (at 96 PPQ internal resolution):

| Quantize | Ticks |
|---|---|
| Free | — (no quantize, raw real-time) |
| 1/16 note | 24 |
| 1/8 note | 48 |
| 1/4 note (beat) | 96 |
| 1 bar | 96 × beats_per_bar |
| 2 bars | × 2 |
| 4 bars | × 4 |

**Count-in**: When quantize is not "free", pressing record enters a "count_in" state. Recording starts automatically at the next quantum boundary. Visual beat dots pulse during count-in.

**Quantized loop length**: When recording stops, the loop length snaps UP to the nearest quantum boundary. This ensures seamless looping on the beat grid.

**Quick Recorder** (`src/quick_recorder.py`):

- Single-slot live capture from ALL hardware MIDI inputs
- Playback through router (applies existing routing rules)
- Save recordings to `.mid` files
- State machine: `idle → count_in → recording → stopped/playing`

**MIDI Looper** (`src/midi_looper.py`):

- 4 independent loop slots with per-slot source/destination
- Overdub: layer new notes while playing (overdub does NOT re-quantize loop length)
- State machine per slot: `empty → count_in → recording → playing ↔ overdubbing → stopped`

**Tick Subscriber Mechanism**: `ClockManager` exposes `register_tick_subscriber(fn)` / `unregister_tick_subscriber(fn)`. Subscribers receive `(tick, beat, bar, transport_running)` on each internal tick. The Launcher, Recorder, and Looper all subscribe to ClockManager — they no longer maintain their own clocks.

## State Persistence

Saved to `software/data/state.json`. Includes: current preset, active routes, clock source, device overrides, clip launcher state, recorder clock settings, looper clock settings. Auto-backup before each save. Restored on startup.

## How to Run (Dev / macOS)

```bash
cd software
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 src/main.py --mode standalone --platform mac --mock -v
# Web UI at http://localhost:8080
```

Useful flags: `--list-devices`, `--list-presets`, `--preset NAME`, `--port PORT`.

## Web UI Pages

Dashboard, Routing (patchbay matrix), Launcher (clip session view), Presets, MIDI Monitor, Record (quick recorder), Looper (4-slot MIDI looper), Player (MIDI file), Logs, System, Settings.

REST API base: `http://<pi-ip>:8080/api/...`

## Key Design Decisions

1. **MIDI engine owns all hardware** — Flask never touches MIDI objects directly.
2. **IPC via Manager dict/queue** — decouples real-time MIDI from web serving.
3. **5 Hz state push** — engine updates shared state dict every 0.2s for UI refresh.
4. **Device registry** — separates USB IDs from friendly names; overrides saved to state.
5. **Preset JSON** — human-readable, shareable routing snapshots.
6. **Unified ClockManager** — single source of truth for BPM and clock source. All modules (Launcher, Recorder, Looper, Player) read from it. Changing BPM on any page propagates everywhere. External MIDI clock loss detected by watchdog (2 s timeout) → automatic fallback to internal.
7. **USB gadget** — Linux libcomposite/configfs makes Pi appear as multi-port MIDI interface.
8. **Clock-synced recording** — recorder/looper subscribe to ClockManager tick events. Count-in waits for quantum boundary. Loop lengths snap to grid.

## Hardware / Power

**Single 5V 5A input powers the whole box directly — no buck converter.**

```
[5V 5A barrel jack]
        │
        ├──→ Raspberry Pi 4 (GPIO 5V pins — USB-C kept free for DAW mode)
        ├──→ Waveshare USB Hub #1 (5V, 4× USB 2.0, 3 MIDI devices)
        └──→ Waveshare USB Hub #2 (5V, 4× USB 2.0, 3 MIDI devices)
```

| Component | 5V current draw |
|---|---|
| Pi 4 + 5" touchscreen | ~2.0A |
| 2× Waveshare hubs + 6 USB MIDI devices | ~1.2A |
| MIDI OUT board (LEDs, 8× 220Ω resistors) | ~0.1A |
| **Realistic total** | **~3.3A** (5A capacity = comfortable headroom) |

- Box is closed — only DIN-5 MIDI ports and USB-A ports visible externally
- 5" DSI touchscreen mounted on box face — shows QR codes + routing UI (Chromium kiosk)
- See `hardware/bom.md` for full component list and power table

## Notes / TODOs (update me!)

- ~~WiFi: Pi runs dual WiFi — home network (wlan0) + hotspot (uap0 virtual interface)~~ ✓ Done
- ~~SC16IS752 UART bridge~~ — replaced by Pi 4 native UARTs via dtoverlay ✓
- ~~OLED + rotary encoder~~ — replaced by 5" DSI touchscreen + Chromium kiosk ✓
- Pi deployment: `scripts/pi_setup.sh` + `scripts/inject_sdcard.sh`
- `pi_setup.sh` now installs UART overlays in `/boot/firmware/config.txt` and sets up `midi-box-kiosk.service`
- Touchscreen kiosk boots to `/display` page (WiFi QR + status); full web UI accessible via touch
- systemd service defined in `docs/software-arch.md`
- Build is in Phase 3/5 (hardware MIDI stage) — see `docs/build-phases.md`
