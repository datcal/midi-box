# MIDI Box v2 — SMD Breakout Boards for Breadboard Testing

Instead of buying generic off-the-shelf modules, design **small breakout PCBs** for each SMD IC. Solder the SMD parts on the breakout, bring pins out to 2.54mm headers, plug into breadboard.

This gives you **exact same circuits as the final v2 PCB** — just split across small boards connected by jumper wires.

---

## Why Custom Breakout PCBs

- You test the **exact same ICs** (USB2514B, STUSB4500) that go on the final board
- Catches datasheet wiring mistakes early (wrong pin, missing cap)
- Breakout PCBs are **tiny and cheap** — $2 for 5 boards at JLCPCB, 2-layer is fine
- You practice SMD soldering on small boards before committing to the big one
- Reusable — keep them as test fixtures even after the v2 PCB works

`★ Insight ─────────────────────────────────────`
**This is standard practice in hardware engineering.** Companies like Adafruit and SparkFun literally sell breakout boards for this exact reason — the STUSB4500 breakout from SparkFun is $12. But you can make your own in EasyEDA for $2 in quantity 5, with the exact same circuit you designed. If it works on the breakout, it works on the final PCB — the IC doesn't know what board it's on.
`─────────────────────────────────────────────────`

---

## Breakout Board Designs (4 boards)

### Board 1: USB Hub Breakout (USB2514B)

**Size:** ~30mm × 40mm, 2-layer

**SMD components ON the breakout:**
- 1× USB2514B-I/M2 (QFN-36) — `C136518`
- 1× 24 MHz crystal — `C32346`
- 2× 18pF cap (0402) — `C1808`
- 4× 100nF cap (0402) — `C1525`
- 1× 10µF cap (0805) — `C19702`
- 1× 1.5kΩ resistor (0402) — `C4026`

**Pin headers OUT (2.54mm, breadboard-compatible):**

```
    Left side (1×10 header):         Right side (1×10 header):
    ┌────────────────────┐
    │ USBUP_D+     DN1_D+ │
    │ USBUP_D-     DN1_D- │
    │ VDD (5V)     DN2_D+ │
    │ GND          DN2_D- │
    │ RESET_N      DN3_D+ │
    │ CFG_SEL0     DN3_D- │
    │ CFG_SEL1     DN4_D+ │
    │ VBUS_DET     DN4_D- │
    │ 3.3V IN      GND    │
    │ GND          GND    │
    └────────────────────┘
```

**Make 2 of these** — one for IC1 (root hub), one for IC2 (cascaded). On the breadboard, wire IC1 DN4 → IC2 upstream to cascade them.

**EasyEDA steps:**
1. New project: `usb-hub-breakout`
2. Place USB2514B (`C136518`), crystal, caps, resistor
3. Wire exactly as in [schematics.md](schematics.md) Section 2
4. Add 2× 1×10 male pin headers (search `C124378` — 1×10 2.54mm)
5. Route on 2-layer, no impedance control needed (traces are <15mm)
6. Board outline: 30×40mm

**JLCPCB order:**
- 2-layer, 5 pcs, 1.6mm, HASL — ~$2
- SMT assembly for SMD parts — ~$8
- Total: ~$10 for 5 boards (you need 2)

---

### Board 2: USB-PD Breakout (STUSB4500)

**Size:** ~20mm × 25mm, 2-layer

**SMD components ON the breakout:**
- 1× STUSB4500QTR (QFN-24) — `C2678061`
- 2× 5.1kΩ resistor (0402) — `C25905` (CC pull-downs)
- 1× 10kΩ resistor (0402) — `C25744` (ADDR)
- 1× 4.7µF cap (0805) — `C1779`
- 1× 100nF cap (0402) — `C1525`

**Connectors ON the breakout:**
- 1× USB-C 16-pin receptacle — `C2765186` (solder directly on breakout)

**Pin headers OUT:**

```
    1×6 header:
    ┌──────────┐
    │ VBUS_OUT │ → 5V from PD charger (after negotiation)
    │ GND      │
    │ POWER_OK │ → HIGH when PD contract established
    │ SCL      │ → I2C clock (for NVM programming)
    │ SDA      │ → I2C data
    │ 3.3V IN  │ → supply for STUSB4500 logic
    └──────────┘
```

