# MIDI Box v2 — EasyEDA Pro Step-by-Step Build Guide

Complete walkthrough for drawing the schematic and PCB in EasyEDA Pro, using LCSC parts, and ordering from JLCPCB.

---

## 0. Setup

### Create Project

1. Go to **https://pro.easyeda.com** → Sign in (same account as JLCPCB/LCSC)
2. **File → New → Project** → Name: `midi-box-v2`
3. **File → New → Schematic** — this creates your first schematic sheet
4. Right-click the project in the left panel → **New → Schematic** — repeat to create **6 sheets total**:

| Sheet Name | Contents |
|------------|----------|
| `01_Power` | USB-C PD input, Schottky, LDO, bulk caps |
| `02_CM4` | CM4 connectors, decoupling, boot config, SD slot |
| `03_USB_Hub` | USB2514B ×2, crystals, cascade |
| `04_USB_Ports` | 8× USB-A connectors, ESD, polyfuses |
| `05_MIDI_OUT` | 4× UART → 220Ω → DIN-5 |
| `06_Connectors` | DSI FPC, fan headers, LEDs, mounting holes |

### EasyEDA Pro Settings

- **Design → Design Rules** → set min clearance 0.15mm, min trace 0.15mm
- **Units**: mm
- **Grid**: 0.5mm for placement, 0.25mm for routing

---

## 1. Sheet: 01_Power (USB-C PD + Regulation)

### Step 1.1 — Place USB-C Power Connector (J3)

1. **Place → Component** (or press `P`)
2. In the search bar, type LCSC number: **`C2765186`**
3. Click the part → **Place** → drop it on the sheet
4. Label it `J3` — this is your USB-C PD power input

### Step 1.2 — Place STUSB4500 (U13)

1. Search: **`C2678061`**
2. Place → label `U13`
3. If out of stock: search `STUSB4500` and pick any available QFN-24 variant

### Step 1.3 — Place CC Resistors

1. Search: **`C25905`** (5.1kΩ 0402)
2. Place two copies → label `R3`, `R4`
3. Wire:
   - `R3` → J3 CC1 pin → R3 → GND
   - `R4` → J3 CC2 pin → R4 → GND
   - Also connect CC1/CC2 to STUSB4500 CC1/CC2 pins

### Step 1.4 — Place STUSB4500 Support Components

| Search | Label | Wire to |
|--------|-------|---------|
| `C25744` (10kΩ 0402) | R5 | STUSB4500 ADDR → R5 → GND |
| `C1779` (4.7µF 0805) | C18 | STUSB4500 VDD → C18 → GND |
| `C1525` (100nF 0402) | C19 | STUSB4500 VDD → C19 → GND |

### Step 1.5 — Place Schottky Diode (D1)

1. Search: **`C8678`** (SS34)
2. Place → label `D1`
3. Wire: J3 VBUS → D1 anode → D1 cathode → net `VBUS_5V`

### Step 1.6 — Place Bulk Capacitor

1. Search: **`C72505`** (100µF electrolytic)
2. Place → label `C20`
3. Wire: `VBUS_5V` → C20 + → C20 - → GND

### Step 1.7 — Place 3.3V LDO (U14)

1. Search: **`C51118`** (AP2112K-3.3)
2. Place → label `U14`
3. Wire:
   - VIN → `VBUS_5V`
   - VOUT → net `V3V3`
   - GND → GND
   - EN → VIN (always enabled)

### Step 1.8 — Place LDO Caps

| Search | Label | Wire to |
|--------|-------|---------|
| `C1525` (100nF) | C22 | U14 VIN → C22 → GND |
| `C19702` (10µF) | C21 | U14 VOUT → C21 → GND |

### Step 1.9 — Add Power Flags & Net Labels

