# MIDI Box v2 — Complete Testing Plan

Test every v2 subsystem before ordering the final PCB. Three test methods combined:

- **Breadboard** — exact same ICs on QFN-to-DIP adapters + through-hole passives (same values). See [breadboard-prototype.md](breadboard-prototype.md) for full wiring guide.
- **Off-the-shelf boards** — CM4 IO Board, USB power meter, USB-C breakouts from AliExpress/Amazon
- **Custom breakout PCBs** — optional, order from JLCPCB if you want a cleaner test setup than bare adapters

---

## Risk Map: What Needs Testing

Since v1 already works, the **only unknowns** in v2 are:

| Subsystem | New in v2? | Risk | Why |
|-----------|-----------|------|-----|
| MIDI OUT circuits | No — same circuit | **None** | Already proven in v1 |
| USB MIDI devices | No — same devices | **None** | Already proven in v1 |
| Software | No — no changes | **None** | Already proven in v1 |
| CM4 as carrier module | **Yes** | **Medium** | Different form factor, Hirose connectors, need to verify GPIO/UART/USB routing |
| USB2514B hub IC | **Yes** | **Medium** | New IC, pin-strap config, crystal, cascade wiring |
| STUSB4500 USB-PD | **Yes** | **Low** | Commodity IC, well-documented, but NVM programming is new |
| USB-C connectors | **Yes** | **Low** | CC resistor values, footprint correctness |
| Power distribution | **Partly** | **Low** | Same budget as v1, just different delivery (PD vs barrel) |
| 4-layer PCB routing | **Yes** | **Low** | USB impedance, DSI — handled by fab house |

**Testing priority: CM4 carrier > USB hub > USB-PD > everything else.**

---

## Test Strategy Per Subsystem

### 1. CM4 Carrier — Buy Off-the-Shelf CM4 IO Board

**Don't build this yourself.** The official Raspberry Pi CM4 IO Board ($35) is the gold standard carrier. Buy one, plug in your CM4, and verify everything works before designing your own carrier.

**What to buy:**

| Product | Price | Where | Search Term |
|---------|-------|-------|-------------|
| **Raspberry Pi CM4 IO Board** (official) | ~$35 | Amazon / Pimoroni / The Pi Hut | `"CM4 IO Board"` |
| **Raspberry Pi CM4** (2GB WiFi, Lite) | ~$35 | Same resellers | `"CM4 Lite 2GB WiFi"` |
| MicroSD card (for CM4 Lite) | ~$8 | Amazon | You have one already |

**What this tests:**

| Test | How | Expected Result |
|------|-----|-----------------|
| CM4 boots from MicroSD | Flash same Pi OS image as your Pi 4 | Boots, WiFi works |
| GPIO UARTs work | Enable UART overlays, connect MIDI OUT circuit | Same as Pi 4 — `/dev/ttyAMA0,2,3,4` |
| USB host works | Plug USB MIDI device into IO board USB | Shows in `lsusb` and `aconnect -l` |
| USB gadget works | Connect IO board USB-C to Mac | Pi appears as MIDI device |
| DSI works | Connect 5" touchscreen to IO board DSI | Display works |
| Full software works | Run `python3 src/main.py` | Web UI loads, routing works |
| I2C works | `i2cdetect -y 1` | Bus functional (for STUSB4500 later) |

`★ Insight ─────────────────────────────────────`
**Why this is the most important test:** If your software runs identically on the CM4 IO Board as it does on the Pi 4, then CM4 compatibility is validated. Everything else (USB hub, PD, MIDI) are just peripheral circuits wired to the same GPIO/USB pins. The CM4 IO Board proves that the CM4 module itself works for your use case — and it costs less than one failed PCB revision.
`─────────────────────────────────────────────────`

> **Keep the CM4 IO Board permanently.** Even after your v2 PCB works, it's invaluable for debugging — if something breaks on v2, swap the CM4 to the IO Board to isolate whether it's a CM4 issue or a carrier board issue.

