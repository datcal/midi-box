# Build Phases Guide

## Phase 1 — Proof of Concept: USB MIDI Routing on Pi

**Goal:** Get the Pi routing MIDI between USB devices.

**What you need:**
- Raspberry Pi 4 with Raspberry Pi OS Lite installed
- Powered 7-port USB hub
- 2-3 USB MIDI devices to test with (e.g., KeyLab + Model D)

**Steps:**

1. Flash Raspberry Pi OS Lite (Bookworm) to MicroSD
2. Boot and configure:
   ```bash
   sudo apt update && sudo apt upgrade -y
   sudo apt install -y python3-pip python3-venv git alsa-utils
   ```
3. Connect USB hub and plug in a couple MIDI devices
4. Verify devices are seen:
   ```bash
   aconnect -l          # List ALSA MIDI ports
   amidi -l             # List raw MIDI ports
   ```
5. Test basic routing with aconnect:
   ```bash
   # Connect KeyLab output to Model D input
   aconnect 20:0 24:0
   ```
6. Play notes on KeyLab — Model D should respond
7. Install Python environment:
   ```bash
   python3 -m venv /opt/midi-box/venv
   source /opt/midi-box/venv/bin/activate
   pip install mido python-rtmidi
   ```
8. Write a basic Python routing script and test

**Success criteria:** Play KeyLab, hear Model D. Route KeyStep to JP-08. Any USB device to any USB device.

**Estimated time:** 1-2 hours

---

## Phase 2 — USB Gadget Mode: Pi as MIDI Interface for Mac

**Goal:** Mac/Logic Pro sees the Pi as a multi-port MIDI device over USB-C.

**What you need:**
- USB-C cable connecting Pi to Mac

**Power options (choose one):**

- **Option A (try first):** Power from Mac via the same USB-C cable. Works if your USB hub
  is self-powered (has its own wall adapter), since the Pi only draws ~600-800mA by itself.
  If you see a lightning bolt icon or instability, switch to Option B.
- **Option B (most reliable):** Feed 5V to Pi GPIO header pins 2(+) and 6(GND) from a
  separate 5V 3A regulated power supply. No fuse on GPIO — use regulated supply only.

**Steps:**

1. Enable dwc2 overlay:
   ```bash
   # Add to /boot/firmware/config.txt
   dtoverlay=dwc2

   # Add to /etc/modules
   dwc2
   libcomposite
   ```
2. Create the USB gadget setup script:
   ```bash
   #!/bin/bash
   # /opt/midi-box/config/gadget_config.sh

   GADGET_DIR=/sys/kernel/config/usb_gadget/midi-box

   mkdir -p $GADGET_DIR
   cd $GADGET_DIR

   # Device descriptor
   echo 0x1d6b > idVendor   # Linux Foundation
   echo 0x0104 > idProduct  # Multifunction Composite Gadget
   echo 0x0100 > bcdDevice
   echo 0x0200 > bcdUSB

   mkdir -p strings/0x409
   echo "MIDIBox" > strings/0x409/manufacturer
   echo "MIDI Box Router" > strings/0x409/product
   echo "000001" > strings/0x409/serialnumber

   # MIDI function
   mkdir -p functions/midi.usb0
   echo 10 > functions/midi.usb0/in_ports   # 10 ports TO host (Mac)
   echo 10 > functions/midi.usb0/out_ports  # 10 ports FROM host (Mac)

   # Configuration
   mkdir -p configs/c.1/strings/0x409
   echo "MIDI Config" > configs/c.1/strings/0x409/configuration
   echo 500 > configs/c.1/MaxPower

   ln -s functions/midi.usb0 configs/c.1/

   # Enable
   UDC=$(ls /sys/class/udc | head -1)
   echo $UDC > UDC
   ```
3. Run the script and connect Pi to Mac:
   ```bash
   sudo bash /opt/midi-box/config/gadget_config.sh
   ```
4. On Mac, open Audio MIDI Setup → MIDI Studio
5. You should see "MIDI Box Router" with 10 IN + 10 OUT ports
6. Test in Logic Pro: create a track, select MIDI Box port, verify signal flow

**Important:** Power the Pi via GPIO 5V+GND pins (pins 2+6) using a separate 5V supply. The USB-C port is occupied by the Mac connection.

**Success criteria:** Logic Pro shows 10 MIDI Box ports. Sending MIDI from Logic reaches the Pi.

**Estimated time:** 2-3 hours

---

## Phase 3 — Custom 5-Pin MIDI I/O Board

**Goal:** Build the hardware MIDI board for MS-20 and Volcas.

**What you need:**
- All components from the BOM (SC16IS752, 6N138, DIN connectors, etc.)
- Soldering station, perfboard, wire

**Steps:**

1. Enable SC16IS752 in Pi device tree:
   ```bash
   # Add to /boot/firmware/config.txt
   dtoverlay=sc16is752-i2c,int_pin=24,addr=0x48
   dtoverlay=sc16is752-i2c,int_pin=25,addr=0x49
   ```
2. Verify I2C devices detected:
   ```bash
   sudo i2cdetect -y 1
   # Should show 0x48 and 0x49
   ```
3. Build MIDI OUT circuits first (simpler, no optocoupler):
   - Wire SC16IS752 TX → 220ohm → DIN pin 5
   - Wire +5V → 220ohm → DIN pin 4
4. Test MIDI OUT:
   ```python
   import serial
   ser = serial.Serial('/dev/ttySC0', 31250)
   ser.write(bytes([0x90, 60, 100]))  # Note On, middle C, velocity 100
   ser.write(bytes([0x80, 60, 0]))    # Note Off
   ```
