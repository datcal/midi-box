# Bill of Materials

## Core Components

| Component | Qty | Purpose | Notes |
|-----------|-----|---------|-------|
| Raspberry Pi 4 Model B (2GB+) | 1 | Main processor / router brain | 4GB recommended for web UI |
| MicroSD Card 16GB+ | 1 | OS + software storage | Class 10 / A1 minimum |
| Waveshare Industrial USB HUB (4× USB 2.0) | 2 | Connect 6 USB MIDI devices (3 per hub) | 5V powered, industrial grade, compact |
| 5V 5A Power Supply (barrel jack) | 1 | Single power input for whole box | 5V directly powers Pi (GPIO pins) + both hubs — no buck converter needed |
| USB-C to USB-A cable | 1 | Connect Pi USB-C to Mac | For DAW mode (gadget mode) — USB-C port dedicated to this |

## Display

| Component | Qty | Purpose | Notes |
|-----------|-----|---------|-------|
| 5" DSI Touchscreen 800×480 IPS Capacitive | 1 | Local UI — QR code, routing, launcher | Third-party DSI screen (800×480, 5-point touch). DSI ribbon to Pi. Most work plug-and-play on Pi OS Bookworm; some need a manufacturer-specific dtoverlay — check product wiki. |

## MIDI DIN I/O Components

4× MIDI OUT ports only (MS-20 Mini + 3× Volca). All driven by Pi native hardware UARTs — no external UART bridge chips needed.

| Component | Qty | Purpose | Notes |
|-----------|-----|---------|-------|
| 5-Pin DIN Female Connector (PCB mount) | 4 | MIDI OUT ports | One per device (MS-20, Volca ×3) |
| 220 ohm Resistor (1/4W) | 8 | MIDI OUT current drive | 2 per port (active-drive circuit) |

## User Interface Components

| Component | Qty | Purpose | Notes |
|-----------|-----|---------|-------|
| LED (green, 3mm) | 10 | MIDI activity indicators | One per port |
| LED (blue, 3mm) | 2 | Mode indicator (Standalone/DAW) | |
| 330 ohm Resistor (1/4W) | 12 | LED current limiting | |
| SPDT Toggle Switch | 1 | Manual mode override | Panel mount |

## Enclosure & Assembly

| Component | Qty | Purpose | Notes |
|-----------|-----|---------|-------|
| 3D Printed Enclosure | 1 | Housing | PLA or PETG, custom design |
| M3 Brass Heat-Set Inserts | 12 | Secure panels to enclosure | Press-in with soldering iron |
| M3x8mm Screws | 12 | Panel mounting | |
| M2.5 Standoffs (11mm) | 4 | Mount Pi inside enclosure | |
| M2.5 Screws | 8 | Secure Pi to standoffs | |
| Rubber Feet (adhesive) | 4 | Non-slip base | |

## Cables (Internal)

| Component | Qty | Purpose | Notes |
|-----------|-----|---------|-------|
| Dupont Jumper Wires (F-F) | 20 | GPIO connections | 20cm |
| USB-A to USB-A cables | 6 | Connect USB MIDI devices to hubs | Short 30cm cables to save space |
| DSI Ribbon Cable | 1 | Pi → 5" touchscreen | Usually included with screen; verify before ordering |

## Port Allocation Plan

### Pi Native UARTs (MIDI OUT — enabled via device tree overlays)

| UART | GPIO (TX) | Device Node | Assigned To |
|------|-----------|-------------|-------------|
| UART0 | GPIO 14 | /dev/ttyAMA0 | Korg MS-20 Mini |
| UART3 | GPIO 4 | /dev/ttyAMA2 | Korg Volca #1 |
| UART4 | GPIO 8 | /dev/ttyAMA3 | Korg Volca #2 |
| UART5 | GPIO 12 | /dev/ttyAMA4 | Korg Volca #3 |

Required in `/boot/firmware/config.txt`:
```
dtoverlay=disable-bt    # frees UART0 (GPIO 14) from Bluetooth
dtoverlay=uart3         # enables UART3 on GPIO 4/5
dtoverlay=uart4         # enables UART4 on GPIO 8/9
dtoverlay=uart5         # enables UART5 on GPIO 12/13
```

### I2C Bus (GPIO 2/3)

| Device | Address | Purpose |
|--------|---------|---------|
| 5" Touchscreen (touch controller) | 0x38 | Touch input (auto via DSI) |

### Reserved GPIO (other)

| GPIO | Purpose |
|------|---------|
| 2 / 3 | I2C SDA / SCL |
| 4 | UART3 TX → Volca #1 |
| 8 | UART4 TX → Volca #2 |
| 12 | UART5 TX → Volca #3 |
| 14 | UART0 TX → MS-20 Mini |

## Power Budget

Single **5V 5A barrel jack** powers everything directly — no buck converter. Pi is powered via GPIO 5V pins (USB-C port kept free for DAW mode / Mac connection).

```
[5V 5A barrel jack]
        │
        ├──→ Raspberry Pi 4 (GPIO 5V pins — USB-C kept free for DAW mode)
        ├──→ Waveshare USB Hub #1 (5V input, 3 MIDI devices)
        └──→ Waveshare USB Hub #2 (5V input, 3 MIDI devices)
```

### 5V Draw

| Component | Current draw | Notes |
|---|---|---|
| Pi 4 + 5" touchscreen | ~2.0A | Pi ~1.7A + screen ~0.3A |
| Waveshare Hub #1 (3 USB MIDI devices) | ~0.6A | MIDI devices ~150–200mA each |
| Waveshare Hub #2 (3 USB MIDI devices) | ~0.6A | MIDI devices ~150–200mA each |
| LEDs ×12 | ~0.12A | 10mA each |
| **Realistic total** | **~3.3A** | |
| **Supply capacity** | **5.0A** | ~1.7A headroom |

> The Waveshare hubs draw their own power from the 5V rail. No charging ports, no idle load — purely USB MIDI instrument connections.