1. **Place → Net Label** → type `VBUS_5V` → attach to the 5V rail output
2. **Place → Net Label** → type `V3V3` → attach to LDO output
3. **Place → Power Port** → `GND` on all ground connections
4. Add a **net label** `PD_POWER_OK` on STUSB4500 POWER_OK pin (for optional LED)
5. Add net labels `I2C_SCL` and `I2C_SDA` on STUSB4500 SCL/SDA pins (for NVM programming)

### Wiring Diagram for This Sheet

```
    J3 (USB-C) VBUS ──→ D1 (SS34) ──→ VBUS_5V ──┬── C20 (100µF) ── GND
                                                   ├── C22 (100nF) ── GND
    J3 CC1 ──→ R3 (5.1k) ──→ GND                 │
    J3 CC1 ──→ U13 (STUSB4500) CC1                ├── U14 (AP2112K) VIN
    J3 CC2 ──→ R4 (5.1k) ──→ GND                 │         │
    J3 CC2 ──→ U13 CC2                            │      VOUT ──→ V3V3
                                                   │         │
    U13 VDD ──→ V3V3                               │      C21 (10µF) ── GND
    U13 ADDR ──→ R5 (10k) ──→ GND                 │
    U13 SCL ──→ I2C_SCL                            │
    U13 SDA ──→ I2C_SDA                            │
    U13 VBUS_EN_SNK ──→ VBUS_5V                    │
    U13 POWER_OK ──→ PD_POWER_OK                   │
```

---

## 2. Sheet: 02_CM4 (Compute Module 4 Carrier)

### Step 2.1 — Place CM4 Connectors (J1, J2)

1. Search: **`C506281`** (Hirose DF40C-100DS-0.4V)
2. Place two copies → label `J1`, `J2`

> **Important:** EasyEDA may show this as a generic 100-pin connector. That's fine — you'll assign nets to specific pins. If the exact Hirose part isn't available, search `DF40C-100` or manually create a 2×100-pin symbol.

### Step 2.2 — Wire Power Pins

On J1:
- Pins 4, 5 → net `VBUS_5V` (5V power input to CM4)
- Pins 2, 6, 10, 14, 18, 22 → `GND`

### Step 2.3 — Wire UART (MIDI) Pins

On J1:
- Pin 76 → net label `MIDI_TX0` (GPIO 14, UART0)
- Pin 80 → net label `MIDI_TX1` (GPIO 4, UART3)
- Pin 82 → net label `MIDI_TX2` (GPIO 8, UART4)
- Pin 84 → net label `MIDI_TX3` (GPIO 12, UART5)

### Step 2.4 — Wire USB Pins

On J2:
- Pins 1, 2 → net labels `USB_UP_DM`, `USB_UP_DP` (to hub IC upstream)
- Pins 5, 6 → net labels `USB_GAD_DM`, `USB_GAD_DP` (to DAW USB-C)

### Step 2.5 — Wire DSI Pins

On J2:
- Pins 30–45 → net labels `DSI_CLK_P`, `DSI_CLK_N`, `DSI_D0_P`, `DSI_D0_N`, `DSI_D1_P`, `DSI_D1_N`

> Check the official CM4 datasheet for exact DSI pin numbers. The Raspberry Pi Foundation provides a reference carrier schematic.

### Step 2.6 — Wire SD Card Pins

On J2:
- Pin 74 → `SD_CLK`
- Pin 76 → `SD_CMD`
- Pins 78–84 → `SD_DAT0`, `SD_DAT1`, `SD_DAT2`, `SD_DAT3`

### Step 2.7 — Place MicroSD Slot (J18)

1. Search: **`C585350`**
2. Place → label `J18`
3. Wire SD_CLK/CMD/DAT0-3 from net labels to J18 pins
4. J18 VDD → `V3V3`, J18 VSS → `GND`

### Step 2.8 — Place CM4 Decoupling

| Search | Label | Placement |
|--------|-------|-----------|
| `C1525` (100nF) ×4 | C1, C2, C3, C4 | Near J1 pins 4/5, across to GND |
| `C19702` (10µF) ×1 | C5 | Near J1 5V pins |

