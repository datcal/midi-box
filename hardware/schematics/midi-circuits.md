# MIDI I/O Circuit Schematics

## MIDI Electrical Specification

- MIDI uses **31250 baud** serial, 8-N-1
- Current loop: 5mA through optocoupler
- All MIDI IN ports **must** be optoisolated (prevents ground loops)
- MIDI OUT drives current into the receiving device's optocoupler

---

## MIDI OUT Circuit (Active Drive)

One circuit per MIDI OUT port. Active driving per current MIDI spec.

```
                         +5V
                          │
                          │
                     ┌────┴────┐
                     │  220 ohm │
                     └────┬────┘
                          │
                          ├──────────── DIN Pin 4 (Source)
                          │
    UART TX ─────┬────────┘
                 │
            ┌────┴────┐
            │  220 ohm │
            └────┬────┘
                 │
                 └───────────────── DIN Pin 5 (Sink)


    DIN Pin 2 ──── Shield / Ground (optional, connected to cable shield)
    DIN Pin 1, 3 ── Not connected
```

### How it works:
- When TX is HIGH (idle): no current flows, pin 4 and pin 5 are both near +5V
- When TX is LOW (data): current flows from +5V through 220ohm into pin 4, through the receiver's optocoupler, back out pin 5, through 220ohm to TX (LOW = ground)
- ~5mA current loop at 5V: (5V - 1.2V drop) / (220 + 220) = ~8.6mA (within spec)

---

## MIDI IN Circuit (Optoisolated)

One circuit per MIDI IN port. Uses 6N138 high-speed optocoupler.

```
    DIN Pin 4 ──────┬──────────────────────────────────┐
                    │                                   │
               ┌────┴────┐                              │
               │  220 ohm │                             │
               └────┬────┘                              │
                    │                                   │
                    ├───── Anode ┌──────────┐           │
                    │            │  6N138   │           │
    DIN Pin 5 ─────┤            │          │    +3.3V  │
                    │   1N4148   │  1  ●  8 │──── VCC  │
                    ├──┤>├──┘   │          │           │
                    │            │  2     7 │──┬── UART RX
                    └─── Cathode │          │  │
                                 │  3     6 │  ├── 10K to +3.3V
                                 │          │  │
                                 │  4     5 │──┘
                                 └──────────┘
                                   │
                                  GND


    6N138 Pin Assignment:
    ─────────────────────
    Pin 1: NC (Anode of internal LED - we use pin 2)
    Pin 2: Anode (MIDI IN current enters here)
    Pin 3: Cathode (MIDI IN current exits here)
    Pin 4: GND
    Pin 5: GND (or Vee)
    Pin 6: Emitter output (active low) → connect to UART RX via pullup
    Pin 7: VCC
    Pin 8: VCC
```

### Detailed 6N138 Wiring:

```
                        +3.3V
                          │
                     ┌────┴────┐
                     │  10K    │
                     └────┬────┘
                          │
                          ├────────── To UART RX (SC16IS752 or Pi GPIO)
                          │
              ┌───────────┴───────────┐
              │       6N138           │
              │                       │
    Pin 2 ────┤ LED Anode    Output ├──── Pin 6 (open collector)
              │                       │
    Pin 3 ────┤ LED Cathode  GND    ├──── Pin 4
              │                       │
              │              VCC    ├──── Pin 8 ── +3.3V
              └───────────────────────┘

    External:
    ─────────
    DIN Pin 4 → 220 ohm → 6N138 Pin 2 (Anode)
    DIN Pin 5 → 6N138 Pin 3 (Cathode) ← 1N4148 diode (reverse protection)
    100nF cap between Pin 8 (VCC) and Pin 4 (GND) for decoupling
```

### Notes:
- Use 3.3V (not 5V) for the output side since Pi GPIO and SC16IS752 are 3.3V logic
- The 10K pull-up on pin 6 gives a clean digital signal
- The 1N4148 protects the optocoupler LED from reverse voltage
- 100nF decoupling capacitor close to VCC/GND pins

---

## SC16IS752 I2C-to-UART Bridge

Each SC16IS752 provides 2 UART channels at 31250 baud for MIDI.

