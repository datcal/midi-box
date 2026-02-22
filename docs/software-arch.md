# Software Architecture

## Overview

The MIDI Box software runs on Raspberry Pi OS Lite and handles:
1. USB MIDI device management (via ALSA)
2. Hardware MIDI OUT (via Pi native UARTs at 31250 baud)
3. MIDI message routing between any port
4. USB gadget mode (appearing as MIDI device to Mac)
5. User interface (web UI + touchscreen kiosk)

## System Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    Application Layer                     │
│                                                          │
│  ┌──────────┐  ┌──────────────────┐  ┌────────────────┐ │
│  │ Web UI   │  │  Clip Launcher   │  │  MIDI Player   │ │
│  │ (Flask)  │  │  (clip_launcher) │  │  (midi_player) │ │
│  └────┬─────┘  └────────┬─────────┘  └───────┬────────┘ │
│       │        ┌────────┴─────────┐           │          │
│       │        │  Tick Subscribers │           │          │
│       │        │  ┌─────────────┐ │           │          │
│       │        │  │ Recorder    │ │           │          │
│       │        │  │ Looper      │ │           │          │
│       │        │  └─────────────┘ │           │          │
│       │        └──────────────────┘           │          │
│       └─────────────────┬─────────────────────┘          │
│                          │                               │
│  ┌───────────────────────┴───────────────────────────┐  │
│  │              Routing Engine (router.py)            │  │
│  │                                                    │  │
│  │  - Routing table management                        │  │
│  │  - MIDI channel filtering / remapping              │  │
│  │  - MIDI message filtering (CC, note, clock, etc)   │  │
│  │  - Merge multiple inputs to one output             │  │
│  │  - Split one input to multiple outputs             │  │
│  └──────────┬──────────────────────┬─────────────────┘  │
│             │                      │                     │
│  ┌──────────┴──────────┐  ┌───────┴──────────────────┐  │
│  │  USB MIDI Layer     │  │  Hardware MIDI Layer     │  │
│  │  (alsa_midi.py)     │  │  (hw_midi.py)            │  │
│  │                     │  │                           │  │
│  │  - ALSA sequencer   │  │  - Pi native UARTs       │  │
│  │  - Device hotplug   │  │  - 31250 baud serial     │  │
│  │  - Port enumeration │  │  - MIDI OUT only         │  │
│  └──────────┬──────────┘  └───────┬──────────────────┘  │
│             │                      │                     │
│  ┌──────────┴──────────┐  ┌───────┴──────────────────┐  │
│  │  USB Gadget Layer   │  │  Pi Device Tree Overlays │  │
│  │  (gadget.py)        │  │  (kernel / config.txt)   │  │
│  │                     │  │                           │  │
│  │  - libcomposite     │  │  - uart3/uart4/uart5      │  │
│  │  - MIDI function    │  │  - disable-bt (UART0)     │  │
│  │  - Mac ↔ Pi bridge  │  │                           │  │
│  └─────────────────────┘  └──────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## File Structure

```
software/
├── src/
│   ├── main.py              ← Entry point, process spawner, main MIDI loop
│   ├── router.py            ← Core routing engine
│   ├── alsa_midi.py         ← USB MIDI port management via ALSA
│   ├── hw_midi.py           ← Hardware MIDI OUT via Pi native UARTs
│   ├── gadget.py            ← USB gadget MIDI device management
│   ├── preset_manager.py    ← Load/save/switch routing presets
│   ├── clip_launcher.py     ← Ableton-style clip session, 96 PPQ clock, tick subscribers
│   ├── midi_player.py       ← MIDI file playback with tempo/loop control
│   ├── quick_recorder.py    ← Live MIDI capture with BPM/quantize/count-in
│   ├── midi_looper.py       ← 4-slot MIDI looper with overdub, BPM/quantize/count-in
│   ├── midi_logger.py       ← Ring buffer MIDI monitor (thread-safe)
│   ├── ui_web.py            ← Flask web interface + REST API
│   ├── ipc.py               ← IPC bridge (shared state, command queue)
│   ├── device_registry.py   ← Known device database & naming
│   ├── state.py             ← Persist/restore app state to JSON
│   └── midi_filter.py       ← Channel/message type filtering
├── config/
│   ├── devices.yaml         ← Device name mapping (USB ID → friendly name)
│   ├── midi_box.yaml        ← Main configuration file
│   └── gadget_config.sh     ← USB gadget setup script
├── presets/
│   └── *.json               ← Named routing presets
├── data/
│   ├── state.json           ← Persisted app state (routes, preset, overrides)
│   └── midi_files/          ← Uploaded MIDI files for player/launcher
└── web_ui/
    ├── templates/
    │   ├── index.html       ← Main SPA (all pages)
    │   └── display.html     ← Kiosk display (QR + status)
    └── static/
        ├── style.css
        └── app.js
```