---

### 2. USB Hub (USB2514B) — Off-the-Shelf + Custom Breakout

**Phase A: Off-the-shelf USB2514B board (validate IC works)**

| Product | Price | Where | Search Term |
|---------|-------|-------|-------------|
| **USB2514B evaluation/breakout board** | ~$5–10 | AliExpress | `"USB2514B module"` or `"USB2514 hub board"` |
| **Generic 7-port USB 2.0 hub board** (bare PCB) | ~$3–5 | AliExpress | `"USB 2.0 7 port hub module PCB"` or `"FE1.1s 7 port hub"` |

> Many cheap AliExpress hub boards use GL850G or FE1.1s instead of USB2514B. That's fine for Phase A — you're testing whether the Pi can handle 7 downstream ports and 6 MIDI devices simultaneously. If you can find a USB2514B-based board, even better.

**Test with off-the-shelf board:**

| Test | How | Expected Result |
|------|-----|-----------------|
| Hub enumerates | Plug hub into CM4 IO Board USB | `lsusb` shows hub + all devices |
| 6 MIDI devices work | Plug all 6 USB MIDI devices | All show in `aconnect -l` |
| Simultaneous routing | Route KeyLab → 3 destinations | No dropped notes, no latency increase |
| Sustained load | Run for 1 hour with active routing | No USB disconnects |

**Phase B: Custom breakout PCB (validate YOUR circuit)**

Only do this if you want to test the exact USB2514B pin-strap configuration and crystal circuit from your v2 design. See [breakout-boards.md](breakout-boards.md) Board 1.

Order from JLCPCB: ~$10 for 5 boards with SMT assembly. Plug into breadboard, wire to CM4 IO Board USB port.

**Test with custom breakout:**

| Test | How | Expected Result |
|------|-----|-----------------|
| IC enumerates with pin-strap config | Plug into CM4 USB | Shows as hub in `lsusb` (VID/PID = Microchip) |
| All 4 downstream ports work | Plug USB device into each port | All 4 enumerate |
| Cascade works | Wire Board 1a DN4 → Board 1b upstream | 7 total ports visible |
| Self-powered mode correct | Check `lsusb -v` output | `Self Powered: yes` |

---

### 3. USB-PD Power (STUSB4500) — Buy SparkFun Board

**Don't make a breakout for this. SparkFun already sells one.**

| Product | Price | Where | Search Term |
|---------|-------|-------|-------------|
| **SparkFun STUSB4500 Breakout** (DEV-15801) | ~$12 | Amazon / SparkFun | `"SparkFun STUSB4500"` or `"STUSB4500 breakout"` |
| **Generic STUSB4500 module** | ~$5–8 | AliExpress | `"STUSB4500 PD sink module"` or `"USB-C PD trigger STUSB4500"` |
| **WITRN USB-C PD trigger board** | ~$5 | AliExpress | `"USB-C PD trigger board 5V"` — various ICs, some use STUSB4500 |

The SparkFun board is pin-for-pin what you need: STUSB4500 + USB-C connector + CC resistors + header pins. It even has a Qwiic I2C connector for easy NVM programming.

**Test with SparkFun board:**

| Test | How | Expected Result |
|------|-----|-----------------|
| PD negotiation works | Plug any USB-C PD charger | POWER_OK LED on, VBUS outputs 5V |
| 5V @ 3A delivery | Connect to CM4 IO Board + USB hub + MIDI | Stable 5V under full load |
| NVM programming | Use `pystusb4500` Python lib over I2C from Pi | Set PDO1 = 5V/3A, verify with `i2cget` |
| Fallback (non-PD charger) | Plug non-PD USB-C charger | Still outputs 5V (at lower current) |
| Measure voltage drop | Multimeter on VBUS output under load | 4.7V–5.1V |

**NVM programming test (run on Pi/CM4):**

