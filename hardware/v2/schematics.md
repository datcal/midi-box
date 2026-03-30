# MIDI Box v2 — Circuit Schematics

All circuits documented here as ASCII schematics for reference when drawing in KiCad. Organized by subsystem as hierarchical sheets.

---

## 1. CM4 Carrier Interface

The CM4 connects via two 100-pin Hirose DF40C connectors (J1, J2). Only the pins we actually use are listed below — leave others unconnected.

### Pinout (Signals We Use)

**Connector J1 (Primary):**

| Pin | Signal | Our Use |
|-----|--------|---------|
| 2, 6, 10, 14, 18, 22 | GND | Ground |
| 1, 3 | GND, VBAT | Not used (we don't need battery backup) |
| 4 | 5V_IN | **5V power to CM4** (from PD rail) |
| 5 | 5V_IN | **5V power to CM4** (parallel with pin 4) |
| 76 | GPIO 14 (UART0 TX) | **MIDI OUT → MS-20** |
| 80 | GPIO 4 (UART3 TX) | **MIDI OUT → Volca #1** |
| 82 | GPIO 8 (UART4 TX) | **MIDI OUT → Volca #2** |
| 84 | GPIO 12 (UART5 TX) | **MIDI OUT → Volca #3** |
| 87 | GPIO 0 (ID_SD) | EEPROM (leave floating or pull up) |
| 88 | GPIO 1 (ID_SC) | EEPROM (leave floating or pull up) |

**Connector J2 (Secondary):**

| Pin | Signal | Our Use |
|-----|--------|---------|
| 1–4 | USB D-, D+, D-, D+ | **USB 2.0 to hub IC (upstream)** |
| 5–8 | USB2 (secondary port) | **USB gadget (DAW mode)** → J4 USB-C |
| 30–45 | DSI signals | **DSI passthrough** → J17 FPC |
| 74 | SD_CLK | MicroSD |
| 76 | SD_CMD | MicroSD |
| 78–84 | SD_DAT0–3 | MicroSD |

### CM4 Decoupling

```
    5V_IN (pins 4,5) ──┬── C1 (100nF) ──┐
                        ├── C2 (100nF) ──┤
                        ├── C3 (100nF) ──┤── GND
                        ├── C4 (100nF) ──┤
                        └── C5 (10µF) ───┘
```

Place all decoupling caps within 5mm of the CM4 connector pins.

### CM4 Boot Configuration

```
    nRPIBOOT (J1 pin 91) ──── 10kΩ pull-up to 3.3V
                               │
                            [Jumper to GND]  ← close to force USB boot (eMMC programming)
                                               leave open for normal SD/eMMC boot
```

### EEPROM (Optional)

For CM4 carrier boards, a small I2C EEPROM (CAT24C32) on GPIO 0/1 can store board identity. This is optional — skip it for prototype.

---

## 2. USB Hub — USB2514B Cascade

Two USB2514B ICs provide 7 downstream ports. IC1 upstream connects to CM4 USB, IC1 port 4 cascades to IC2 upstream.

### Block Diagram

```
    CM4 USB Host (J2 pins 1-2)
         │
         ▼
    ┌──────────┐
    │ USB2514B │ (IC1 — Root Hub)
    │   (U2)   │
    ├──────────┤
    │ Port 1 ──┼──→ J9  (USB-A #1)
    │ Port 2 ──┼──→ J10 (USB-A #2)
    │ Port 3 ──┼──→ J11 (USB-A #3)
    │ Port 4 ──┼──→ [cascade to IC2 upstream]
    └──────────┘
         │ (Port 4)
         ▼
    ┌──────────┐
    │ USB2514B │ (IC2 — Tier 2 Hub)
    │   (U3)   │
    ├──────────┤
    │ Port 1 ──┼──→ J12 (USB-A #4)
    │ Port 2 ──┼──→ J13 (USB-A #5)
    │ Port 3 ──┼──→ J14 (USB-A #6)
    │ Port 4 ──┼──→ J15 (USB-A #7)
    └──────────┘
```

**Total: 7 downstream USB-A ports.** (6 for MIDI devices + 1 spare.) Add J16 as 8th port from CM4's second USB host if needed, or use USB2517 single-chip 7-port alternative.

### USB2514B Circuit (Per IC)

```
                          +3.3V
                            │
                     ┌──────┴──────┐
                     │  USB2514B   │
                     │             │
    USBUP_D- ───────┤ USBDM       │
    USBUP_D+ ───────┤ USBDP       │
                     │             │
                     │ DN1_DM ─────┤──→ Port 1 D-
                     │ DN1_DP ─────┤──→ Port 1 D+
                     │ DN2_DM ─────┤──→ Port 2 D-
                     │ DN2_DP ─────┤──→ Port 2 D+
                     │ DN3_DM ─────┤──→ Port 3 D-
                     │ DN3_DP ─────┤──→ Port 3 D+
                     │ DN4_DM ─────┤──→ Port 4 D-
                     │ DN4_DP ─────┤──→ Port 4 D+
                     │             │
                     │ XTAL1 ──────┤──── Y1 (24 MHz) ──┤
                     │ XTAL2 ──────┤────────────────────┤
                     │             │    C16 (18pF)  C17 (18pF)
                     │             │      │            │
                     │ VBUS_DET ───┤── 5V (via divider) │
                     │ RESET_N ────┤── 10kΩ to 3.3V    GND
                     │ CFG_SEL0 ───┤── GND (pin-strap config)
                     │ CFG_SEL1 ───┤── GND
                     └─────────────┘
                          │
                         GND

    Decoupling per IC:
    VDD33  ── C (100nF) ── GND    (×2, near VDD pins)
    VDDA33 ── C (100nF) ── GND
    CRFILT ── C (10nF)  ── GND    (internal PLL filter)
```

### USB2514B Configuration

Using pin-strap (non-SMBus) mode — CFG_SEL0/1 both tied to GND. Default config:
- All 4 ports enabled
- Self-powered mode
- Gang overcurrent reporting
- No need for EEPROM or SMBus

---

## 3. USB ESD Protection

One USBLC6-2SC6 per USB port, placed close to the connector.

```
    USB-A Connector                  To Hub IC
         │                               │
    D- ──┤──┬── USBLC6 ──┬──────────── D-
    D+ ──┤──┤   (ESD)    ├──────────── D+
         │  │             │
    VBUS ┤  └── GND ──── GND
    GND ─┤
         │
      [Polyfuse F1]── VBUS → hub VBUS_DET / power
```

---

## 4. MIDI OUT Circuits (×4)

Identical to v1 design. Pi UART TX → 220Ω active-drive → DIN-5 connector. No optocoupler on output side (only receiving devices have optocouplers).

### Single MIDI OUT Port

```
              +5V Rail
                │
              [R_src] 220Ω (e.g., R8)
                │
           DIN-5 Pin 4 (Source) ────────┐
                                        │
                                   [MIDI Cable]
                                   [to receiver]
                                   [optocoupler]
                                        │
           DIN-5 Pin 5 (Sink) ──────────┘
                │
              [R_snk] 220Ω (e.g., R9)
                │
           CM4 GPIO TX (3.3V logic)
           (e.g., GPIO 14 for UART0)

    DIN-5 Pin 2 ── GND (cable shield, optional)
    DIN-5 Pin 1, 3 ── NC (not connected)
```

### All 4 Ports Wiring

```
    +5V ──┬── R8  (220Ω) ── J5 Pin 4 ──┐    J5 Pin 5 ── R9  (220Ω) ── GPIO 14 (UART0)
          │                              │
          ├── R10 (220Ω) ── J6 Pin 4 ──┐│    J6 Pin 5 ── R11 (220Ω) ── GPIO 4  (UART3)
          │                              ││
          ├── R12 (220Ω) ── J7 Pin 4 ──┐││   J7 Pin 5 ── R13 (220Ω) ── GPIO 8  (UART4)
          │                              │││
          └── R14 (220Ω) ── J8 Pin 4 ──┐│││  J8 Pin 5 ── R15 (220Ω) ── GPIO 12 (UART5)
                                        ││││
                               (to external receivers via MIDI cables)
```

### MIDI TX Activity LEDs (Optional)

```
    GPIO TX ──→ R_snk (220Ω) ──→ DIN Pin 5
                  │
                  ├──→ R16 (1kΩ) ──→ LED (yellow) ──→ GND
                  │
    (LED lights when TX is LOW = transmitting data)
```

Note: LED taps off the TX line. When TX goes LOW (sending MIDI byte), current flows through both the MIDI port AND the LED. The 1kΩ limits LED current to ~3mA — dim but visible. This is a quick-and-dirty indicator; for brighter LEDs, use a transistor buffer off a spare GPIO.

---

## 5. DSI Display Passthrough

Straight passthrough from CM4 DSI pins to a 15-pin FPC connector (J17). No active components needed.

```
    CM4 J2 DSI pins ──── [traces, controlled impedance] ──── J17 (15-pin FPC)
                                                                │
                                                           [FPC ribbon cable]
                                                                │
                                                          5" DSI Touchscreen
```

DSI differential pairs need 100Ω impedance matching. Keep traces short and equal length (within 0.5mm per pair). See [pcb-spec.md](pcb-spec.md) for layout rules.

---

## 6. MicroSD Card Slot

CM4 Lite has no eMMC — boots from MicroSD. Direct connection to CM4 SD interface pins.

```
    CM4 J2 ──── SD_CLK  ──── J18 (MicroSD) CLK
                SD_CMD  ──── J18 CMD
                SD_DAT0 ──── J18 DAT0
                SD_DAT1 ──── J18 DAT1
                SD_DAT2 ──── J18 DAT2
                SD_DAT3 ──── J18 DAT3
                             J18 VDD ── 3.3V
                             J18 VSS ── GND

    Decoupling: 100nF + 10µF near J18 VDD pin
```

---

## 7. Net Names Reference

For use when drawing the KiCad schematic:

| Net Name | Description |
|-----------|-------------|
| `VBUS_5V` | USB-C PD input, main 5V rail |
| `V3V3` | 3.3V regulated rail (from LDO) |
| `USB_UP_DP`, `USB_UP_DM` | CM4 → Hub IC1 upstream |
| `USB_GAD_DP`, `USB_GAD_DM` | CM4 USB OTG → DAW USB-C |
| `HUB1_DN1_DP` ... `HUB1_DN4_DP` | Hub IC1 downstream ports |
| `HUB2_DN1_DP` ... `HUB2_DN4_DP` | Hub IC2 downstream ports |
| `MIDI_TX0` | GPIO 14 → MIDI OUT J5 |
| `MIDI_TX1` | GPIO 4 → MIDI OUT J6 |
| `MIDI_TX2` | GPIO 8 → MIDI OUT J7 |
| `MIDI_TX3` | GPIO 12 → MIDI OUT J8 |
| `DSI_CLK_P/N`, `DSI_D0_P/N` ... | DSI differential pairs |
| `SD_CLK`, `SD_CMD`, `SD_DAT0-3` | MicroSD interface |

---

## KiCad Hierarchical Sheet Organization

```
midi-box-v2.kicad_sch (root)
    ├── power.kicad_sch        — USB-C PD, LDO, bulk caps, polyfuses
    ├── cm4.kicad_sch          — CM4 connectors, decoupling, boot config, SD slot
    ├── usb_hub.kicad_sch      — USB2514B ×2, crystals, cascade wiring
    ├── usb_ports.kicad_sch    — 8× USB-A connectors, ESD, polyfuses
    ├── midi_out.kicad_sch     — 4× UART → resistor → DIN-5
    └── connectors.kicad_sch   — DSI FPC, fan headers, LEDs, mounting holes
```
