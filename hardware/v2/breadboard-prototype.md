# MIDI Box v2 — Breadboard Prototype (Same Components)

Test the v2 design on breadboards using the **exact same ICs and components** from [bom.md](bom.md). SMD parts go on adapter/breakout boards, then plug into the breadboard via 2.54mm pin headers.

---

## The Problem & Solution

SMD chips (QFN, SOT-23) can't plug into a breadboard. But you can solder them onto **adapter PCBs** that convert the SMD pads to standard 2.54mm DIP pins.

```
    SMD chip (QFN-36)          Adapter board              Breadboard
    ┌──────────┐          ┌──────────────────┐       ┌─────────────────┐
    │ ■■■■■■■■ │  solder  │ ■■■■■■■■         │  plug │ ○ ○ ○ ○ ○ ○ ○ ○│
    │ ■      ■ │ ───────→ │ ■      ■  ▌▌▌▌▌ │ ────→ │ ○ ○ ○ ○ ○ ○ ○ ○│
    │ ■■■■■■■■ │          │ ■■■■■■■■  ▌▌▌▌▌ │       │ ○ ○ ○ ○ ○ ○ ○ ○│
    └──────────┘          └──────────────────┘       └─────────────────┘
                           (pins on 2.54mm grid)
```

---

## Component-by-Component Plan

### Every v2 BOM item → how to put it on a breadboard:

| v2 Component | Package | Breadboard Method |
|-------------|---------|-------------------|
| **USB2514B** | QFN-36 | QFN-36 to DIP adapter + hand solder |
| **STUSB4500** | QFN-24 | QFN-24 to DIP adapter + hand solder |
| **AP2112K-3.3** (LDO) | SOT-23-5 | SOT-23 to DIP adapter + hand solder |
| **USBLC6-2SC6** (ESD) | SOT-23-6 | SOT-23 to DIP adapter + hand solder |
| **SS34 Schottky** | SMA | SMA to DIP adapter, OR use through-hole **1N5822** (same specs) |
| **24 MHz crystal** | 3215 SMD | Solder onto QFN adapter board next to USB2514B |
| **100nF caps** | 0402 | Use **through-hole 100nF ceramic** (same value, just bigger) |
| **10µF caps** | 0805 | Use **through-hole 10µF electrolytic** (same value) |
| **18pF caps** | 0402 | Use **through-hole 18pF ceramic** |
| **4.7µF cap** | 0805 | Use **through-hole 4.7µF ceramic/electrolytic** |
| **100µF cap** | 8×10mm electrolytic | Already through-hole — **use directly** |
| **220Ω resistors** | 0805 | Use **through-hole 220Ω 1/4W** (same value) |
| **1kΩ resistors** | 0402 | Use **through-hole 1kΩ 1/4W** |
| **1.5kΩ resistors** | 0402 | Use **through-hole 1.5kΩ 1/4W** |
| **5.1kΩ resistors** | 0402 | Use **through-hole 5.1kΩ 1/4W** |
| **10kΩ resistors** | 0402 | Use **through-hole 10kΩ 1/4W** |
| **500mA polyfuses** | 1206 | Use **through-hole 500mA polyfuse** (radial lead) |
| **LEDs** | 0805 | Use **5mm through-hole LEDs** (same colors) |
| **DIN-5 connectors** | Through-hole | **Use directly** — pins fit breadboard |
| **USB-A connectors** | Through-hole | **USB-A female breakout boards** (DIP) |
| **USB-C connectors** | SMD mid-mount | **USB-C female breakout boards** (DIP) |
| **DSI FPC connector** | SMD | Skip — test DSI on CM4 IO Board directly |
| **MicroSD slot** | SMD | Skip — CM4 IO Board has one built in |
| **CM4 + Hirose connectors** | SO-DIMM / 100-pin SMD | **Use CM4 IO Board** as stand-in |