```bash
pip install pystusb4500
python3 -c "
from stusb4500 import STUSB4500
pd = STUSB4500(bus=1)
pd.set_pdo(1, voltage=5.0, current=3.0)
pd.write_nvm()
print('NVM programmed: 5V @ 3A')
print(pd.read_pdo(1))
"
```

`★ Insight ─────────────────────────────────────`
**Why buy instead of build for PD:** The STUSB4500 circuit is simple (IC + 3 resistors + 2 caps + USB-C connector), but the USB-C connector footprint is fiddly and the QFN-24 package is hard to hand-solder. SparkFun's $12 board saves you a custom breakout PCB run AND lets you test NVM programming immediately. Once validated, you copy the exact same circuit to your v2 PCB — the IC doesn't care what board it's on.
`─────────────────────────────────────────────────`

---

### 4. USB-C Connectors (DAW Mode) — Breadboard Test

The DAW mode USB-C port just needs D+, D-, CC1, CC2, and GND. Test with a cheap USB-C breakout.

| Product | Price | Where | Search Term |
|---------|-------|-------|-------------|
| **USB-C female breakout board** (DIP) | ~$1–2 | AliExpress / Amazon | `"USB Type-C female breakout board DIP"` |

These are tiny boards with a USB-C receptacle broken out to 2.54mm pins. Perfect for breadboard.

**Breadboard wiring:**

```
USB-C breakout:
    CC1 → 5.1kΩ → GND    (breadboard resistor)
    CC2 → 5.1kΩ → GND    (breadboard resistor)
    D+  → CM4 IO Board USB OTG D+  (or Pi 4 USB-C data pin)
    D-  → CM4 IO Board USB OTG D-
    GND → GND
    VBUS → not connected (Mac provides, we don't use it)
```

**Test:**

| Test | How | Expected Result |
|------|-----|-----------------|
| Mac detects USB device | Plug USB-C cable from breakout to Mac | Pi appears in System Information > USB |
| MIDI gadget works | Enable gadget mode, open Logic Pro | MIDI Box shows as MIDI interface |
| Bidirectional MIDI | Send note from Logic → Pi → hardware synth | Sound plays |

---

### 5. MIDI OUT Circuits — Breadboard (Already Done in v1)

You've already proven this circuit works. But test it one more time with the CM4 (on the IO Board) to confirm the UARTs are identical.

**Breadboard (same as v1):**

```
Per port:
    5V → 220Ω (through-hole) → DIN-5 Pin 4
    CM4 GPIO TX → 220Ω (through-hole) → DIN-5 Pin 5
    DIN-5 Pin 2 → GND
```

**Test: send MIDI from CM4 to each synth — should work identically to Pi 4.**

---

### 6. DSI Display — Direct Test on CM4 IO Board

The CM4 IO Board has a DSI connector. Just plug in your existing 5" touchscreen.

| Test | How | Expected Result |
|------|-----|-----------------|
| Display works | Connect DSI ribbon to IO Board | Screen displays desktop/kiosk |
| Touch works | Tap screen | Touch input registered |
| Kiosk mode | Boot with `midi-box-kiosk.service` | Shows `/display` page |

No breadboard or breakout needed — the IO Board tests this directly.

---

### 7. Power Distribution — Load Test on Breadboard

Test total system power draw with all components connected. Use the SparkFun STUSB4500 board as the power source.

```
    USB-C PD Charger (5V/3A+)
        │
    SparkFun STUSB4500 board → VBUS_OUT
        │
        ├──→ CM4 IO Board (5V in)
        ├──→ USB Hub board (5V in)
        ├──→ MIDI OUT circuits (5V in, via breadboard)
        └──→ Fans (5V in)

    Measure with USB power meter between charger and board.
```

| Test | How | Expected Result |
|------|-----|-----------------|
| Idle current | Pi booted, no MIDI activity | ~1.5–2.0A |
| Full load | 6 USB devices + 4 MIDI ports active + fans | ~3.0–3.6A |
| No brownout | Play MIDI intensively for 30 min | Voltage stays above 4.75V |
| Charger compatibility | Test with 3 different PD chargers | All work |

