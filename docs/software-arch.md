# Software Architecture

## Overview

The MIDI Box software runs on Raspberry Pi OS Lite and handles:
1. USB MIDI device management (via ALSA)
2. Hardware MIDI I/O (via SC16IS752 UARTs)
3. MIDI message routing between any port
4. USB gadget mode (appearing as MIDI device to Mac)
5. User interface (OLED + web)

## System Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    Application Layer                     │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐ │
│  │ Web UI   │  │ OLED UI  │  │ Preset   │  │ Mode   │ │
│  │ (Flask)  │  │ (display)│  │ Manager  │  │ Switch │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └───┬────┘ │
│       └──────────────┴─────────────┴─────────────┘      │
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
│  │  - ALSA sequencer   │  │  - SC16IS752 driver      │  │
│  │  - Device hotplug   │  │  - 31250 baud serial     │  │
│  │  - Port enumeration │  │  - Pi native UART        │  │
│  └──────────┬──────────┘  └───────┬──────────────────┘  │
│             │                      │                     │
│  ┌──────────┴──────────┐  ┌───────┴──────────────────┐  │
│  │  USB Gadget Layer   │  │  GPIO / I2C              │  │
│  │  (gadget.py)        │  │  (Linux kernel drivers)  │  │
│  │                     │  │                           │  │
│  │  - libcomposite     │  │  - sc16is7xx driver      │  │
│  │  - MIDI function    │  │  - device tree overlay   │  │
│  │  - Mac ↔ Pi bridge  │  │                           │  │
│  └─────────────────────┘  └──────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## File Structure

```
software/
├── src/
│   ├── main.py              ← Entry point, mode detection, startup
│   ├── router.py            ← Core routing engine
│   ├── alsa_midi.py         ← USB MIDI port management via ALSA
│   ├── hw_midi.py           ← Hardware MIDI (SC16IS752 + native UART)
│   ├── gadget.py            ← USB gadget MIDI device management
│   ├── preset_manager.py    ← Load/save/switch routing presets
│   ├── ui_oled.py           ← OLED display + rotary encoder interface
│   ├── ui_web.py            ← Flask web interface
│   ├── device_registry.py   ← Known device database & naming
│   └── midi_filter.py       ← Channel/message type filtering
├── config/
│   ├── devices.yaml         ← Device name mapping (USB ID → friendly name)
│   ├── midi_box.yaml        ← Main configuration file
│   └── gadget_config.sh     ← USB gadget setup script
├── presets/
│   ├── default.json         ← Default startup routing
│   ├── live_keys.json       ← KeyLab → all synths
│   ├── sequencer.json       ← KeyStep → Volcas + MS-20
│   ├── recording.json       ← Everything → Logic Pro
│   └── sp404_live.json      ← SP-404 centered live setup
└── web_ui/
    ├── templates/
    │   └── index.html       ← Patchbay-style routing UI
    └── static/
        ├── style.css
        └── patchbay.js      ← Interactive routing matrix
```

## Key Design Decisions

### 1. Routing Engine
- Central routing table: list of `(source_port, dest_port, filter)` tuples
- Runs in a tight loop reading all inputs and forwarding to mapped outputs
- Filters applied per-route: channel, message type, velocity range
- Thread per input port for lowest latency

### 2. USB MIDI via ALSA
- Use `rtmidi` Python library (wraps ALSA sequencer)
- Auto-detect USB MIDI devices on hotplug via `udev` rules
- Map USB vendor/product IDs to friendly names (e.g., `0x1c75:0x0206` → "KeyLab 88 MK2")

### 3. Hardware MIDI via SC16IS752
- Linux has a built-in `sc16is7xx` kernel driver
- Creates `/dev/ttySC0`, `/dev/ttySC1`, etc.
- Access via `pyserial` at 31250 baud
- No custom driver needed

### 4. USB Gadget Mode
- Use `libcomposite` kernel module to create a USB MIDI gadget
- Appears to Mac as class-compliant USB MIDI device
- Create multiple MIDI ports (one per connected device)
- Bridge: gadget port ↔ routing engine ↔ hardware port

### 5. Mode Detection
```python
def detect_mode():
    """Check if USB-C is connected to a host"""
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
    ports: 1
  "1c75:0288":
    name: "KeyStep"
    type: controller_sequencer
    ports: 1
  "1397:00d2":
    name: "Behringer Model D"
    type: synth
    ports: 1
  "0582:0191":
    name: "Roland JP-08"
    type: synth
    ports: 1
  "1c75:0207":
    name: "MicroBrute"
    type: synth
    ports: 1
  "0582:01e5":
    name: "SP-404 MK2"
    type: sampler
    ports: 1

hardware_ports:
  ttySC0:
    name: "MS-20 Mini"
    direction: out
  ttySC1:
    name: "Volca 1"
    direction: out
  ttySC2:
    name: "Volca 2"
    direction: out
  ttySC3:
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
      "filter": { "channel": 1 }
    },
    {
      "from": "KeyLab 88 MK2",
      "to": "Behringer Model D",
      "filter": { "channel": 2 }
    },
    {
      "from": "KeyLab 88 MK2",
      "to": "Roland JP-08",
      "filter": { "channel": 3 }
    },
    {
      "from": "KeyStep",
      "to": "Volca 1",
      "filter": { "channel": 4 }
    },
    {
      "from": "KeyStep",
      "to": "Volca 2",
      "filter": { "channel": 5 }
    },
    {
      "from": "KeyStep",
      "to": "Volca 3",
      "filter": { "channel": 6 }
    },
    {
      "from": "SP-404 MK2",
      "to": "MicroBrute",
      "filter": { "channel": 10 }
    }
  ],
  "clock_source": "KeyStep"
}
```

## Dependencies

```
# Python packages
mido>=1.3.0          # MIDI message handling
python-rtmidi>=1.5.0 # ALSA MIDI backend
pyserial>=3.5        # Hardware UART (SC16IS752)
flask>=3.0           # Web UI
pyyaml>=6.0          # Configuration files
luma.oled>=3.13      # OLED display driver
RPi.GPIO>=0.7        # GPIO access (encoder, LEDs)
smbus2>=0.4          # I2C access (if needed directly)
```

## Systemd Services

### midi-box.service (main application)
```ini
[Unit]
Description=MIDI Box Router
After=network.target sound.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/midi-box
ExecStartPre=/opt/midi-box/config/gadget_config.sh
ExecStart=/usr/bin/python3 /opt/midi-box/src/main.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

### midi-box-web.service (web UI)
```ini
[Unit]
Description=MIDI Box Web Interface
After=midi-box.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/midi-box
ExecStart=/usr/bin/python3 /opt/midi-box/src/ui_web.py
Restart=always

[Install]
WantedBy=multi-user.target
```

## Latency Targets

| Path | Target | Notes |
|---|---|---|
| USB → USB | < 2ms | ALSA handles this well |
| USB → 5-Pin | < 3ms | SC16IS752 adds ~1ms |
| 5-Pin → USB | < 3ms | Same |
| USB → Mac (gadget) | < 3ms | Gadget mode overhead |
| End-to-end (key press → sound) | < 5ms | Imperceptible |