`★ Insight ─────────────────────────────────────`
**Resistors and capacitors are value-defined, not package-defined.** A 220Ω resistor is 220Ω whether it's an 0805 SMD chip or a through-hole 1/4W axial. The circuit doesn't care about the physical size — only the electrical value matters. So for passives (R, C, L), you can freely use through-hole equivalents on a breadboard. The only components where the **exact same physical part** matters are the ICs — those have specific pinouts, internal logic, and configuration registers. That's why we use adapter boards for the ICs but through-hole substitutes for passives.
`─────────────────────────────────────────────────`

---

## Adapter Boards Shopping List

### QFN / SOT-23 to DIP Adapters

These are generic, gold-plated PCBs. Buy a variety pack — they're reusable.

| Adapter | For Which IC | Qty Needed | AliExpress Search | Amazon Search |
|---------|-------------|-----------|-------------------|---------------|
| **QFN-36 to DIP-36** (0.5mm pitch) | USB2514B | 2 | `"QFN36 to DIP36 adapter 0.5mm"` | `"QFN36 DIP adapter board"` |
| **QFN-24 to DIP-24** (0.5mm pitch) | STUSB4500 | 1 | `"QFN24 to DIP24 adapter 0.5mm"` | `"QFN24 DIP adapter board"` |
| **SOT-23-5/6 to DIP** | AP2112K, USBLC6 | 10 | `"SOT23 to DIP adapter board"` | `"SOT-23 breakout board"` |
| **SMA to DIP** | SS34 Schottky | 1 | `"SMA diode adapter DIP"` | — (or just use 1N5822 through-hole) |

**Recommended: buy a multi-pack adapter kit**

| Product | Price | What's Inside |
|---------|-------|---------------|
| **SMD to DIP adapter assortment kit** | ~$8–12 | AliExpress: `"SMD to DIP adapter board kit QFN SSOP SOT23"` — usually includes QFN-8/16/24/32/36/48, SSOP, SOT-23, SMA, all with pin headers |
| **Specific QFN-36 adapters (5-pack)** | ~$3 | AliExpress: `"QFN36 adapter board 0.5mm pitch"` |

> **Important:** Match the **pitch** (pad spacing) of the adapter to the IC. USB2514B is QFN-36 with **0.5mm pitch**. STUSB4500 is QFN-24 with **0.5mm pitch**. Most adapter kits include 0.5mm versions.

### Pin Headers

You'll solder 2.54mm pin headers onto each adapter board so they plug into the breadboard.

| Product | Qty | Price | Search |
|---------|-----|-------|--------|
| **2.54mm male pin headers** (40-pin strips, breakable) | 5 strips | ~$1 | `"2.54mm pin header male 40 pin"` — you already have these if you've done any Arduino/Pi work |

---

## SMD ICs to Buy (Same as v2 BOM)

Order these from **LCSC.com** directly (minimum order ~$2 shipping). Same parts that go on the final PCB.

| IC | LCSC # | Package | Qty for Breadboard | Unit Price | Notes |
|----|--------|---------|-------------------|------------|-------|
| USB2514B-I/M2 | C136518 | QFN-36 | 2 (+ 2 spare) | ~$2.50 | Order 4 — you'll want spares in case of soldering mistakes |
| STUSB4500QTR | C2678061 | QFN-24 | 1 (+ 1 spare) | ~$3.00 | Order 2 |
| AP2112K-3.3TRG1 | C51118 | SOT-23-5 | 1 (+ 2 spare) | ~$0.30 | Order 3 |
| USBLC6-2SC6 | C7519 | SOT-23-6 | 2 (+ 2 spare) | ~$0.25 | Only need 1-2 for testing, not all 9 |
| 24 MHz crystal (3215) | C32346 | 3215 SMD | 2 (+ 2 spare) | ~$0.20 | Solder next to USB2514B on adapter |

**LCSC order total: ~$15–20** (with spares and shipping)

> **Soldering QFN by hand:** You need flux paste, a fine-tip soldering iron (or hot air station), and a magnifier. QFN-36 at 0.5mm pitch is doable by hand but challenging. Search YouTube: `"hand solder QFN"` — drag soldering technique works. If you have a hot air rework station, that's even better. Practice on a spare adapter board first.

---

## Breadboard Connectors to Buy