```
                    +3.3V
                      │
              ┌───────┴───────┐
              │   SC16IS752   │
              │               │
    Pi SDA ───┤ SDA     TXA  ├──── MIDI OUT Circuit A
              │               │
    Pi SCL ───┤ SCL     RXA  ├──── MIDI IN Circuit A
              │               │
              │         TXB  ├──── MIDI OUT Circuit B
              │               │
    A0/A1 ────┤ ADDR    RXB  ├──── MIDI IN Circuit B
              │               │
       GND ───┤ GND     IRQ  ├──── Pi GPIO (interrupt, optional)
              │               │
     3.3V ────┤ VCC     XTAL ├──── 1.8432 MHz or 14.7456 MHz crystal
              │               │
              └───────────────┘

    I2C Address Selection:
    ──────────────────────
    A0=GND, A1=GND → 0x48 (Chip #1)
    A0=VCC, A1=GND → 0x49 (Chip #2)
```

### Crystal Selection:
- **1.8432 MHz**: Standard, divides cleanly to 31250 baud
- **14.7456 MHz**: Higher frequency, also divides cleanly, better for multi-baud

### I2C Pull-ups:
- 4.7K pull-ups on SDA and SCL to 3.3V (only one set needed for the bus)

---

## Complete MIDI Port Wiring Summary

```
                                    ┌─────────────────┐
                                    │   Raspberry Pi   │
                                    │                  │
                                    │  GPIO 2 (SDA) ──┼──── I2C Bus ────┐
                                    │  GPIO 3 (SCL) ──┼──── I2C Bus ──┐ │
                                    │  GPIO 14 (TX) ──┼──── Spare OUT │ │
                                    │  GPIO 15 (RX) ──┼──── Spare IN  │ │
                                    │                  │               │ │
                                    └─────────────────┘               │ │
                                                                      │ │
    ┌──────────────────────────────────────────────────────────────────┘ │
    │  ┌────────────────────────────────────────────────────────────────┘
    │  │
    │  │     ┌──────────────┐
    │  └─────┤ SC16IS752 #1 │
    │        │ Addr: 0x48   │
    │        │              │
    │        │ CH_A TX ─────┼──── MIDI OUT → MS-20 Mini
    │        │ CH_A RX ─────┼──── (MIDI IN from spare)
    │        │ CH_B TX ─────┼──── MIDI OUT → Volca #1
    │        │ CH_B RX ─────┼──── (MIDI IN from spare)
    │        └──────────────┘
    │
    │        ┌──────────────┐
    └────────┤ SC16IS752 #2 │
             │ Addr: 0x49   │
             │              │
             │ CH_A TX ─────┼──── MIDI OUT → Volca #2
             │ CH_A RX ─────┼──── (MIDI IN from spare)
             │ CH_B TX ─────┼──── MIDI OUT → Volca #3
             │ CH_B RX ─────┼──── (MIDI IN from spare)
             └──────────────┘
```

---

## Perfboard Layout Guide

Suggested layout for a 9x15cm perfboard:

```
    ┌──────────────────────────────────────────────────────┐
    │  [SC16IS752 #1]    [SC16IS752 #2]    [Pi Header]    │
    │                                                       │
    │  [6N138] [6N138]   [6N138] [6N138]   [6N138] [6N138]│
    │                                                       │
    │  ┌─────┐ ┌─────┐   ┌─────┐ ┌─────┐  ┌─────┐ ┌─────┐│
    │  │DIN 1│ │DIN 2│   │DIN 3│ │DIN 4│  │DIN 5│ │DIN 6││
    │  │ IN  │ │ IN  │   │ IN  │ │ IN  │  │ IN  │ │ IN  ││
    │  └─────┘ └─────┘   └─────┘ └─────┘  └─────┘ └─────┘│
    │                                                       │
    │  ┌─────┐ ┌─────┐   ┌─────┐ ┌─────┐  ┌─────┐ ┌─────┐│
    │  │DIN 1│ │DIN 2│   │DIN 3│ │DIN 4│  │DIN 5│ │DIN 6││
    │  │ OUT │ │ OUT │   │ OUT │ │ OUT │  │ OUT │ │ OUT ││
    │  └─────┘ └─────┘   └─────┘ └─────┘  └─────┘ └─────┘│
    │                                                       │
    │  [Power]  [Decoupling Caps]  [LED Activity Drivers]  │
    └──────────────────────────────────────────────────────┘
```

---

## Power Distribution on MIDI Board

```
    5V Input ──┬──── MIDI OUT circuits (220 ohm drivers)
               │
               └──── 3.3V Regulator (AMS1117-3.3 or similar)
                          │
                          ├──── SC16IS752 x2
                          ├──── 6N138 output side x6
                          ├──── Pull-up resistors
                          └──── Decoupling caps
```

Note: If powering from Pi's 3.3V pin, you can skip the regulator but the Pi's 3.3V rail is limited to ~50mA from the GPIO header. Using a separate 3.3V regulator from the 5V rail is safer.