### Step 2.9 — Boot Config

1. Place a 10kΩ resistor (`C25744`) from nRPIBOOT (J1 pin 91) to V3V3 — label `R_BOOT`
2. Place a 2-pin header next to it — short pins = USB boot, open = normal boot

### Step 2.10 — I2C Lines

- Wire J1 GPIO 2 → net `I2C_SCL` (connects to STUSB4500 on power sheet)
- Wire J1 GPIO 3 → net `I2C_SDA`

---

## 3. Sheet: 03_USB_Hub (USB2514B ×2 Cascade)

### Step 3.1 — Place Hub IC1 (U2)

1. Search: **`C136518`** (USB2514B-I/M2)
2. Place → label `U2`

### Step 3.2 — Place Crystal for U2

1. Search: **`C32346`** (24 MHz crystal)
2. Place → label `Y1`
3. Search: **`C1808`** (18pF 0402) — place two → label `CY1a`, `CY1b`
4. Wire:
   - U2 XTAL1 → Y1 pin 1 → CY1a → GND
   - U2 XTAL2 → Y1 pin 2 → CY1b → GND

### Step 3.3 — Wire U2 Upstream

- U2 USBDP → net `USB_UP_DP` (from CM4 sheet)
- U2 USBDM → net `USB_UP_DM`

### Step 3.4 — Wire U2 Downstream Ports 1–3

- U2 DN1_DP → net `HUB1_DN1_DP`
- U2 DN1_DM → net `HUB1_DN1_DM`
- U2 DN2_DP → net `HUB1_DN2_DP`
- U2 DN2_DM → net `HUB1_DN2_DM`
- U2 DN3_DP → net `HUB1_DN3_DP`
- U2 DN3_DM → net `HUB1_DN3_DM`

### Step 3.5 — Wire U2 Port 4 → U3 Cascade

- U2 DN4_DP → net `HUB_CASCADE_DP`
- U2 DN4_DM → net `HUB_CASCADE_DM`

### Step 3.6 — Place Hub IC2 (U3) + Crystal

1. Same parts: `C136518` → U3, `C32346` → Y2, `C1808` ×2 → CY2a, CY2b
2. Wire crystal same way as U2

### Step 3.7 — Wire U3 Upstream (Cascade)

- U3 USBDP → net `HUB_CASCADE_DP`
- U3 USBDM → net `HUB_CASCADE_DM`

### Step 3.8 — Wire U3 Downstream Ports 1–4

- U3 DN1_DP/DM → `HUB2_DN1_DP/DM`
- U3 DN2_DP/DM → `HUB2_DN2_DP/DM`
- U3 DN3_DP/DM → `HUB2_DN3_DP/DM`
- U3 DN4_DP/DM → `HUB2_DN4_DP/DM`

### Step 3.9 — Hub IC Config Pins (Both U2 and U3)

For each hub IC:
- VDD33 → `V3V3` + C (100nF `C1525`) → GND
- VDDA33 → `V3V3` + C (100nF) → GND
- CRFILT → C (10nF) → GND
- RESET_N → 10kΩ (`C25744`) → `V3V3`
- CFG_SEL0 → GND
- CFG_SEL1 → GND
- VBUS_DET → `VBUS_5V` via 100kΩ/47kΩ divider (check datasheet)
- PRTPWR1–4 → (leave NC or connect to polyfuse enable — optional)
- Upstream pull-up: 1.5kΩ (`C4026`) from D+ to `V3V3`

### Step 3.10 — Decoupling

Place per hub IC:
- 4× `C1525` (100nF) near VDD pins
- 1× `C19702` (10µF) bulk cap

---

## 4. Sheet: 04_USB_Ports (8× USB-A + ESD + Polyfuses)

### Step 4.1 — Place 7× USB-A Connectors