**Recommended USB power meter:**

| Product | Price | Where | Search Term |
|---------|-------|-------|-------------|
| **WITRN C5 / C4** USB-C power meter | ~$15–25 | AliExpress / Amazon | `"WITRN C5 USB-C power meter"` or `"USB-C PD tester"` |
| **ChargerLAB KM003C** | ~$40 | Amazon | Premium option, shows PD negotiation details |

`★ Insight ─────────────────────────────────────`
**A USB power meter is essential for this project.** It shows real-time voltage, current, and PD negotiation status. When you plug your PD charger into the STUSB4500, you can see exactly what voltage/current was negotiated. When testing under load, you can see if voltage drops below 4.75V (which would cause CM4 instability). It's $15 and you'll use it forever. Get the WITRN C5 — it decodes PD packets and shows them on screen.
`─────────────────────────────────────────────────`

---

## Complete Shopping List

### Off-the-Shelf Boards

| # | Product | Price | Source | Purpose |
|---|---------|-------|--------|---------|
| 1 | **Raspberry Pi CM4** (2GB, WiFi, Lite) | ~$35 | Pi reseller | The actual compute module for v2 |
| 2 | **Raspberry Pi CM4 IO Board** | ~$35 | Pi reseller / Amazon | Test CM4 carrier functions |
| 3 | **SparkFun STUSB4500 Breakout** | ~$12 | Amazon / SparkFun | Test USB-PD power input |
| 4 | **USB 2.0 hub module board** (7-port) | ~$5 | AliExpress | Test multi-port USB hub with MIDI devices |
| 5 | **USB-C female breakout** (DIP, 2.54mm) | ~$2 | AliExpress | Test DAW mode USB-C connector |
| 6 | **USB-A female breakout** (DIP) ×4 | ~$4 | AliExpress | Connect USB MIDI devices on breadboard |
| 7 | **WITRN C5 USB-C power meter** | ~$20 | AliExpress / Amazon | Measure voltage/current/PD status |
| | **Subtotal** | **~$113** | | |

### Breadboard Supplies

| # | Product | Qty | Price | Notes |
|---|---------|-----|-------|-------|
| 8 | Full-size breadboard (830 pts) | 2 | ~$10 | You may already have these |
| 9 | Jumper wire kit (M-M, M-F, F-F) | 1 | ~$5 | |
| 10 | 220Ω resistors (through-hole) | 8 | ~$0.50 | MIDI OUT circuits |
| 11 | 5.1kΩ resistors (through-hole) | 4 | ~$0.50 | USB-C CC pull-downs |
| 12 | 1kΩ resistors (through-hole) | 6 | ~$0.50 | LEDs |
| 13 | 5-Pin DIN connectors (PCB mount) | 4 | ~$4 | MIDI OUT — may already have from v1 |
| 14 | 5mm LEDs (assorted) | 6 | ~$1 | Status indicators |
| 15 | 100nF + 10µF capacitors (through-hole) | 10 | ~$1 | Decoupling |
| | **Subtotal** | | **~$22** | |

### Optional: Custom Breakout PCB (USB2514B)

Only if you want to validate your exact hub circuit before the final PCB.

| # | Product | Qty | Price | Notes |
|---|---------|-----|-------|-------|
| 16 | USB2514B breakout PCB (JLCPCB, 2-layer, SMT assembled) | 5 | ~$15 | Tests exact circuit from v2 schematic |
| 17 | 2.54mm pin headers (to solder on breakouts) | 4 | ~$1 | |
| | **Subtotal** | | **~$16** | |

---

### Total Cost Summary

| Path | Cost | What You Validate |
|------|------|-------------------|
| **Off-the-shelf boards only** | ~$135 | CM4 compatibility, PD power, USB hub capacity, DAW mode, full software |
| **+ breadboard MIDI circuits** | ~$157 | + MIDI OUT with CM4 UARTs (re-validates v1 circuit) |
| **+ custom USB2514B breakout** | ~$173 | + exact hub IC circuit from v2 design |