**On breadboard:**
- Plug header into breadboard
- VBUS_OUT → 5V power rail
- Connect SCL/SDA to Pi GPIO 2/3 (for one-time NVM programming)
- 3.3V IN from AMS1117 module or another source

**EasyEDA steps:**
1. New project: `usb-pd-breakout`
2. Place STUSB4500 (`C2678061`), USB-C connector (`C2765186`), resistors, caps
3. Wire as in [power.md](power.md) STUSB4500 circuit section
4. Add 1×6 male pin header
5. Board outline: 20×25mm

---

### Board 3: USB-C Gadget Port Breakout (DAW Mode)

**Size:** ~15mm × 20mm, 2-layer

This one is super simple — just a USB-C connector with CC resistors, broken out to pins.

**SMD components ON the breakout:**
- 2× 5.1kΩ resistor (0402) — `C25905`

**Connectors ON the breakout:**
- 1× USB-C 16-pin receptacle — `C2765186`

**Pin headers OUT:**

```
    1×4 header:
    ┌──────┐
    │ D+   │ → to Pi USB OTG / CM4 gadget port
    │ D-   │
    │ VBUS │ → sense only (from Mac)
    │ GND  │
    └──────┘
```

**On breadboard:**
- Not actually needed for breadboard — just connect a USB-C cable from Pi to Mac
- But useful to validate the USB-C connector footprint and CC resistor values

---

### Board 4: MIDI OUT Breakout (×1, simple)

**Size:** ~25mm × 35mm, 2-layer

Optional — you could just do this on the breadboard with through-hole parts. But if you want to validate the exact SMD layout:

**SMD components ON the breakout:**
- 2× 220Ω resistor (0805) — `C17557`
- 1× yellow LED (0805) — `C2296` (optional)
- 1× 1kΩ resistor (0402) — `C11702` (optional, for LED)

**Connectors ON the breakout:**
- 1× DIN-5 female (through-hole) — hand solder

**Pin headers OUT:**

```
    1×3 header:
    ┌───────┐
    │ 5V    │ → power rail
    │ TX    │ → Pi GPIO UART TX
    │ GND   │ → ground
    └───────┘
```

**Make 4 of these** for all 4 MIDI ports — or just 1 and test each UART sequentially.

---

## Complete Breakout → Breadboard Wiring

```
    ┌───────────────────────────────────────────────────────────┐
    │                     BREADBOARD                            │
    │  [+5V rail] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
    │  [GND rail] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
    │                                                           │
    │  ┌──────────┐                                             │
    │  │ PD Board │ VBUS_OUT ──→ 5V rail                       │
    │  │ (Board 2)│ GND ──→ GND rail                           │
    │  │ USB-C IN │ 3.3V IN ←── AMS1117 out                    │
    │  └──────────┘                                             │
    │       │ (or skip PD board, use 5V bench supply directly)  │
    │                                                           │
    │  ┌──────────────┐  ┌──────────────┐                      │
    │  │ Hub Board #1 │  │ Hub Board #2 │                      │
    │  │  (Board 1a)  │  │  (Board 1b)  │                      │
    │  │              │  │              │                        │
    │  │ USBUP_D+/D- │  │ USBUP_D+/D- │                       │
    │  │  ↑ from Pi   │  │  ↑ from Hub1 │                      │
    │  │  USB port    │  │    DN4       │                       │
    │  │              │  │              │                        │
    │  │ DN1 ──→ USB-A breakout ──→ MIDI device 1              │
    │  │ DN2 ──→ USB-A breakout ──→ MIDI device 2              │
    │  │ DN3 ──→ USB-A breakout ──→ MIDI device 3              │
    │  │ DN4 ──→ Hub Board #2 upstream                         │
    │  │              │  │ DN1 ──→ USB-A breakout ──→ device 4 │
    │  └──────────────┘  │ DN2 ──→ USB-A breakout ──→ device 5 │
    │                     │ DN3 ──→ USB-A breakout ──→ device 6 │
    │                     │ DN4 ──→ USB-A breakout ──→ spare    │
    │                     └──────────────┘                      │
    │                                                           │
    │  MIDI OUT ports (Board 4 ×4, or through-hole on BB):     │
    │  ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐                │
    │  │MIDI 1 │ │MIDI 2 │ │MIDI 3 │ │MIDI 4 │                │
    │  │5V←rail│ │5V←rail│ │5V←rail│ │5V←rail│                │
    │  │TX←GP14│ │TX←GP4 │ │TX←GP8 │ │TX←GP12│                │
    │  │GND←rl │ │GND←rl │ │GND←rl │ │GND←rl │                │
    │  │[DIN5] │ │[DIN5] │ │[DIN5] │ │[DIN5] │                │
    │  └───────┘ └───────┘ └───────┘ └───────┘                │
    │                                                           │
    │  [+5V rail] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
    │  [GND rail] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
    └───────────────────────────────────────────────────────────┘

    Raspberry Pi 4 (off breadboard):
    ├── USB-A port → cut cable → Hub Board #1 upstream (D+, D-, 5V, GND)
    ├── GPIO 14 (pin 8)  → jumper → MIDI 1 TX
    ├── GPIO 4  (pin 7)  → jumper → MIDI 2 TX
    ├── GPIO 8  (pin 24) → jumper → MIDI 3 TX
    ├── GPIO 12 (pin 32) → jumper → MIDI 4 TX
    ├── 5V (pin 2) → jumper → 5V rail (if not using PD board)
    └── GND (pin 6) → jumper → GND rail
```