| Product | Qty | Price | Source | Search |
|---------|-----|-------|--------|--------|
| **USB-C female breakout (DIP)** | 3 | ~$1 each | AliExpress | `"USB Type-C female breakout board DIP 2.54mm"` |
| **USB-A female breakout (DIP)** | 7 | ~$0.80 each | AliExpress | `"USB-A female breakout board DIP"` |
| **5-Pin DIN female connector** (PCB mount) | 4 | ~$1 each | AliExpress / Amazon | `"5 pin DIN female connector PCB mount"` — same ones as v2 BOM |
| **JST-XH 2-pin connectors** | 2 | ~$0.30 each | AliExpress | `"JST XH 2pin male PCB header"` — or just use bare wires for fans |

---

## Full Shopping List

### From LCSC.com (exact v2 BOM ICs)

| Item | LCSC # | Qty | Price |
|------|--------|-----|-------|
| USB2514B-I/M2 | C136518 | 4 | ~$10 |
| STUSB4500QTR | C2678061 | 2 | ~$6 |
| AP2112K-3.3TRG1 | C51118 | 3 | ~$1 |
| USBLC6-2SC6 | C7519 | 4 | ~$1 |
| 24 MHz crystal (3215) | C32346 | 4 | ~$1 |
| **LCSC subtotal** | | | **~$19 + $2 shipping** |

### From AliExpress (adapters + breakouts)

| Item | Qty | Price |
|------|-----|-------|
| SMD to DIP adapter kit (QFN + SOT-23) | 1 kit | ~$10 |
| USB-C female breakout (DIP) | 3 | ~$3 |
| USB-A female breakout (DIP) | 7 | ~$6 |
| 5-Pin DIN female connectors | 4 | ~$4 |
| 2.54mm pin header strips | 5 | ~$1 |
| **AliExpress subtotal** | | **~$24** |

### From Amazon / Local Electronics Store (through-hole passives)

| Item | Qty | Price |
|------|-----|-------|
| 220Ω resistor 1/4W | 20 (pack) | ~$1 |
| 1kΩ resistor 1/4W | 20 (pack) | ~$1 |
| 1.5kΩ resistor 1/4W | 10 (pack) | ~$1 |
| 5.1kΩ resistor 1/4W | 10 (pack) | ~$1 |
| 10kΩ resistor 1/4W | 10 (pack) | ~$1 |
| 100nF ceramic cap (through-hole) | 20 (pack) | ~$1 |
| 10µF electrolytic cap | 10 (pack) | ~$1 |
| 18pF ceramic cap (through-hole) | 10 (pack) | ~$1 |
| 4.7µF ceramic/electrolytic | 5 | ~$1 |
| 100µF electrolytic cap | 5 | ~$1 |
| 1N5822 Schottky diode (through-hole) | 5 | ~$1 |
| 500mA polyfuse (radial through-hole) | 10 | ~$2 |
| 5mm LEDs (green, blue, yellow assorted) | 10 | ~$1 |
| Full-size breadboard (830 pts) | 2 | ~$10 |
| Jumper wire kit (M-M, M-F) | 1 | ~$5 |
| **Local subtotal** | | **~$29** |

### From Pi Reseller (compute)

| Item | Qty | Price |
|------|-----|-------|
| Raspberry Pi CM4 (2GB, WiFi, Lite) | 1 | ~$35 |
| CM4 IO Board (official Raspberry Pi) | 1 | ~$35 |
| **Pi subtotal** | | **~$70** |

### Tools You Need

| Tool | Price | Notes |
|------|-------|-------|
| Fine-tip soldering iron (or station) | ~$30+ | You probably have one from v1 |
| Solder flux paste (no-clean) | ~$5 | **Essential** for QFN soldering |
| Solder wick / desoldering braid | ~$3 | For fixing bridges |
| Magnifying glass / loupe (10×) | ~$5 | Inspect QFN solder joints |
| USB-C power meter (WITRN C5) | ~$20 | Test PD negotiation + monitor voltage/current |
| Multimeter | — | You have one |
| **Tools subtotal** | **~$33** (if you have soldering iron already: ~$3) |

