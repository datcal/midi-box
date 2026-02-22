# MIDI Box

A DIY MIDI router and patchbay built on a Raspberry Pi 4. It connects all your synths, samplers, and sequencers — USB and DIN — and lets you control the routing from your phone or laptop via a web UI. You can also plug it into your Mac and Logic Pro sees every device as its own named MIDI port.

The whole thing runs headless in a box. A 5" touchscreen on the front shows a QR code to connect and a live routing overview.

---

## What it does

- **Routes MIDI** between up to 10 devices (6 USB + 4 five-pin DIN) with any-to-any routing
- **Web UI** — control routing, manage presets, monitor MIDI traffic, all from a browser
- **DAW mode** — plug into a Mac via USB-C and Logic Pro sees each synth as a named port
- **Standalone mode** — Pi handles everything internally, no Mac needed
- **Presets** — save and recall full routing configurations instantly
- **Clip launcher** — Ableton-style session view for triggering MIDI clips, quantized to the beat
- **MIDI file player** — play .mid files to any destination with tempo/loop control
- **MIDI monitor** — live scrolling view of all MIDI messages across all ports
- **Hotplug** — devices coming and going are detected automatically
- **WiFi hotspot** — Pi broadcasts its own network, no router needed

---

## Hardware

| # | Device | Type | Connection |
|---|--------|------|------------|
| 1 | Arturia KeyLab 88 MK2 | Controller | USB |
| 2 | Arturia KeyStep | Sequencer | USB |
| 3 | Behringer Model D | Mono synth | USB |
| 4 | Roland JP-08 | Polysynth | USB |
| 5 | Arturia MicroBrute | Mono synth | USB |
| 6 | Roland SP-404 MK2 | Sampler | USB |
| 7 | Korg MS-20 Mini | Mono synth | 5-Pin DIN |
| 8 | Korg Volca #1 | Synth | 5-Pin DIN |
| 9 | Korg Volca #2 | Synth | 5-Pin DIN |
| 10 | Korg Volca #3 | Synth | 5-Pin DIN |

**Pi hardware:**
- Raspberry Pi 4 (4GB)
- 5" DSI touchscreen (kiosk UI)
- 2× Waveshare powered USB hubs
- Custom MIDI I/O board (Pi native UARTs → 5-Pin DIN OUT)
- 5V 5A power supply (powers everything)

See [hardware/bom.md](hardware/bom.md) for the full bill of materials and [hardware/schematics/](hardware/schematics/) for circuit diagrams.

---

## How it's built

Two processes communicate over IPC:

```
Process 1 — MIDI Engine (src/main.py)
  Owns all hardware: USB MIDI via ALSA/rtmidi, Pi UARTs for DIN OUT, USB gadget
  Core routing loop: poll inputs → apply filters → send to outputs
  Handles commands from Flask via a shared queue

Process 2 — Web UI (src/ui_web.py)
  Flask app serving the browser UI and REST API
  Reads engine state every 200ms, sends commands via queue
  Never touches MIDI objects directly
```

The engine runs at ~1ms polling. The web UI refreshes at ~5Hz. They stay decoupled so a slow browser request never touches the MIDI loop.

Full architecture notes in [docs/software-arch.md](docs/software-arch.md).

---

## Running on a Mac (dev mode)

No hardware needed — runs with mock MIDI ports.

```bash
cd software
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 src/main.py --mode standalone --platform mac --mock -v
```

Open [http://localhost:8080](http://localhost:8080).

Useful flags:
```
--list-devices     show detected MIDI ports
--list-presets     show saved presets
--preset NAME      load a preset on startup
--port PORT        change web UI port (default 8080)
```

---

## Deploying to a Raspberry Pi

Clone the repo onto the Pi and run the setup script once:

```bash
git clone https://github.com/datcal/midi-box ~/midi-box
cd ~/midi-box
sudo bash scripts/pi_setup.sh
```

This installs dependencies, sets up the systemd service, configures the WiFi hotspot, and adds the UART overlays for hardware MIDI. Reboot when it's done.

After reboot:
- WiFi network **MIDI-BOX** appears (password: `midibox123` — change it in Settings)
- Web UI at `http://192.168.4.1:8080`
- QR code on the touchscreen takes you straight there

The service starts on boot and restarts automatically if it crashes.

**Mac + Pi hybrid (DAW mode):**
Connect the Pi to your Mac via USB-C. The Pi's USB gadget presents each synth as a named MIDI port in Logic Pro. Change modes via the web UI or restart with `--mode daw`.

Software updates can be triggered from Settings → Software Update without SSHing in.

---

## Routing

Routes are point-to-point with optional per-route filters:

```json
{
  "from": "KeyLab 88 MK2",
  "to": "MS-20 Mini",
  "filter": {
    "channels": [1, 2],
    "message_types": ["note", "pitchwheel"],
    "velocity_min": 20,
    "remap_channel": 3
  }
}
```

Filter options: `channels`, `remap_channel`, `message_types` (`note`, `cc`, `program_change`, `pitchwheel`, `aftertouch`, `clock`, `sysex`), `velocity_min/max`, `cc_numbers`, `block_clock`, `block_sysex`.

Save any routing setup as a named preset and recall it instantly.

---

## Project layout

```
midi-box/
├── software/
│   ├── src/              Python source (14 modules)
│   ├── config/           App settings, device registry
│   ├── presets/          Saved routing presets (JSON)
│   └── web_ui/           Flask templates + vanilla JS/CSS
├── hardware/
│   ├── bom.md            Bill of materials
│   └── schematics/       MIDI I/O board circuit
├── docs/
│   ├── software-arch.md  Architecture decisions and latency notes
│   ├── gear-inventory.md MIDI specs for all 10 devices
│   └── build-phases.md   Build log
└── scripts/
    ├── pi_setup.sh       One-command Pi installer
    └── update.sh         OTA update helper (used by web UI)
```

---

## License

MIT — see [LICENSE](LICENSE).