---

## Order Summary for Breakout Boards

Order all breakout PCBs in one JLCPCB order to save on shipping:

| Board | Qty to Order | 2-Layer PCB Cost | SMT Assembly | Components |
|-------|-------------|------------------|--------------|------------|
| USB Hub Breakout | 5 pcs (need 2) | ~$2 | ~$8 | ~$5 |
| USB-PD Breakout | 5 pcs (need 1) | ~$2 | ~$5 | ~$4 |
| USB-C DAW Breakout | 5 pcs (need 1) | ~$2 | ~$3 | ~$1 |
| MIDI OUT Breakout | 5 pcs (need 1–4) | ~$2 | ~$3 | ~$2 |
| **Total** | | **~$8** | **~$19** | **~$12** |

**Grand total: ~$39 + shipping (~$8) ≈ $47**

Plus breadboard + jumper wires + through-hole parts: ~$20

**Full breadboard prototype cost: ~$65–70**

---

## Build Order

| Phase | What to Do | Time |
|-------|-----------|------|
| 1 | Design 4 breakout boards in EasyEDA (simple, 2-layer each) | 2–3 hours |
| 2 | Order from JLCPCB (SMT assembled) | 5 min + 7–14 day wait |
| 3 | Hand-solder pin headers + DIN-5 on breakouts | 30 min |
| 4 | Wire up breadboard | 1 hour |
| 5 | Boot Pi, run software, test all subsystems | 1–2 hours |
| 6 | Fix any issues, iterate | varies |
| 7 | **Green light → order the full v2 PCB** | |

---

## What This Validates That Off-the-Shelf Boards Don't

| Validation | Off-the-shelf module | Custom breakout |
|------------|---------------------|-----------------|
| USB2514B pin-strap config works | N/A (different IC) | **Yes — same IC, same config** |
| STUSB4500 negotiates 5V PD | Maybe (SparkFun board) | **Yes — same IC, your NVM config** |
| USB-C CC resistor values correct | No | **Yes** |
| Crystal + load cap values correct | No | **Yes** |
| Decoupling cap placement sufficient | No | **Yes** |
| Your schematic has no wiring errors | **No** | **Yes — this is the main win** |

`★ Insight ─────────────────────────────────────`
**The real value of custom breakouts:** You're not just testing whether "a USB hub works" — you're testing whether **your specific USB2514B circuit, with your specific pin-strap configuration, your specific crystal, and your specific decoupling layout** works. If the breakout works, you can copy-paste that exact sub-circuit into the v2 PCB with near-certainty. If you used a generic module, you'd still have uncertainty about your own design.

**Bonus: soldering practice.** QFN-36 (USB2514B) is the hardest package in this design. If you can solder it successfully on a small breakout board, you'll have confidence in the full PCB assembly. Or if JLCPCB assembles it for you — you've validated their assembly quality on a cheap board before trusting them with the expensive one.
`─────────────────────────────────────────────────`