5. Connect to MS-20 Mini and verify it plays
6. Build remaining MIDI OUT ports for Volcas
7. Build MIDI IN circuits (with 6N138 optocouplers) for spare ports
8. Test all ports

**Build order:**
1. Solder SC16IS752 chips and crystal/caps
2. Wire I2C connections to Pi header
3. Build one MIDI OUT circuit, test it
4. Replicate for remaining OUT ports
5. Build MIDI IN circuits for spare ports

**Success criteria:** Send MIDI note from Pi → MS-20 plays. Same for each Volca.

**Estimated time:** 4-6 hours (soldering + testing)

---

## Phase 4 — Routing Engine with Dual Mode

**Goal:** Unified software that handles USB + hardware + gadget routing.

**Steps:**

1. Implement `device_registry.py` — maps USB IDs and serial ports to device names
2. Implement `alsa_midi.py` — enumerate and open USB MIDI ports
3. Implement `hw_midi.py` — open SC16IS752 serial ports at 31250 baud
4. Implement `router.py` — the core routing table
   - Read from all input ports (threaded)
   - Look up route in routing table
   - Forward to destination port(s)
   - Apply filters (channel, message type)
5. Implement `gadget.py` — bridge ALSA gadget ports to routing engine
6. Implement `preset_manager.py` — load JSON presets into routing table
7. Implement `main.py` — detect mode, initialize everything, start routing
8. Test scenarios:
   - Standalone: KeyLab → Model D (USB to USB)
   - Standalone: KeyStep → Volca (USB to 5-pin)
   - DAW mode: Logic → JP-08 (gadget to USB)
   - DAW mode: Logic → MS-20 (gadget to 5-pin)
   - Merge: KeyLab + KeyStep → Model D

**Success criteria:** All routing scenarios work. Preset switching works. Mode detection works.

**Estimated time:** 6-10 hours (coding + testing)

---

## Phase 5 — OLED/Encoder UI + Mode Switching

**Goal:** Standalone control without needing a computer or phone.

**Steps:**

1. Wire OLED (I2C) and rotary encoder (GPIO) to Pi
2. Implement `ui_oled.py`:
   - Boot screen with MIDI Box logo
   - Main screen: current preset name + activity dots
   - Menu: preset list, scroll with encoder, select with push
   - Status: show connected devices, active routes
3. Implement mode indicator LEDs
4. Test: change presets from encoder, see routing change in real-time

**UI Flow:**
```
Boot → [MIDI Box v1.0] → Main Screen
                              │
                         Push encoder
                              │
                         ┌────┴────┐
                         │  Menu   │
                         │         │
                         │ > Presets│ → scroll through presets → push to load
                         │   Devices│ → show connected devices
                         │   Status │ → show active routes + MIDI activity
                         │   Mode   │ → Standalone / DAW toggle
                         │   Info   │ → IP address, version
                         └─────────┘
```

**Estimated time:** 3-4 hours

---

## Phase 6 — 3D Printed Enclosure

**Goal:** Professional-looking box that holds everything.

**Design considerations:**
- Front panel: OLED window, rotary encoder hole, mode switch, activity LEDs
- Rear panel: 12x DIN connector holes (6 IN + 6 OUT), USB hub ports, USB-C (to Mac), power jack
- Internal: Pi mounting posts, MIDI board mounting, USB hub mounting
- Ventilation: slots or holes for airflow
- Size estimate: approximately 250mm x 180mm x 60mm

**Steps:**
1. Measure all components (Pi, USB hub, MIDI board, DIN connectors)
2. Design in Fusion 360, FreeCAD, or TinkerCAD
3. Print test fit pieces first (just corners and connector cutouts)
4. Print full enclosure
5. Install brass heat-set inserts
6. Mount everything, route cables

**Tips:**
- Print DIN connector panel separately — easier to iterate
- Use panel-mount DIN connectors, not PCB-mount (more flexible)
- Label all ports on the enclosure (embossed or printed labels)
- Leave extra space — cables inside take more room than you think

**Estimated time:** 8-12 hours (design + printing + assembly)

---

## Phase 7 — Web UI, Presets & Polish

**Goal:** Easy configuration from any device on the network.

**Steps:**
1. Set up Pi as WiFi access point OR connect to home network
2. Implement Flask web UI:
   - Visual patch matrix (grid: inputs on Y axis, outputs on X axis)
   - Click to create/remove routes
   - Drag to set channel filtering
   - Preset save/load/rename
   - Device status page
3. Create useful default presets:
   - "Live Keys" — KeyLab controls all synths
   - "Sequencer" — KeyStep drives Volcas + MS-20
   - "Recording" — Everything to Logic
   - "SP-404 Live" — SP-404 centered setup
   - "All Through" — Everything connected to everything
4. Final testing and polish
5. Write usage notes for yourself

**Estimated time:** 4-6 hours

---

## Total Estimated Build Time

| Phase | Time |
|-------|------|
| Phase 1: USB MIDI PoC | 1-2 hours |
| Phase 2: USB Gadget | 2-3 hours |
| Phase 3: Hardware MIDI Board | 4-6 hours |
| Phase 4: Routing Engine | 6-10 hours |
| Phase 5: OLED/Encoder UI | 3-4 hours |
| Phase 6: Enclosure | 8-12 hours |
| Phase 7: Web UI & Polish | 4-6 hours |
| **Total** | **28-43 hours** |

Spread across weekends, this is a 3-5 weekend project.