1. Search: **`C46407`** (USB-A female)
2. Place 7 copies → label `J9` through `J15`

> 7 ports from the hub ICs. If you want an 8th (J16), connect it to the CM4's second USB host port directly — useful for a spare or debug port.

### Step 4.2 — Place ESD Protection (One Per Port)

1. Search: **`C7519`** (USBLC6-2SC6)
2. Place 7 copies → label `U4` through `U10`
3. For each port:
   - USBLC6 IO1 → connector D+
   - USBLC6 IO2 → connector D-
   - USBLC6 VBUS → VBUS_5V
   - USBLC6 GND → GND

Also place one more (U12) on the CM4 upstream USB lines.

### Step 4.3 — Place Polyfuses (One Per Port)

1. Search: **`C70069`** (500mA resettable fuse, 1206)
2. Place 7 copies → label `F1` through `F7`
3. Wire: `VBUS_5V` → F1 → J9 VBUS pin (repeat for each port)

### Step 4.4 — Wire Data Lines

For ports from Hub IC1 (J9–J11):
- J9 D+ → `HUB1_DN1_DP`, J9 D- → `HUB1_DN1_DM`
- J10 D+ → `HUB1_DN2_DP`, J10 D- → `HUB1_DN2_DM`
- J11 D+ → `HUB1_DN3_DP`, J11 D- → `HUB1_DN3_DM`

For ports from Hub IC2 (J12–J15):
- J12 D+ → `HUB2_DN1_DP`, J12 D- → `HUB2_DN1_DM`
- J13 D+ → `HUB2_DN2_DP`, J13 D- → `HUB2_DN2_DM`
- J14 D+ → `HUB2_DN3_DP`, J14 D- → `HUB2_DN3_DM`
- J15 D+ → `HUB2_DN4_DP`, J15 D- → `HUB2_DN4_DM`

### Step 4.5 — DAW Mode USB-C (J4)

