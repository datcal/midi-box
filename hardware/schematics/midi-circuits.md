# MIDI I/O Circuit Schematics

## MIDI Electrical Specification

- MIDI uses **31250 baud** serial, 8-N-1
- Current loop: 5mA through optocoupler in receiving device
- All 4 DIN ports are **MIDI OUT only** — no MIDI IN circuits needed
- Pi native hardware UARTs drive the circuits directly (no SC16IS752 bridge chips)

---

## MIDI OUT Circuit (Active Drive)

One circuit per port × 4. Pi GPIO TX pin drives it directly at 3.3V logic — no level shifter needed.

```
                         +5V
                          │
                     ┌────┴────┐
                     │  220 ohm │
                     └────┬────┘
                          │
                          ├──────────── DIN Pin 4 (Source)
                          │
    UART TX ─────┬────────┘
    (3.3V GPIO)  │
            ┌────┴────┐
            │  220 ohm │
            └────┬────┘
                 │
                 └───────────────── DIN Pin 5 (Sink)


    DIN Pin 2 ──── Shield / Ground (optional, connected to cable shield)
    DIN Pin 1, 3 ── Not connected
```

### How it works:
- When TX is HIGH (idle): no current flows
- When TX is LOW (data): current flows 5V → 220Ω → DIN pin 4 → receiver optocoupler → DIN pin 5 → 220Ω → TX (LOW = GND)
- ~8.6mA loop at 5V: (5V - 1.2V drop) / (220 + 220) — within MIDI spec

### 3.3V GPIO note:
Pi GPIO outputs 3.3V when HIGH. Since the circuit's current only flows when TX is LOW (sinking to GND), the idle-high voltage level doesn't affect MIDI signal integrity.

---

## Pi UART → MIDI OUT Wiring

```
                        ┌─────────────────────┐
                        │    Raspberry Pi 4   │
                        │                     │
                        │ GPIO 14 (UART0 TX) ─┼──── MIDI OUT → MS-20 Mini
                        │ GPIO 4  (UART3 TX) ─┼──── MIDI OUT → Volca #1
                        │ GPIO 8  (UART4 TX) ─┼──── MIDI OUT → Volca #2
                        │ GPIO 12 (UART5 TX) ─┼──── MIDI OUT → Volca #3
                        │                     │
                        │ GPIO 2  (SDA) ──────┼──── I2C Bus (touchscreen touch)
                        │ GPIO 3  (SCL) ──────┼──── I2C Bus
                        │                     │
                        │ GPIO 2/4 (5V) ──────┼──── Buck converter 5V in
                        │ GPIO 6   (GND) ─────┼──── Buck converter GND
                        │                     │
                        │ DSI connector ──────┼──── 7" Touchscreen ribbon
                        └─────────────────────┘
```

Required in `/boot/firmware/config.txt`:
```
dtoverlay=disable-bt    # frees UART0 (GPIO 14) from Bluetooth
dtoverlay=uart3         # GPIO 4  TX
dtoverlay=uart4         # GPIO 8  TX
dtoverlay=uart5         # GPIO 12 TX
```

Device nodes (pyserial):
```
/dev/ttyAMA0  →  MS-20 Mini   (UART0, GPIO 14)
/dev/ttyAMA2  →  Volca #1     (UART3, GPIO 4)
/dev/ttyAMA3  →  Volca #2     (UART4, GPIO 8)
/dev/ttyAMA4  →  Volca #3     (UART5, GPIO 12)
```

---

## MIDI OUT Circuit × 4 — Perfboard Layout

```
    ┌──────────────────────────────────────────┐
    │  [Pi Header]                             │
    │                                          │
    │  ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐   │
    │  │DIN 1│  │DIN 2│  │DIN 3│  │DIN 4│   │
    │  │OUT  │  │OUT  │  │OUT  │  │OUT  │   │
    │  └─────┘  └─────┘  └─────┘  └─────┘   │
    │  MS-20    Volca1   Volca2   Volca3     │
    │                                          │
    │  [220Ω]×8    [+5V rail]   [GND rail]   │
    └──────────────────────────────────────────┘
```

---

## Power Distribution on MIDI Board

```
    5V Input (from Pi GPIO 5V pin or buck converter) ──── MIDI OUT circuits (220Ω drivers)
```

No 3.3V regulator needed — the Pi GPIO TX pins are the only 3.3V logic, and they connect directly.
No optocouplers, no crystal oscillators, no I2C UART bridge chips.