## Key Design Decisions

### 1. Dual-Process Architecture
- **Process 1 (MIDI engine)**: owns all hardware — ALSA ports, serial UARTs, USB gadget. Runs the real-time routing loop.
- **Process 2 (Flask)**: reads shared state, sends commands via queue. Never touches hardware directly.
- IPC: `multiprocessing.Manager` dict (state) + Queue (commands) + results dict.

### 2. Main Loop — Non-Blocking Poll
```python
while running:
    for port_name in alsa.get_input_ports():
        for msg in alsa.receive(port_name):   # drains all pending messages at once
            router.process_message(source, msg)
    process_commands()
    if state_update_due:
        push_shared_state()
    time.sleep(0.001)
```
All pending messages per port are drained in a single `iter_pending()` call each iteration, so simultaneous notes (chords, player bursts) are processed without per-message polling delay.

### 3. USB MIDI via ALSA
- `rtmidi` Python library (wraps ALSA sequencer)
- Auto-detect USB MIDI devices on hotplug via background polling thread (2s interval)
- Map ALSA port names to friendly names via `devices.yaml`

### 4. Hardware MIDI via Pi Native UARTs
- Pi 4 has 6 UARTs; 4 enabled via device tree overlays in `/boot/firmware/config.txt`
- `disable-bt` frees UART0 (GPIO 14 → `/dev/ttyAMA0`)
- `uart3/uart4/uart5` overlays → GPIO 4/8/12 → `/dev/ttyAMA2/3/4`
- Access via `pyserial` at 31250 baud, non-blocking reads (`timeout=0`)
- All 4 DIN ports are MIDI OUT only

### 5. USB Gadget Mode
- `libcomposite` kernel module creates a USB MIDI gadget
- Pi appears to Mac as a class-compliant USB MIDI device
- Bridge: Mac → gadget port → routing engine → hardware ports (and vice versa)

### 6. Clip Launcher Clock
- Internal clock thread ticks at 96 PPQ (4× MIDI standard 24 PPQ)
- MIDI clock (0xF8) emitted every 4 internal ticks = standard 24 PPQ output
- Clip launches quantized to beat/bar/2bar/4bar boundaries
- External clock mode: syncs to incoming MIDI clock from any device

### 7. Clock-Synced Recording (Recorder & Looper)

Both the Quick Recorder and MIDI Looper support clock-synced recording via the clip launcher's tick subscriber mechanism.

**Tick Subscriber Pattern:**

```text
ClipLauncher._advance_tick()
  → for each subscriber: fn(tick, beat, bar, transport_running)
    → QuickRecorder._on_tick()   (checks for quantum boundary → starts recording)
    → MidiLooper._on_tick()      (checks for quantum boundary → starts slot recording)
```

**Clock Sources** (configurable per system):