---

### Total Cost

| Category | Cost |
|----------|------|
| LCSC ICs (same parts as v2) | ~$21 |
| AliExpress adapters + breakouts | ~$24 |
| Through-hole passives + breadboard | ~$29 |
| CM4 + IO Board | ~$70 |
| Tools (flux, wick, power meter) | ~$28 |
| **Total** | **~$172** |

> **Note:** The CM4 + IO Board ($70) is not wasted money — the CM4 goes into your final v2 PCB, and the IO Board stays as a permanent debug tool. So the actual "testing overhead" cost is ~$102.

---

## Assembly: Solder ICs onto Adapter Boards

### USB2514B on QFN-36 Adapter (×2)

```
    QFN-36 Adapter Board (top view)
    ┌──────────────────────────────────────┐
    │                                      │
    │  Solder USB2514B (QFN-36) here       │
    │  ┌────────────┐                      │
    │  │ ■■■■■■■■■ │  Also solder nearby: │
    │  │ ■        ■ │  - Y1 (24 MHz xtal) │
    │  │ ■        ■ │  - 2× 18pF caps     │
    │  │ ■■■■■■■■■ │    (CY1a, CY1b)     │
    │  └────────────┘                      │
    │                                      │
    │  ▌▌▌▌▌▌▌▌▌  ← DIP pins (left)      │
    │  ▌▌▌▌▌▌▌▌▌  ← DIP pins (right)     │
    └──────────────────────────────────────┘
```

**Why solder the crystal on the adapter too:** The crystal and its load caps must be physically close (<10mm) to the IC. You can't run them through long breadboard jumper wires — the parasitic capacitance will prevent the oscillator from starting. Solder Y1 + 18pF caps directly on the adapter board, next to the USB2514B.

**QFN soldering steps:**
1. Apply flux paste to the adapter pads
2. Tin one corner pad with a small solder blob
3. Align the IC — tack one corner
4. Check alignment under magnifier
5. Drag-solder remaining pins (or use hot air)
6. Check for bridges with magnifier
7. Remove bridges with solder wick
8. Solder crystal and load caps on nearby pads
9. Solder 2.54mm pin headers on the DIP pads
10. Plug into breadboard

### STUSB4500 on QFN-24 Adapter (×1)

Same process as above, but QFN-24. No crystal needed — just the IC itself.

### AP2112K on SOT-23-5 Adapter (×1)

SOT-23 is much easier to solder than QFN — big pads, visible pins. Straightforward.

### USBLC6 on SOT-23-6 Adapter (×2)

Same as AP2112K — easy SOT-23 soldering. You only need 1-2 for breadboard testing (one on the upstream USB, one on a downstream port). The other 7 can be skipped for prototype.

---

## Breadboard Wiring (Exact v2 Circuit)

### Power Input Section

```
    USB-C breakout #1 (J3 — PD power input)
    ┌────────────┐
    │ VBUS ──────┼──→ STUSB4500 adapter VBUS_EN_SNK pin
    │ CC1 ───────┼──→ 5.1kΩ → GND  AND  STUSB4500 CC1 pin
    │ CC2 ───────┼──→ 5.1kΩ → GND  AND  STUSB4500 CC2 pin
    │ GND ───────┼──→ GND rail
    └────────────┘

    STUSB4500 adapter board (plugged into breadboard)
    ┌────────────────┐
    │ VBUS_EN_SNK ───┼──← USB-C VBUS
    │ CC1 ───────────┼──← USB-C CC1
    │ CC2 ───────────┼──← USB-C CC2
    │ VDD ───────────┼──← 3.3V rail (from LDO)
    │ ADDR ──────────┼──→ 10kΩ → GND
    │ SCL ───────────┼──→ CM4 GPIO 3 (I2C SCL) via IO Board
    │ SDA ───────────┼──→ CM4 GPIO 2 (I2C SDA) via IO Board
    │ POWER_OK ──────┼──→ 1kΩ → green LED → GND (PD status)
    │ GND ───────────┼──→ GND rail
    └────────────────┘

    STUSB4500 VBUS output → 1N5822 anode → cathode → VBUS_5V rail
                                                       │
                                                    100µF cap → GND

    VBUS_5V rail → AP2112K adapter IN → OUT → V3V3 rail
                                          │
                                       10µF cap → GND
```

