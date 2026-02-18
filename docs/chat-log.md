# MIDI Box - Development Chat Log

## Session: 2026-02-18

### Project Goal
Build a DIY MIDI router/patchbay that connects all studio gear. Works standalone (Pi) and with Mac/Logic Pro. Controlled via web UI.

### Gear
1. Arturia KeyLab 88 MK2 (USB MIDI)
2. Arturia KeyStep (USB MIDI)
3. Korg MS-20 Mini (5-pin DIN only)
4. Behringer Model D (USB MIDI)
5. Roland JP-08 (USB MIDI)
6. Arturia MicroBrute (USB MIDI)
7. 3x Korg Volca (5-pin DIN only)
8. Roland SP-404 MK2 (USB MIDI)

### Builder Skills
- 3D printer, soldering, basic circuit design
- Arduino and Raspberry Pi experience
- Uses Mac + Logic Pro for production

### Architecture Decisions Made
- **Raspberry Pi 4** as the brain
- **Powered 7-port USB hub** for 6 USB MIDI devices
- **SC16IS752** I2C-to-UART bridge (x2) for 5-pin DIN ports (MS-20 + 3 Volcas)
- **USB gadget mode** (dwc2) so Pi appears as a multi-port MIDI device to Mac
- **Web UI only** (removed OLED, rotary encoder, mode switch)
- **Cross-platform** — runs on Mac for testing, Pi for production
- **Persistent state** — saves routes/presets to `software/data/state.json`
- **Power from Mac** via USB-C is OK since USB hub is self-powered

### What Was Built

#### Documentation
- `README.md` — Master plan, architecture diagram, quick start
- `docs/build-phases.md` — 5-phase build guide (was 7, removed OLED/encoder phases)
- `docs/gear-inventory.md` — All 10 devices with MIDI specs and channel assignments
- `docs/software-arch.md` — Software design, config formats, dependencies
- `hardware/bom.md` — Full bill of materials
- `hardware/schematics/midi-circuits.md` — MIDI IN/OUT circuits, SC16IS752 wiring

#### Software (Python)
- `software/src/main.py` — Entry point, cross-platform (Mac/Pi), mode detection
- `software/src/router.py` — Core routing engine (any-to-any, filters, merging)
- `software/src/alsa_midi.py` — USB MIDI via ALSA/rtmidi, hotplug detection
- `software/src/hw_midi.py` — Hardware 5-pin DIN MIDI via SC16IS752 serial (Pi only)
- `software/src/gadget.py` — USB gadget mode for Logic Pro (Pi only)
- `software/src/midi_filter.py` — Channel filter, remap, message type filter
- `software/src/device_registry.py` — Maps USB IDs to friendly device names
- `software/src/preset_manager.py` — Load/save/switch JSON presets
- `software/src/state.py` — Persistent state manager (auto-saves, export/import)
- `software/src/midi_logger.py` — MIDI message capture ring buffer
- `software/src/ui_web.py` — Flask backend (REST API + pages)

#### Web UI
- `software/web_ui/templates/index.html` — Single-page app (6 views)
- `software/web_ui/static/style.css` — Dark theme
- `software/web_ui/static/app.js` — Frontend logic

Web UI pages:
1. **Dashboard** — Device list, activity dots, stats
2. **Routing** — Click-to-route matrix, filter editor (right-click), route list
3. **Presets** — Load/save/delete (default, live_keys, sequencer, recording, sp404_live, all_through)
4. **MIDI Monitor** — Live message stream with type/channel/raw hex
5. **Settings** — Platform info, clock source, export/import, reset
6. **Logs** — Application log stream

#### Configuration
- `software/config/devices.yaml` — USB device ID mapping + hardware port config
- `software/config/midi_box.yaml` — System settings
- `software/config/gadget_config.sh` — USB gadget setup (Pi boot)
- `software/presets/*.json` — 6 routing presets

### Bugs Fixed
1. **404 on web UI** — `Path(__file__)` was relative, added `.resolve()` to `ui_web.py`, `device_registry.py`, `preset_manager.py`
2. **Port 8080 in use** — Found and killed lingering process with `lsof -ti:8080`
3. **Git push failed (HTTP 400)** — `venv/` directory (1400+ files, 6 MB) was committed. Fixed by adding `.gitignore`, squashing history, force-pushing clean commit.

### What's Next (TODO)
- [ ] **Phase 1 testing** — Plug in USB MIDI devices on Mac, test routing via web UI
- [ ] **Phase 2** — Set up USB gadget mode on Pi, test with Logic Pro
- [ ] **Phase 3** — Build SC16IS752 MIDI I/O board for MS-20 + Volcas
- [ ] **Phase 4** — 3D print enclosure
- [ ] **Enhancements** — WebSocket for real-time monitor (currently polls), MIDI learn, virtual MIDI ports on Mac

### How to Run

**On Mac (testing):**
```bash
cd ~/project/midi-box/software
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 src/main.py --platform mac -v
# Open http://localhost:8080
```

**On Raspberry Pi (production):**
```bash
# Flash Raspberry Pi OS Lite, SSH in
sudo apt install -y python3-pip python3-venv git
git clone https://github.com/datcal/midi-box.git
cd midi-box/software
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# Also install Pi-specific deps:
pip install RPi.GPIO smbus2
python3 src/main.py -v
```

### Useful Commands
```bash
# List MIDI devices
python3 src/main.py --list-devices

# List presets
python3 src/main.py --list-presets

# Run with specific preset
python3 src/main.py --preset sequencer -v

# Kill stuck process on port 8080
kill $(lsof -ti:8080)
```

### GitHub Repo
https://github.com/datcal/midi-box
