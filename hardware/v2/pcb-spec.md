# MIDI Box v2 — PCB Manufacturing Specification

## Fabrication Specs

Order from JLCPCB or PCBWay. These specs are compatible with both.

| Parameter | Value | Notes |
|-----------|-------|-------|
| **Layers** | 4 | Signal – GND – Power – Signal |
| **Board thickness** | 1.6mm | Standard |
| **Copper weight** | 1 oz (outer), 1 oz (inner) | 1 oz is fine for our currents |
| **Board dimensions** | ~120mm × 100mm | Final size TBD after layout |
| **Min trace width** | 0.15mm (6 mil) | USB diff pairs will be wider |
| **Min trace spacing** | 0.15mm (6 mil) | |
| **Min via drill** | 0.3mm | Standard via |
| **Surface finish** | **ENIG** (recommended) or HASL | ENIG for fine-pitch QFN pads |
| **Solder mask** | Green (cheapest) or black | |
| **Silkscreen** | White | Both sides |
| **Impedance control** | **Yes** — 90Ω differential for USB | Specify in JLCPCB order notes |
| **Castellated holes** | No | |
| **Panelization** | No (single board) | |

---

## 4-Layer Stackup

```
    Layer 1 (Top)     — Signal: USB data, MIDI TX, SD, component pads
    Layer 2 (Inner 1) — GND plane (solid, unbroken)
    Layer 3 (Inner 2) — Power plane (5V and 3.3V split)
    Layer 4 (Bottom)  — Signal: remaining traces, through-hole pads
```

### Why 4 Layers?

1. **USB 2.0 impedance** — 90Ω differential pairs need a solid reference plane directly below. With a 2-layer board, impedance control is nearly impossible.
2. **Power integrity** — solid 5V plane distributes current evenly to CM4, hub ICs, and USB ports without thick traces.
3. **EMI** — ground plane shields MIDI UART signals (31250 baud) from USB (480 MHz) crosstalk.
4. **Cost** — JLCPCB 4-layer is only ~$2 more than 2-layer for 5 boards. Negligible.

---

## Trace Width Guidelines

| Signal Type | Width | Spacing | Layer | Notes |
|-------------|-------|---------|-------|-------|
| USB 2.0 differential pairs | **0.18mm** (7 mil) | 0.18mm gap | Top | 90Ω differential impedance (check JLCPCB calculator) |
| DSI differential pairs | **0.1mm** (4 mil) | 0.15mm gap | Top | 100Ω differential — short traces only |
| MIDI TX (UART, 31250 baud) | 0.25mm (10 mil) | — | Top or Bottom | Low speed, no impedance requirement |
| SD card data | 0.2mm (8 mil) | — | Top | Keep traces <50mm, matched length |
| 5V power traces | 0.5mm+ (20 mil) | — | Top / Power plane | Use plane for main distribution |
| 3.3V power traces | 0.3mm (12 mil) | — | Power plane | Low current rail |
| I2C (SCL/SDA) | 0.2mm (8 mil) | — | Any | Short run to STUSB4500 only |
| General GPIO | 0.2mm (8 mil) | — | Any | LEDs, boot config |

---

## Layout Guidelines

### CM4 Connector Area
- Place J1 and J2 (Hirose 100-pin) at the center or one edge of the board
- Keep decoupling caps (C1–C5) within **5mm** of connector pins
- Route USB and DSI differential pairs on the top layer, directly over the GND plane
- MicroSD slot (J18) near CM4 — SD traces should be <30mm

### USB Hub ICs
- Place U2 (IC1) and U3 (IC2) near the CM4 USB output
- Crystal (Y1, Y2) within **10mm** of the IC, with ground guard ring
- Route downstream USB pairs as matched-length differential pairs
- Keep each D+/D- pair length-matched within **0.5mm**

### USB-A Connectors
- Place along one or two edges of the board (8 connectors)
- Option A: **8 in a row** on one edge (~110mm total width)
- Option B: **4 per edge** on two opposite edges
- Through-hole connectors — ensure clearance for plastic housing on the board edge
- ESD protection ICs (U4–U11) placed **as close as possible** to each connector

### MIDI DIN-5 Connectors
- Place along one edge, away from USB connectors
- Through-hole, spaced ~25mm center-to-center
- 220Ω resistors (0805 SMD) placed within 10mm of each DIN connector
- Route MIDI TX traces on bottom layer to avoid crossing USB pairs

### Power Input (USB-C PD)
- Place J3 (USB-C power) at a board edge — typically opposite from data connectors
- STUSB4500 (U13) within 15mm of J3
- Bulk cap C20 (100µF) close to J3
- Schottky D1 between J3 VBUS and the 5V rail