### USB Hub Section

```
    CM4 IO Board USB-A port
    ──→ cut USB cable ──→ wires:
         red   (5V)  → not needed (hub powered from VBUS_5V rail)
         white (D-)  → USBLC6 adapter IO1 → USB2514B adapter #1 USBDM pin
         green (D+)  → USBLC6 adapter IO2 → USB2514B adapter #1 USBDP pin
         black (GND) → GND rail

    USB2514B Adapter #1 (root hub, plugged into breadboard)
    ┌────────────────────┐
    │ VDD33 ─────────────┼──← V3V3 rail + 100nF cap → GND
    │ VDDA33 ────────────┼──← V3V3 rail + 100nF cap → GND
    │ CRFILT ────────────┼──→ 10nF cap → GND
    │ USBDP ─────────────┼──← CM4 USB D+ (via USBLC6)
    │ USBDM ─────────────┼──← CM4 USB D- (via USBLC6)
    │ RESET_N ───────────┼──→ 10kΩ → V3V3
    │ CFG_SEL0 ──────────┼──→ GND (pin-strap mode)
    │ CFG_SEL1 ──────────┼──→ GND
    │ VBUS_DET ──────────┼──← VBUS_5V via 100kΩ/47kΩ divider
    │                    │
    │ DN1_DP ────────────┼──→ USB-A breakout #1 D+  (→ MIDI device 1)
    │ DN1_DM ────────────┼──→ USB-A breakout #1 D-
    │ DN2_DP ────────────┼──→ USB-A breakout #2 D+  (→ MIDI device 2)
    │ DN2_DM ────────────┼──→ USB-A breakout #2 D-
    │ DN3_DP ────────────┼──→ USB-A breakout #3 D+  (→ MIDI device 3)
    │ DN3_DM ────────────┼──→ USB-A breakout #3 D-
    │ DN4_DP ────────────┼──→ USB2514B adapter #2 USBDP (cascade)
    │ DN4_DM ────────────┼──→ USB2514B adapter #2 USBDM (cascade)
    │ GND ───────────────┼──→ GND rail
    └────────────────────┘

    USB2514B Adapter #2 (tier 2 hub, plugged into breadboard)
    ┌────────────────────┐
    │ (same power/config │
    │  wiring as #1)     │
    │                    │
    │ USBDP ─────────────┼──← Hub #1 DN4_DP (cascade)
    │ USBDM ─────────────┼──← Hub #1 DN4_DM
    │                    │
    │ DN1_DP ────────────┼──→ USB-A breakout #4 D+  (→ MIDI device 4)
    │ DN1_DM ────────────┼──→ USB-A breakout #4 D-
    │ DN2_DP ────────────┼──→ USB-A breakout #5 D+  (→ MIDI device 5)
    │ DN2_DM ────────────┼──→ USB-A breakout #5 D-
    │ DN3_DP ────────────┼──→ USB-A breakout #6 D+  (→ MIDI device 6)
    │ DN3_DM ────────────┼──→ USB-A breakout #6 D-
    │ DN4_DP ────────────┼──→ USB-A breakout #7 D+  (→ spare)
    │ DN4_DM ────────────┼──→ USB-A breakout #7 D-
    │ GND ───────────────┼──→ GND rail
    └────────────────────┘

    Each USB-A breakout:
    VBUS → VBUS_5V rail via 500mA polyfuse
    D+   → from hub DN port
    D-   → from hub DN port
    GND  → GND rail
```

### MIDI OUT Section

