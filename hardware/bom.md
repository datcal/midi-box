# Bill of Materials

## Core Components

| Component | Qty | Purpose | Notes |
|-----------|-----|---------|-------|
| Raspberry Pi 4 Model B (2GB+) | 1 | Main processor / router brain | 4GB recommended for web UI |
| MicroSD Card 16GB+ | 1 | OS + software storage | Class 10 / A1 minimum |
| Powered USB Hub (7-port) | 1 | Connect USB MIDI devices | **Must be powered**, not bus-powered |
| 5V 4A Power Supply | 1 | Power the Pi + MIDI board | Powers Pi via GPIO, not USB-C |
| USB-C to USB-A cable | 1 | Connect Pi USB-C to Mac | For DAW mode (gadget mode) |

## MIDI I/O Board Components

| Component | Qty | Purpose | Notes |
|-----------|-----|---------|-------|
| SC16IS752 I2C/SPI-to-UART | 2 | Adds 4 hardware UARTs total | 2 channels each, I2C address configurable |
| 6N138 Optocoupler | 6 | MIDI IN galvanic isolation | Standard MIDI spec requirement |
| 5-Pin DIN Female Connector (PCB mount) | 12 | 6x MIDI IN + 6x MIDI OUT | Panel mount recommended |
| 220 ohm Resistor (1/4W) | 18 | MIDI circuit current limiting | 6 for IN, 12 for OUT |
| 1N4148 Diode | 6 | MIDI IN protection | Across optocoupler input |
| 10K ohm Resistor (1/4W) | 6 | Optocoupler pull-up | For 6N138 output |
| 100nF Ceramic Capacitor | 6 | Decoupling for optocouplers | One per MIDI IN circuit |
| Perfboard (9x15cm) | 1 | Mount MIDI circuits | Or custom PCB |
| Pin Headers (male/female) | 1 set | Connect to Pi GPIO | 2.54mm pitch |
| Hookup Wire (22AWG) | 1 roll | Internal wiring | Solid core for perfboard |

## User Interface Components

| Component | Qty | Purpose | Notes |
|-----------|-----|---------|-------|
| SSD1306 OLED Display 128x64 | 1 | Show routing info / menus | I2C, 0.96" or 1.3" |
| Rotary Encoder with Push Button | 1 | Navigate menus / select presets | KY-040 module or bare encoder |
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
| USB-A to USB-B/Micro cables | 6 | Connect USB MIDI devices | Short 30cm cables to save space |

## Port Allocation Plan

### SC16IS752 #1 (I2C Address 0x48)
| UART Channel | Direction | Assigned To |
|---|---|---|
| Channel A | OUT | Korg MS-20 Mini |
| Channel B | OUT | Korg Volca #1 |

### SC16IS752 #2 (I2C Address 0x49)
| UART Channel | Direction | Assigned To |
|---|---|---|
| Channel A | OUT | Korg Volca #2 |
| Channel B | OUT | Korg Volca #3 |

### Pi Native UART (GPIO 14/15)
| UART | Direction | Assigned To |
|---|---|---|
| UART0 | IN/OUT | Spare Port 1 |

### Extra UART (via additional SC16IS752 or software serial)
| UART | Direction | Assigned To |
|---|---|---|
| Spare | IN/OUT | Spare Port 2 |

## Power Budget

| Component | Current Draw |
|---|---|
| Raspberry Pi 4 | ~1.0A (idle) - 1.5A (load) |
| Powered USB Hub | Self-powered (separate PSU) |
| SC16IS752 x2 | ~10mA |
| OLED Display | ~20mA |
| LEDs x12 | ~120mA (10mA each) |
| 6N138 x6 | ~30mA |
| **Total** | **~1.7A typical** |

Recommendation: 5V 4A supply gives plenty of headroom.