> **Recommendation:** Start with just the off-the-shelf boards ($135). That validates 90% of the design. Add the custom hub breakout only if you want extra confidence before the final PCB order.

---

## Testing Timeline

```
    WEEK 1 ─── Order everything
    │
    ├── Order CM4 + IO Board (Amazon / Pi reseller — 2-3 day shipping)
    ├── Order SparkFun STUSB4500 (Amazon — 2-3 day shipping)
    ├── Order USB-C power meter (Amazon — 2-3 day shipping)
    ├── Order AliExpress parts (hub board, breakouts, connectors — 7-14 day shipping)
    └── (Optional) Order USB2514B breakout PCB from JLCPCB (7-14 days)

    WEEK 2 ─── Test Phase 1 (CM4 + existing parts)
    │
    │   Amazon deliveries arrive (~day 3-4)
    │
    ├── Day 1: Flash MicroSD, boot CM4 on IO Board
    │          Verify: WiFi, SSH, GPIO, I2C, DSI touchscreen
    │
    ├── Day 1: Connect v1 Waveshare USB hubs to IO Board USB
    │          Verify: all 6 USB MIDI devices enumerate
    │
    ├── Day 1: Connect v1 MIDI OUT perfboard to CM4 GPIOs
    │          Verify: UART0/3/4/5 work identically to Pi 4
    │
    ├── Day 1: Run full midi-box software on CM4
    │          Verify: web UI, routing, presets, clock, everything
    │
    ├── Day 2: Test DAW mode (USB gadget) on CM4
    │          Connect IO Board USB-C to Mac
    │          Verify: gadget mode works on CM4
    │
    └── Day 2: Test STUSB4500 breakout (SparkFun)
               Program NVM for 5V/3A
               Power CM4 IO Board from STUSB4500 VBUS output
               Verify: stable 5V under load, measure with power meter

    ✅ CHECKPOINT: CM4 + PD power validated. If anything fails, debug here —
       don't proceed until this works.

    WEEK 3 ─── Test Phase 2 (New USB hub + breadboard)
    │
    │   AliExpress deliveries arrive (~day 10-14)
    │
    ├── Day 1: Wire breadboard MIDI OUT circuits
    │          Connect to CM4 IO Board GPIOs
    │          Verify: same results as perfboard (proves circuit, not just v1 board)
    │
    ├── Day 2: Connect off-the-shelf USB hub board to CM4
    │          Wire USB-A breakouts for each MIDI device
    │          Verify: all 6 devices work through hub board
    │
    ├── Day 2: Full integration test
    │          Power: STUSB4500 → CM4 IO Board
    │          USB: hub board → 6 MIDI devices
    │          MIDI: breadboard circuits → 4 DIN synths
    │          DAW: USB-C breakout → Mac
    │          Verify: everything works together, run for 1 hour
    │
    └── Day 3: Power stress test
               Measure total current draw with power meter
               Test with 3 different PD chargers
               Verify: no brownouts over 30 minutes

    ✅ CHECKPOINT: Full system validated with off-the-shelf parts.
       If the USB2514B breakout arrived, test it now.

    WEEK 3-4 ─── Test Phase 3 (Optional: custom USB2514B breakout)
    │
    │   JLCPCB breakout boards arrive (~day 10-14)
    │
    ├── Day 1: Solder pin headers on USB2514B breakout boards
    │          Plug into breadboard
    │          Wire: CM4 USB → Hub breakout 1 → Hub breakout 2 (cascade)
    │
    ├── Day 1: Verify hub enumerates
    │          Check `lsusb -v` — confirm VID/PID, self-powered, 4 ports per hub
    │
    ├── Day 2: Connect all 6 MIDI devices through custom hub breakouts
    │          Run full routing test
    │          Verify: identical behavior to off-the-shelf hub
    │
    └── Day 2: Run stress test — 1 hour continuous MIDI routing through custom hubs

    ✅ CHECKPOINT: Exact v2 hub circuit validated.

    WEEK 4-5 ─── Order Final v2 PCB
    │
    ├── Draw schematic in EasyEDA Pro (follow easyeda-guide.md)
    ├── Layout PCB
    ├── Run DRC/ERC
    ├── Order from JLCPCB (4-layer, SMT assembled)
    │
    └── Wait 10-14 days for delivery

    WEEK 6 ─── Final Assembly & Test
    │
    ├── Hand-solder through-hole connectors (DIN-5, USB-A, fan headers)
    ├── Plug in CM4
    ├── Power on — verify with USB power meter
    ├── Run full test sequence
    │
    └── ✅ DONE — v2 PCB validated and working
```