### DSI FPC Connector
- Place J17 at a board edge for easy ribbon cable routing to the display
- DSI differential pairs: short as possible, length-matched within pair

### Fan Headers
- Place J19, J20 at board edge or near mounting holes
- Connected directly to 5V and GND planes

---

## Mounting Holes

| Hole | Size | Purpose |
|------|------|---------|
| H1–H4 | M3 (3.2mm drill) | PCB mounting to enclosure |
| | Pad: 6mm copper ring | Connect to GND plane for shielding |

Place at four corners, inset ~5mm from board edge. Match to enclosure standoff positions.

---

## Component Placement Map (Conceptual)

```
    ┌──────────────────────────────────────────────────────────┐
    │  [USB-C PD]  [USB-C DAW]          [Fan] [Fan]          │ ← Top edge
    │     J3           J4                J19   J20            │
    │                                                          │
    │  ┌──────────┐  ┌──────────┐                             │
    │  │ STUSB4500│  │  LDO     │                             │
    │  │  (U13)   │  │ (U14)    │                             │
    │  └──────────┘  └──────────┘                             │
    │                                                          │
    │  (H1)                                          (H2)     │
    │                                                          │
    │      ┌──────────────────────────────┐                   │
    │      │     CM4 Module (J1, J2)      │                   │
    │      │     (Hirose connectors)      │                   │
    │      └──────────────────────────────┘                   │
    │                    │                                     │
    │            ┌───────┴───────┐                             │
    │            │    [SD Card]  │                             │
    │            │     J18       │                             │
    │            └───────────────┘                             │
    │                                                          │
    │  ┌─────┐  ┌─────┐                                      │
    │  │USB  │  │USB  │      [DSI FPC]                        │
    │  │Hub  │  │Hub  │        J17                            │ ← Right edge
    │  │IC1  │  │IC2  │                                       │
    │  │(U2) │  │(U3) │                                       │
    │  └─────┘  └─────┘                                       │
    │                                                          │
    │  (H3)                                          (H4)     │
    │                                                          │
    │ [J9][J10][J11][J12][J13][J14][J15][J16]                │ ← Bottom edge: 8× USB-A
    │                                                          │
    │ [J5 DIN][J6 DIN][J7 DIN][J8 DIN]                       │ ← Bottom edge: 4× MIDI OUT
    └──────────────────────────────────────────────────────────┘
```

> This is a rough placement guide. Adjust based on actual footprint sizes and routing constraints. The key rule: **USB connectors and MIDI connectors on accessible edges, power input on a separate edge.**

---

## Assembly Notes

### JLCPCB SMT Assembly

| Assembly Type | Components |
|---------------|-----------|
| **SMT (top side)** | All SMD: resistors, caps, ICs (USB2514B, STUSB4500, LDO, ESD), LEDs, crystals |
| **Through-hole (hand solder)** | DIN-5 ×4, USB-A ×8, JST fan headers ×2, DSI FPC |

Order SMT assembly from JLCPCB for all SMD parts. Hand-solder the through-hole connectors yourself — they're all standard and easy to solder.

### BOM and CPL Files

When ordering from JLCPCB, export from KiCad:
1. **Gerber files** — all 4 copper layers + mask + silkscreen + drill
2. **BOM CSV** — columns: `Comment, Designator, Footprint, LCSC Part Number`
3. **CPL (Component Placement List)** — columns: `Designator, Mid X, Mid Y, Rotation, Layer`

Use the [KiCad JLCPCB plugin](https://github.com/Bouni/kicad-jlcpcb-tools) to auto-generate these.

---

## Design Rule Check (DRC) Settings

Set these in KiCad before running DRC:

| Rule | Value |
|------|-------|
| Min clearance | 0.15mm |
| Min trace width | 0.15mm |
| Min via drill | 0.3mm |
| Min via annular ring | 0.13mm |
| Min hole-to-hole | 0.5mm |
| Board edge clearance | 0.3mm |
| Silk-to-pad clearance | 0.15mm |

---

## Pre-Order Checklist

Before submitting to JLCPCB:

- [ ] Run KiCad DRC — zero errors
- [ ] Run KiCad ERC (electrical rules check) — zero errors
- [ ] Verify all LCSC part numbers are in stock
- [ ] Check USB differential pair impedance with JLCPCB stackup calculator
- [ ] Verify CM4 connector footprint matches Hirose DF40C-100DS datasheet
- [ ] Confirm DIN-5 footprint pin assignment (pin 4 = source, pin 5 = sink)
- [ ] Check board outline fits inside enclosure design
- [ ] Verify mounting hole positions match enclosure standoffs
- [ ] Check all through-hole components have sufficient annular ring
- [ ] Generate and review 3D render in KiCad before ordering