```
    MIDI OUT 1 (MS-20 Mini):
    VBUS_5V rail → 220Ω → DIN-5 (J5) Pin 4
    CM4 IO Board GPIO 14 (physical pin 8) → 220Ω → DIN-5 (J5) Pin 5
    DIN-5 (J5) Pin 2 → GND rail

    MIDI OUT 2 (Volca #1):
    VBUS_5V rail → 220Ω → DIN-5 (J6) Pin 4
    CM4 IO Board GPIO 4 (physical pin 7) → 220Ω → DIN-5 (J6) Pin 5
    DIN-5 (J6) Pin 2 → GND rail

    MIDI OUT 3 (Volca #2):
    VBUS_5V rail → 220Ω → DIN-5 (J7) Pin 4
    CM4 IO Board GPIO 8 (physical pin 24) → 220Ω → DIN-5 (J7) Pin 5
    DIN-5 (J7) Pin 2 → GND rail

    MIDI OUT 4 (Volca #3):
    VBUS_5V rail → 220Ω → DIN-5 (J8) Pin 4
    CM4 IO Board GPIO 12 (physical pin 32) → 220Ω → DIN-5 (J8) Pin 5
    DIN-5 (J8) Pin 2 → GND rail
```

### DAW Mode USB-C Section

```
    USB-C breakout #2 (J4 — DAW port)
    ┌────────────┐
    │ D+ ────────┼──→ CM4 IO Board USB OTG D+
    │ D- ────────┼──→ CM4 IO Board USB OTG D-
    │ CC1 ───────┼──→ 5.1kΩ → GND
    │ CC2 ───────┼──→ 5.1kΩ → GND
    │ VBUS ──────┼──→ not connected
    │ GND ───────┼──→ GND rail
    └────────────┘
```

### Status LEDs

```
    Power:          VBUS_5V → 1kΩ → green LED → GND
    PD status:      STUSB4500 POWER_OK → 1kΩ → blue LED → GND
    MIDI TX 1:      GPIO 14 line → 1kΩ → yellow LED → GND
    MIDI TX 2:      GPIO 4  line → 1kΩ → yellow LED → GND
    MIDI TX 3:      GPIO 8  line → 1kΩ → yellow LED → GND
    MIDI TX 4:      GPIO 12 line → 1kΩ → yellow LED → GND
```

---

## Physical Layout (3 Breadboards)

```
    ┌─ BREADBOARD 1: POWER ────────────────────────────────────────┐
    │                                                               │
    │  [USB-C brk]   [STUSB4500]   [1N5822]   [AP2112K]          │
    │   (J3, PD)      adapter      diode        adapter            │
    │                                                               │
    │  [100µF]  [10kΩ]  [5.1kΩ×2]  [100nF×2]  [10µF]  [LED grn] │
    │                                                               │
    │  VBUS_5V rail ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
    │  GND rail ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
    │  V3V3 rail ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
    └───────────────────────────────────────────────────────────────┘
          │ (bridge 5V, 3.3V, GND to BB2)
          ▼
    ┌─ BREADBOARD 2: USB HUB ──────────────────────────────────────┐
    │                                                               │
    │  [USB2514B #1]       [USB2514B #2]                           │
    │    adapter             adapter                                │
    │   (root hub)          (cascade)                               │
    │                                                               │
    │  [USBLC6]  [100nF×8]  [10µF×2]  [10kΩ×2]  [1.5kΩ×2]       │
    │                                                               │
    │  [USB-A brk1] [brk2] [brk3] [brk4] [brk5] [brk6] [brk7]   │
    │  + polyfuse    + pf   + pf   + pf   + pf   + pf   + pf      │
    │                                                               │
    │  [USB-C brk]  ← DAW port (J4) + 5.1kΩ×2                    │
    └───────────────────────────────────────────────────────────────┘
          │ (bridge 5V, GND to BB3)
          ▼
    ┌─ BREADBOARD 3: MIDI OUT + LEDS ──────────────────────────────┐
    │                                                               │
    │  [220Ω×2] → [DIN-5]   [220Ω×2] → [DIN-5]                   │
    │   MS-20 (J5)            Volca 1 (J6)                         │
    │                                                               │
    │  [220Ω×2] → [DIN-5]   [220Ω×2] → [DIN-5]                   │
    │   Volca 2 (J7)          Volca 3 (J8)                         │
    │                                                               │
    │  [1kΩ→LED] [1kΩ→LED] [1kΩ→LED] [1kΩ→LED]  ← MIDI TX LEDs  │
    │                                                               │
    │  [Fan header 1]  [Fan header 2]   ← 5V direct               │
    └───────────────────────────────────────────────────────────────┘

    CM4 IO Board (off-breadboard, on desk):
    ├── CM4 module plugged in
    ├── MicroSD inserted
    ├── DSI ribbon → 5" touchscreen
    ├── USB-A port → cut cable → BB2 hub upstream
    ├── GPIO 14 (pin 8)  → jumper wire → BB3 MIDI 1
    ├── GPIO 4  (pin 7)  → jumper wire → BB3 MIDI 2
    ├── GPIO 8  (pin 24) → jumper wire → BB3 MIDI 3
    ├── GPIO 12 (pin 32) → jumper wire → BB3 MIDI 4
    ├── GPIO 2  (pin 3)  → jumper wire → BB1 STUSB4500 SCL
    ├── GPIO 3  (pin 5)  → jumper wire → BB1 STUSB4500 SDA
    └── GND (pin 6)      → jumper wire → BB1 GND rail
```