1. Search: **`C2765186`** (USB-C 16-pin) → label `J4`
2. Search: **`C25905`** (5.1kΩ) → place 2 → label `R6`, `R7`
3. Wire:
   - J4 D+ → `USB_GAD_DP` (to CM4 OTG port)
   - J4 D- → `USB_GAD_DM`
   - J4 CC1 → R6 → GND
   - J4 CC2 → R7 → GND
   - J4 VBUS → leave NC (Mac provides power, but we don't use it)
   - J4 GND → GND

---

## 5. Sheet: 05_MIDI_OUT (4× DIN-5 Ports)

### Step 5.1 — Place DIN-5 Connectors

DIN-5 connectors are usually **not on LCSC**. Two options:

**Option A:** Search `DIN 5` in EasyEDA's library — there may be community footprints. Use a 5-pin generic connector symbol and assign the CUI SDS-50J footprint later.

**Option B:** Create a custom 5-pin symbol:
1. **File → New → Symbol** → name: `DIN5_MIDI_OUT`
2. Add 5 pins: Pin1 (NC), Pin2 (GND), Pin3 (NC), Pin4 (Source), Pin5 (Sink)
3. Save → use this symbol 4 times

Place 4 connectors → label `J5`, `J6`, `J7`, `J8`

### Step 5.2 — Place 220Ω Resistors

1. Search: **`C17557`** (220Ω 0805)
2. Place 8 copies → label `R8` through `R15`

### Step 5.3 — Wire Each MIDI Port

**Port J5 (MS-20 Mini, UART0):**
```
VBUS_5V → R8 (220Ω) → J5 Pin 4
MIDI_TX0 → R9 (220Ω) → J5 Pin 5
J5 Pin 2 → GND
```

**Port J6 (Volca #1, UART3):**
```
VBUS_5V → R10 (220Ω) → J6 Pin 4
MIDI_TX1 → R11 (220Ω) → J6 Pin 5
J6 Pin 2 → GND
```

**Port J7 (Volca #2, UART4):**
```
VBUS_5V → R12 (220Ω) → J7 Pin 4
MIDI_TX2 → R13 (220Ω) → J7 Pin 5
J7 Pin 2 → GND
```

**Port J8 (Volca #3, UART5):**
```
VBUS_5V → R14 (220Ω) → J8 Pin 4
MIDI_TX3 → R15 (220Ω) → J8 Pin 5
J8 Pin 2 → GND
```

### Step 5.4 — Add Silkscreen Labels

Use **Place → Text** to label each DIN connector on the schematic:
- J5: `MS-20`
- J6: `VOLCA 1`
- J7: `VOLCA 2`
- J8: `VOLCA 3`

---

## 6. Sheet: 06_Connectors (DSI, Fans, LEDs)

### Step 6.1 — DSI FPC Connector (J17)

1. Search: **`C262652`** (15-pin FPC 1mm pitch)
2. Place → label `J17`
3. Wire DSI net labels from CM4 sheet:
   - `DSI_CLK_P`, `DSI_CLK_N`
   - `DSI_D0_P`, `DSI_D0_N`
   - `DSI_D1_P`, `DSI_D1_N`
   - Power pins: VDD → `VBUS_5V`, GND → `GND`

### Step 6.2 — Fan Headers (J19, J20)

1. Search: **`C158012`** (2-pin JST-XH)
2. Place 2 copies → label `J19`, `J20`
3. Wire: Pin 1 → `VBUS_5V`, Pin 2 → `GND` (always-on fans)

### Step 6.3 — Power LED (LED1)

1. Search: **`C2297`** (green 0805 LED) → label `LED1`
2. Search: **`C11702`** (1kΩ 0402) → label `R16`
3. Wire: `VBUS_5V` → R16 → LED1 anode → LED1 cathode → GND

### Step 6.4 — Activity LED (LED2)

1. Search: **`C72041`** (blue 0805 LED) → label `LED2`
2. Place another 1kΩ resistor → label `R17`
3. Wire: CM4 GPIO (pick a spare, e.g., GPIO 25) → R17 → LED2 → GND
4. Add net label `ACT_LED` on the GPIO side

### Step 6.5 — MIDI TX LEDs (LED3–LED6, Optional)

1. Search: **`C2296`** (yellow 0805 LED) → place 4 → label `LED3`–`LED6`
2. Place 4× 1kΩ resistors → `R18`–`R21`
3. Wire each between the MIDI_TX net and GND:
   - `MIDI_TX0` → R18 → LED3 → GND
   - `MIDI_TX1` → R19 → LED4 → GND
   - `MIDI_TX2` → R20 → LED5 → GND
   - `MIDI_TX3` → R21 → LED6 → GND

> Note: these LEDs share the TX line with the MIDI resistors. They'll blink when data is sent. Dim but functional.

### Step 6.6 — Mounting Holes

1. Search `mounting hole` in EasyEDA library → select M3 (3.2mm)
2. Place 4 copies → label `H1`–`H4`
3. Connect pad to GND (ground-referenced mounting)

---

## 7. Convert Schematic → PCB

### Step 7.1 — Run ERC

1. **Design → Electrical Rules Check (ERC)**
2. Fix all errors. Common issues:
   - Unconnected pins → add "no connect" flags (×) on unused CM4 pins
   - Power flag missing → ensure at least one power port symbol per net
   - Net name conflicts → rename duplicates

### Step 7.2 — Generate PCB

1. **Design → Update/Convert Schematic to PCB**
2. EasyEDA creates a new PCB document with all footprints in a pile
3. All nets (wires) are shown as ratsnest lines

---

## 8. PCB Layout

### Step 8.1 — Board Setup

1. **Design → Board Options**:
   - Layers: **4** (if available in EasyEDA Pro; otherwise use 2-layer and widen USB traces)
   - Units: mm
   - Grid: 0.5mm placement, 0.25mm routing
2. Draw board outline: **~120mm × 100mm** rectangle on the Board Outline layer

### Step 8.2 — Place Connectors First (Edge Components)

These define your board edges:

| Edge | Components |
|------|-----------|
| **Top** | J3 (USB-C power), J4 (USB-C DAW), J19/J20 (fans) |
| **Bottom** | J9–J15 (USB-A ×7), J5–J8 (DIN-5 ×4) |
| **Right** | J17 (DSI FPC) |
| **Left** | J18 (MicroSD) — or near CM4 |

### Step 8.3 — Place CM4 Connectors

1. Place J1, J2 in the **center** of the board
2. The CM4 module will sit on top — keep a clearance zone above (no tall components under CM4)
3. Place decoupling caps C1–C5 **within 5mm** of J1 power pins

### Step 8.4 — Place ICs Near Their Connections

1. U2, U3 (USB hub ICs) → between CM4 and USB-A connectors
2. U13 (STUSB4500) → near J3 (USB-C power)
3. U14 (LDO) → near U13
4. U4–U10 (ESD) → as close as possible to each USB-A connector

### Step 8.5 — Place Passives

- Decoupling caps: **within 5mm** of the IC they serve
- Crystal: **within 10mm** of hub IC, with GND guard ring
- MIDI resistors: **within 10mm** of DIN-5 connectors
- Polyfuses: between 5V plane and each USB-A VBUS

### Step 8.6 — Route Critical Traces First

**Priority order:**

1. **USB differential pairs** (D+/D-):
   - Route as paired traces (use EasyEDA's differential pair tool if available)
   - Width: 0.18mm, gap: 0.18mm (90Ω differential)
   - Keep on top layer, over GND plane
   - No vias in differential pairs if possible
   - Length-match each pair within 0.5mm

2. **DSI differential pairs**:
   - Same rules as USB but 100Ω impedance
   - Keep traces as short as possible (<30mm)

3. **SD card traces**:
   - Length-match CLK/CMD/DAT lines within 5mm
   - Keep under 50mm total length

4. **MIDI TX traces** (low priority):
   - 31250 baud — no impedance requirement
   - Route on bottom layer to separate from USB
   - Any width 0.2mm+ is fine

5. **Power traces**:
   - Use copper pours / planes for VBUS_5V and GND
   - 5V traces to CM4 should be wide (0.5mm+) or use plane

### Step 8.7 — Copper Pours

1. **GND plane** on Layer 2 (inner 1): solid fill, no splits
2. **VBUS_5V plane** on Layer 3 (inner 2): fill most of the board
3. **V3V3 island** on Layer 3: small area near hub ICs and LDO
4. Top/bottom: add GND copper pours in empty areas (stitched with vias)

### Step 8.8 — Add Silkscreen

- Label each USB-A port: `USB1` through `USB7`
- Label each DIN-5: `MIDI 1 (MS-20)`, `MIDI 2 (V1)`, `MIDI 3 (V2)`, `MIDI 4 (V3)`
- Label USB-C connectors: `5V PD IN`, `DAW (Mac)`
- Add board name: `MIDI-BOX v2`
- Add your name / date / revision

---

## 9. Design Rule Check & Review

1. **Design → DRC** — fix all errors
2. **3D View** (Alt+3) — check:
   - CM4 module clears components below it
   - DIN-5 connectors don't collide with USB-A connectors
   - USB-C connectors are flush with board edge
   - Mounting holes are accessible

---

## 10. Order from JLCPCB

### Step 10.1 — Generate Manufacturing Files

EasyEDA Pro has a **one-click JLCPCB export**:

1. **Fabrication → One-click Order PCB/SMT at JLCPCB**
2. This auto-generates: Gerber, BOM, and CPL (pick-and-place) files
3. Review the BOM — ensure all LCSC part numbers are populated
4. Remove through-hole parts from SMT BOM (you'll hand-solder those)

### Step 10.2 — JLCPCB Order Settings

| Setting | Value |
|---------|-------|
| Layers | 4 |
| PCB Qty | 5 (minimum) |
| Thickness | 1.6mm |
| Surface Finish | ENIG (for QFN pads) |
| Copper Weight | 1 oz |
| Impedance Control | Yes — specify 90Ω diff for USB pairs |
| SMT Assembly | Yes (top side) |
| Assembly Side | Top |
| Tooling Holes | Added by JLCPCB |

### Step 10.3 — Review Before Paying

- Check the JLCPCB Gerber viewer — all layers look correct
- Verify BOM quantities match your design
- Check for any "part out of stock" warnings — swap LCSC numbers if needed
- Estimated lead time: ~7–10 days fabrication + 5–7 days shipping

---

## 11. After Boards Arrive

### Hand-Solder Through-Hole Parts

| Part | Count | Difficulty |
|------|-------|-----------|
| DIN-5 connectors (J5–J8) | 4 | Easy |
| USB-A connectors (J9–J15) | 7 | Easy |
| JST-XH fan headers (J19, J20) | 2 | Easy |
| 100µF electrolytic cap (C20) | 1 | Easy |
| **Total hand-solder** | **14 parts** | ~20 min |

### Plug In CM4

1. Align CM4 module on J1/J2 connectors
2. Press down firmly until it clicks
3. Insert MicroSD with flashed Pi OS

### Test Sequence

| Step | Test | Expected Result |
|------|------|-----------------|
| 1 | Plug USB-C PD charger into J3 | Power LED (LED1) lights up |
| 2 | Measure VBUS_5V at TP1 | 4.7–5.0V |
| 3 | Measure V3V3 at TP2 | 3.3V |
| 4 | Insert MicroSD, power on | CM4 boots, activity LED blinks |
| 5 | Connect to WiFi hotspot | Web UI loads at :8080 |
| 6 | Plug USB MIDI device into J9 | Device appears in `aconnect -l` |
| 7 | Connect DIN cable to J5 | Send MIDI note, MS-20 responds |
| 8 | Connect Mac to J4 (DAW port) | Pi appears as USB MIDI device in Logic |

---

## Quick Reference: All LCSC Part Numbers

Copy-paste these into EasyEDA search:

```
C506281   — Hirose DF40C-100DS (CM4 connector) ×2
C136518   — USB2514B-I/M2 (USB hub IC) ×2
C32346    — 24 MHz crystal ×2
C7519     — USBLC6-2SC6 (USB ESD) ×9
C2678061  — STUSB4500QTR (PD sink) ×1
C2765186  — USB-C 16-pin receptacle ×2
C51118    — AP2112K-3.3 (3.3V LDO) ×1
C8678     — SS34 Schottky diode ×1
C70069    — 500mA polyfuse ×8
C46407    — USB-A female connector ×7
C262652   — 15-pin FPC connector ×1
C585350   — MicroSD card slot ×1
C158012   — JST-XH 2-pin header ×2
C1525     — 100nF 0402 capacitor ×16
C19702    — 10µF 0805 capacitor ×4
C1808     — 18pF 0402 capacitor ×4
C1779     — 4.7µF 0805 capacitor ×1
C72505    — 100µF electrolytic capacitor ×1
C17557    — 220Ω 0805 resistor ×8
C11702    — 1kΩ 0402 resistor ×6
C4026     — 1.5kΩ 0402 resistor ×2
C25905    — 5.1kΩ 0402 resistor ×4
C25744    — 10kΩ 0402 resistor ×1
C2297     — Green LED 0805 ×1
C72041    — Blue LED 0805 ×1
C2296     — Yellow LED 0805 ×4
```

> **Before ordering:** Search each number in LCSC to verify stock. Parts go out of stock often — substitute with same value/package alternatives.