---

## Test-to-PCB Traceability

Every test maps directly to a v2 PCB subsystem. If a test passes, that subsystem is validated for the final board.

| Test Phase | What You Tested | v2 PCB Subsystem Validated | Confidence |
|------------|----------------|---------------------------|------------|
| CM4 on IO Board boots | CM4 + MicroSD + WiFi + GPIO | CM4 carrier circuit (schematics.md §1) | **High** |
| UART MIDI on CM4 | GPIO 14/4/8/12 UART TX | MIDI OUT (schematics.md §4) | **High** — same circuit as v1 |
| USB devices on CM4 | CM4 USB host + hub | USB hub upstream connection (schematics.md §2) | **High** |
| DSI on CM4 IO Board | DSI display passthrough | DSI connector (schematics.md §5) | **High** |
| USB gadget on CM4 | CM4 USB OTG → Mac | DAW mode USB-C (schematics.md §3) | **High** |
| STUSB4500 SparkFun board | PD negotiation, 5V output | USB-PD input (power.md) | **High** — same IC |
| Off-the-shelf USB hub | 7-port hub + 6 MIDI devices | Hub port count + software | **Medium** — different IC |
| Custom USB2514B breakout | Exact hub circuit | USB2514B cascade (schematics.md §2) | **Very high** — same circuit |
| Full integration on breadboard | All subsystems together | Power budget (power.md) | **High** |

**What's NOT tested until the final PCB:**
- Hirose DF40C connector footprint alignment (mechanical)
- USB trace impedance on 4-layer stackup (electrical)
- Component thermal performance with copper pours
- Physical board fits in enclosure

These are low-risk items. If all the above tests pass, the final PCB has a **very high** chance of working first try.

---

## Decision Tree: What If Something Fails?

```
    CM4 doesn't boot on IO Board?
    └── Check MicroSD image, try re-flash
    └── Try different CM4 module
    └── This is a CM4 hardware issue, not your design

    UARTs don't work on CM4?
    └── Check /boot/firmware/config.txt overlays
    └── CM4 uses same UART silicon as Pi 4 — should be identical
    └── If different: update device tree overlays (software fix)

    USB hub doesn't enumerate all devices?
    └── Power issue — add more bulk capacitance, use stronger supply
    └── Some MIDI devices are picky about hub latency — try different port order
    └── If USB2514B breakout fails but off-the-shelf hub works:
        your schematic has a wiring error — review pin-strap config

    STUSB4500 doesn't negotiate PD?
    └── NVM not programmed — re-program via I2C
    └── Charger doesn't support 5V PDO — try different charger
    └── CC resistors wrong — should be 5.1kΩ to GND

    System browns out under load?
    └── PD charger can't deliver enough current — use 5V/5A charger
    └── Cable too thin — use USB-C cable rated for 3A+
    └── Add more bulk capacitance (bigger electrolytic on 5V rail)

    DAW mode (USB gadget) doesn't work on CM4?
    └── IO Board USB-C port may default to host mode — check DIP switch
    └── CM4 USB OTG needs device tree config — check docs
    └── This is the one area where CM4 differs from Pi 4 — test carefully
```