---

## Important Warnings

### USB Signal Integrity on Breadboard

USB 2.0 data lines (D+/D-) are sensitive to capacitance and impedance. Breadboard wiring adds ~5–10pF per jumper wire. This matters:

| Scenario | Will It Work? | Why |
|----------|--------------|-----|
| Hub upstream (CM4 → Hub IC, short wire) | **Yes** | Short run, Full Speed (12 Mbps) tolerant |
| Hub downstream (Hub IC → USB-A, short wire) | **Yes** | MIDI devices are Full Speed |
| Long jumper wires (>15cm) | **Maybe not** | Excess capacitance can cause enumeration failures |
| Hub cascade (Hub #1 → Hub #2, breadboard wire) | **Likely yes** | Keep wires <5cm, use twisted pair if possible |

**Tips:**
- Keep USB D+/D- jumper wires **as short as possible** (< 10cm)
- Twist D+ and D- wires together (reduces noise pickup)
- If a device doesn't enumerate, try a shorter wire first
- MIDI devices are very low bandwidth — they're forgiving

### Crystal Oscillator

The 24 MHz crystal **must** be soldered onto the adapter board next to the IC, not wired via breadboard. Breadboard parasitics will prevent the oscillator from starting. This is the one component that cannot be on the breadboard.

### Power Rails

- Use **both** power rails on each breadboard (top and bottom)
- Bridge them together at both ends of each board
- Add 100nF + 10µF decoupling at every adapter board's power pins
- Run 5V and GND wires between breadboards using thick (22AWG) jumper wires

---

## Test Sequence

Same tests as [testing-plan.md](testing-plan.md), but now with exact v2 components:

| # | Test | Pass Criteria |
|---|------|---------------|
| 1 | Plug PD charger into USB-C breakout | STUSB4500 POWER_OK LED on, multimeter reads 4.7–5.0V on VBUS_5V |
| 2 | Check 3.3V rail | Multimeter reads 3.3V on V3V3 rail |
| 3 | Boot CM4 on IO Board (powered from VBUS_5V) | CM4 boots, WiFi works, SSH works |
| 4 | USB2514B #1 enumerates | `lsusb` shows Microchip USB hub |
| 5 | USB2514B #2 enumerates (cascade) | `lsusb` shows two Microchip USB hubs |
| 6 | Plug MIDI device into each USB-A breakout | All 6 show in `aconnect -l` |
| 7 | Send MIDI to each DIN-5 port | Synths respond (MS-20, 3× Volca) |
| 8 | DAW mode via USB-C breakout #2 | Mac sees Pi as MIDI device |
| 9 | Run full midi-box software | Web UI works, routing works, presets load |
| 10 | 1-hour stress test | No crashes, no USB disconnects, voltage stable |
| 11 | Measure total current | < 4A (matches power.md budget) |

**If all 11 tests pass → order the final v2 PCB with confidence.**