- `standalone` — own clock thread (same pattern as launcher's `_internal_clock_loop`)
- `launcher` — subscribes to launcher's tick callbacks (shared BPM/transport)
- `external` — syncs to incoming MIDI clock from hardware

**Quantize Grid** (at 96 PPQ):

- `free`: no quantize (immediate start/stop, raw-length loops)
- `1/16`: 24 ticks, `1/8`: 48 ticks, `1/4`: 96 ticks (1 beat)
- `bar`: 96 × beats_per_bar, `2bar`: × 2, `4bar`: × 4

**Count-in Flow:**

1. User presses record → state becomes `count_in`
2. Subscribe to clock (launcher ticks or start standalone clock)
3. On each tick: check `tick % quantum_ticks == 0`
4. When boundary hit: transition to `recording`, set `_record_start = time.monotonic()`

**Quantized Loop Length:**

- On stop: `elapsed_ticks = raw_seconds / tick_interval`
- Round UP to nearest quantum: `((elapsed // qt) + 1) * qt`
- Convert back to seconds for playback loop duration

**State Persistence:** Clock settings (`source`, `bpm`, `quantize`, `beats_per_bar`) saved to `state.json` under `recorder_clock` and `looper_clock` keys.

### 8. Mode Detection
```python
def detect_mode():
    # Check USB gadget UDC state
    udc_state = read_file("/sys/class/udc/fe980000.usb/state")
    if udc_state.strip() == "configured":
        return "daw"  # Mac is connected
    return "standalone"
```

## Configuration Format

### devices.yaml
```yaml
usb_devices:
  "1c75:0206":
    name: "KeyLab 88 MK2"
    type: controller
    direction: both
  "1c75:0288":
    name: "KeyStep"
    type: controller
    direction: both
  "1397:00d2":
    name: "Behringer Model D"
    type: synth
    direction: both
  "0582:0191":
    name: "Roland JP-08"
    type: synth
    direction: both
  "1c75:0207":
    name: "Arturia MicroBrute"
    type: synth
    direction: both
  "0582:01e5":
    name: "Roland SP-404 MK2"
    type: sampler
    direction: both

hardware_ports:
  ttyAMA0:
    name: "MS-20 Mini"
    direction: out
  ttyAMA2:
    name: "Volca 1"
    direction: out
  ttyAMA3:
    name: "Volca 2"
    direction: out
  ttyAMA4:
    name: "Volca 3"
    direction: out
```

### Preset Format (JSON)
```json
{
  "name": "Live Keys",
  "description": "KeyLab controls everything, KeyStep sequences Volcas",
  "routes": [
    {
      "from": "KeyLab 88 MK2",
      "to": "MS-20 Mini",
      "filter": { "channels": [1] }
    },
    {
      "from": "KeyLab 88 MK2",
      "to": "Roland JP-08",
      "filter": { "channels": [3] }
    },
    {
      "from": "KeyStep",
      "to": "Volca 1",
      "filter": { "channels": [4] }
    }
  ],
  "clock_source": "KeyStep"
}
```

Filter fields: `channels` (list, 1-16), `remap_channel` (1-16), `message_types` (list: `"note"`, `"cc"`, `"program_change"`, `"pitchwheel"`, `"aftertouch"`, `"clock"`, `"sysex"`), `velocity_min/max` (0-127), `cc_numbers` (list), `block_clock` (bool), `block_sysex` (bool).

## Dependencies

```
mido>=1.3.0          # MIDI message handling
python-rtmidi>=1.5.0 # ALSA MIDI backend
pyserial>=3.5        # Hardware UART (Pi native)
flask>=3.0           # Web UI
pyyaml>=6.0          # Configuration files
psutil>=5.9          # System stats (CPU, RAM, disk)
```

## Systemd Service

Single service — Flask runs as a subprocess of the MIDI engine (not a separate service).

```ini
[Unit]
Description=MIDI Box Router
After=network.target sound.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/midi-box/software
ExecStartPre=/opt/midi-box/software/config/gadget_config.sh
ExecStart=/opt/midi-box/software/venv/bin/python3 src/main.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Kiosk display is a separate service (`midi-box-kiosk.service`) managed by `pi_setup.sh`.

## Latency

| Path | Typical | Notes |
|---|---|---|
| USB → USB | ~2–3ms | USB 2.0 frame (1ms) × 2 + software (~20µs) |
| USB → 5-Pin DIN | ~3–4ms | + serial TX (~1ms per 3-byte message at 31250 baud) |
| USB → Mac (gadget) | ~3–4ms | Similar to USB→USB + gadget overhead |
| End-to-end (key press → sound) | ~5–10ms | Includes destination synth latency |

Serial note: 12 simultaneous notes to a DIN port take ~11.5ms to fully transmit (physics of 31250 baud). USB destinations batch notes efficiently and don't have this constraint.
