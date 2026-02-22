# MIDI Box - DIY MIDI Router & Interface

A custom-built MIDI router/patchbay that connects all studio gear and works both standalone and as a multi-port USB MIDI interface for Logic Pro on macOS. Controlled entirely via web UI.

## Project Overview

**Goal:** Build a MIDI router that can route MIDI signals between any connected device, with two operating modes:

- **Standalone Mode** — Routing handled internally on Pi, controlled via web UI on phone/laptop.
- **DAW Mode** — Connect to Mac via USB-C. Logic Pro sees every synth as a named MIDI port.
- **Dev Mode** — Run directly on Mac for testing USB MIDI devices before deploying to Pi.

## Connected Gear

| # | Device | USB MIDI | 5-Pin IN | 5-Pin OUT | Connection |
|---|--------|----------|----------|-----------|------------|
| 1 | Arturia KeyLab 88 MK2 | Yes | - | Yes | USB |
| 2 | Arturia KeyStep | Yes | Yes | Yes | USB |
| 3 | Korg MS-20 Mini | No | Yes | - | 5-Pin DIN |
| 4 | Behringer Model D | Yes | Yes | - | USB |
| 5 | Roland JP-08 | Yes | Yes | Yes* | USB |
| 6 | Arturia MicroBrute | Yes | Yes | - | USB |
| 7 | Korg Volca #1 | No | Yes | Yes* | 5-Pin DIN |
| 8 | Korg Volca #2 | No | Yes | Yes* | 5-Pin DIN |
| 9 | Korg Volca #3 | No | Yes | Yes* | 5-Pin DIN |
| 10 | Roland SP-404 MK2 | Yes | Yes | Yes | USB |

*\* Limited MIDI out / sync out*

## System Architecture

```
  ┌─────────────────────────────────────────────────────────────────┐
  │                     MIDI BOX (Pi or Mac)                        │
  │                                                                 │
  │  ┌──────────────┐   ┌─────────────┐   ┌─────────────────────┐ │
  │  │ Python App   │───│ USB Hub     │───│ USB MIDI Devices    │ │
  │  │              │   │ (powered)   │   │ KeyLab, KeyStep,    │ │
  │  │ Router       │   └─────────────┘   │ Model D, JP-08,     │ │
  │  │ Web UI       │                     │ MicroBrute, SP-404  │ │
  │  │ Preset Mgr   │   ┌─────────────┐  └─────────────────────┘ │
  │  │ MIDI Logger  │───│ MIDI I/O    │───│ MS-20, Volca x3    │ │
  │  │              │   │ (Pi only)   │   │ (5-Pin DIN)        │ │
  │  └──────┬───────┘   └─────────────┘  └─────────────────────┘ │
  │         │                                                      │
  │         │ :8080                                                │
  └─────────┼──────────────────────────────────────────────────────┘
            │
     ┌──────┴──────┐
     │   Web UI    │  ← Phone / Laptop / Any browser
     │             │
     │ Routing     │
     │ Presets     │
     │ MIDI Log    │
     │ Settings    │
     └─────────────┘
```

## Project Structure

```
midi-box/
├── README.md
├── docs/
│   ├── gear-inventory.md      ← Full gear specs & MIDI capabilities
│   ├── build-phases.md        ← Step-by-step build guide
│   └── software-arch.md       ← Software architecture & design
├── hardware/
│   ├── schematics/            ← Circuit schematics (MIDI I/O board)
│   ├── pcb/                   ← PCB design files
│   ├── datasheets/            ← Component datasheets
│   └── bom.md                 ← Bill of materials
├── software/
│   ├── src/                   ← Python source code
│   ├── config/                ← Configuration files
│   ├── presets/               ← MIDI routing presets (JSON)
│   └── web_ui/
│       ├── templates/         ← HTML templates
│       └── static/            ← CSS, JS
├── firmware/                  ← USB gadget setup scripts (Pi only)
└── design/
    ├── enclosure/             ← 3D printable STL/STEP files
    ├── panels/                ← Front/rear panel designs
    └── renders/
```

## Quick Start (Mac)

```bash
cd software
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 src/main.py --mode standalone -v
# Open http://localhost:8080
```

## Tech Stack

- **Software:** Python 3, mido, rtmidi, Flask, pyserial, psutil
- **Hardware (Pi):** Raspberry Pi 4, Pi native UARTs (MIDI OUT), 5" DSI touchscreen (kiosk)
- **Platforms:** macOS (dev/testing with `--mock`), Raspberry Pi OS (production)
- **DAW:** Logic Pro on macOS
