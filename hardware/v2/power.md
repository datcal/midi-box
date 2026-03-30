# MIDI Box v2 — Power Distribution

## Power Input: USB-C with Power Delivery

Replaces the v1 barrel jack with a standard USB-C PD input. The STUSB4500 IC negotiates a power contract with the charger.

### PD Contract

| Parameter | Value |
|-----------|-------|
| Requested voltage | **5V** |
| Requested current | **3A** (minimum) |
| Ideal charger | 5V/5A USB-C PD (25W) |
| Fallback | 5V/3A (standard USB-C) — enough for basic operation |

The STUSB4500 is configured via NVM (one-time programming over I2C) to request 5V @ 3A as PDO1. If the source can provide more (5A), the system will draw what it needs — PD is negotiated max, not forced draw.

> **Why not 9V/12V?** The CM4, USB hub ICs, and MIDI circuits all need 5V. Using a higher PD voltage would require a buck converter, adding cost and complexity. 5V direct is simpler and the whole system runs under 4A.

### STUSB4500 Circuit

```
                    USB-C Connector (J3)
                    ┌─────────────────┐
                    │ VBUS ───────────┼──→ D1 (Schottky) ──→ VBUS_5V rail
                    │ CC1 ────────────┼──→ R3 (5.1kΩ) ──→ GND
                    │ CC2 ────────────┼──→ R4 (5.1kΩ) ──→ GND
                    │ D+ (not used)   │    ├──→ STUSB4500 CC1 pin
                    │ D- (not used)   │    └──→ STUSB4500 CC2 pin
                    │ GND ────────────┼──→ GND
                    └─────────────────┘

                    ┌─────────────────┐
                    │   STUSB4500     │
                    │   (U13)         │
                    │                 │
           CC1  ───┤ CC1             │
           CC2  ───┤ CC2             │
          VBUS  ───┤ VBUS_EN_SNK     │── (VBUS sense)
                   │ VDD     ────────┤── 3.3V (from LDO)
                   │ ADDR    ────────┤── R5 (10kΩ) to GND (I2C addr = 0x28)
                   │ SCL     ────────┤── CM4 GPIO 2 (I2C1 SCL) — for NVM programming
                   │ SDA     ────────┤── CM4 GPIO 3 (I2C1 SDA) — for NVM programming
                   │ POWER_OK ───────┤── (optional: LED or CM4 GPIO for PD status)
                   │ GND     ────────┤── GND
                   └─────────────────┘

    Decoupling:
    VDD  ── C18 (4.7µF) ── GND
    VDD  ── C19 (100nF) ── GND
    VBUS ── C20 (100µF electrolytic) ── GND
```

### STUSB4500 NVM Configuration

The STUSB4500 stores its PD configuration in on-chip NVM. Program once via I2C before deployment:

| NVM Field | Value | Notes |
|-----------|-------|-------|
| PDO1 Voltage | 5V | Only voltage we need |
| PDO1 Current | 3.0A | Minimum acceptable |
| PDO2 | Disabled | We don't need 9V/12V/20V |
| PDO3 | Disabled | |
| SNK_UNCONS_POWER | 0 | Not an unconstrainted sink |
| REQ_SRC_CURRENT | 1 | Request source's max current |

Use ST's GUI tool or the `pystusb4500` Python library to program NVM over I2C.

---

## Power Distribution Tree

```
    USB-C PD (J3) ── D1 (Schottky) ──┬── VBUS_5V (main 5V rail)
                                      │
                 ┌────────────────────┼────────────────────────────────┐
                 │                    │                                │
            ┌────┴────┐          ┌────┴────┐                     ┌────┴────┐
            │ CM4 5V  │          │ USB Hub │                     │  Other  │
            │ (J1/J2) │          │  Power  │                     │         │
            └────┬────┘          └────┬────┘                     └────┬────┘
                 │                    │                                │
            ~2.0A max           ┌─────┼─────┐                    ├── MIDI OUT (50mA)
            (CM4 + screen)      │     │     │                    ├── Fans ×2 (400mA)
                                │     │     │                    ├── LEDs (20mA)
                           F1-F4  F5-F7  (polyfuses)            └── LDO → 3.3V (50mA)
                              │     │
                         USB ports USB ports
                         (150-200mA each)
```

---

## 5V Rail Budget

| Consumer | Current Draw | Notes |
|----------|-------------|-------|
| CM4 + WiFi | ~1.5A | CM4 draws less than full Pi 4 (no HDMI, no onboard USB hub) |
| 5" DSI touchscreen | ~0.3A | Via DSI connector, powered from CM4 5V |
| USB Hub ICs (U2, U3) | ~0.1A | Logic power only |
| USB devices (6× MIDI) | ~1.2A | ~200mA each worst case |
| 2× Cooling fans | ~0.4A | Always-on, direct from 5V rail |
| MIDI OUT (4× 220Ω circuits) | ~0.05A | ~8.6mA per active port |
| LDO (3.3V rail) | ~0.05A | STUSB4500 + hub IC logic |
| LEDs | ~0.02A | 6× LEDs @ ~3mA each |
| **Total** | **~3.6A** | |
| **Supply (PD 5V/5A)** | **5.0A** | **~1.4A headroom** |

> Same total as v1 — the load hasn't changed, just the packaging. The headroom is comfortable.

---

## 3.3V Rail

A small LDO (AP2112K-3.3) generates 3.3V from the 5V rail for:
- STUSB4500 VDD
- USB2514B VDD33 / VDDA33 (hub IC logic)
- Pull-up resistors

```
    VBUS_5V ── C22 (100nF) ──┬── AP2112K-3.3 (U14) ──┬── V3V3 (3.3V rail)
                              │     │                   │
                             GND   GND              C21 (10µF) ── GND
```

The AP2112K provides up to 600mA — we draw ~50mA on this rail. Massive headroom.

> **CM4 has its own internal 3.3V regulator** — do NOT power CM4 from this LDO. CM4 takes 5V only and regulates internally.

---

## Protection

### Reverse Polarity (D1)

```
    VBUS (from USB-C) ── D1 (SS34 Schottky, 3A) ── VBUS_5V
```

Forward voltage drop: ~0.3V at 3A. So VBUS_5V is ~4.7V under load. This is fine — CM4 input range is 4.75V–5.25V, and USB PD sources deliver 5.0V–5.25V.

If the 0.3V drop is a concern, replace D1 with an **ideal diode IC** (e.g., LTC4357) for <50mV drop. For prototype, the Schottky is fine.

### Per-Port Overcurrent (F1–F8)

Each USB-A downstream port has a 500mA polyfuse (resettable PTC fuse):

```
    VBUS_5V ── F1 (500mA polyfuse) ── J9 VBUS pin
    VBUS_5V ── F2 (500mA polyfuse) ── J10 VBUS pin
    ... (one per port)
```

If a connected device shorts or draws >500mA, the polyfuse trips and resets when the fault clears. No damage to the main rail or other devices.

### Input Bulk Capacitance

```
    VBUS_5V ── C20 (100µF electrolytic) ── GND     (main input filter)
              + additional 100nF ceramic near each IC
```

The 100µF cap handles inrush and load transients. Place it as close to the USB-C connector as possible.

---

## Thermal Considerations

| Component | Power Dissipation | Notes |
|-----------|-------------------|-------|
| D1 (Schottky) | ~1W at 3A | Gets warm — use SMA package with large pad, or thermal relief |
| AP2112K (LDO) | ~85mW | 50mA × (5V−3.3V) = negligible |
| USB2514B (×2) | ~200mW each | Normal operating range |
| Polyfuses | ~50mW each (normal) | Only heat up when tripping |

The Schottky diode is the only component that needs thermal attention. Give it a generous copper pour on the cathode pad. If using an ideal diode IC instead, thermal is a non-issue.

---

## Test Points

Add test points on the PCB for debugging:

| TP | Net | Purpose |
|----|-----|---------|
| TP1 | VBUS_5V | Main 5V rail voltage |
| TP2 | V3V3 | 3.3V rail voltage |
| TP3 | GND | Ground reference |
| TP4 | POWER_OK | STUSB4500 PD negotiation status |

---

## Charger Recommendations

| Charger | Compatibility |
|---------|---------------|
| Any USB-C PD charger (5V/3A+) | Full operation |
| USB-C 5V/1.5A (non-PD) | CM4 boots but USB devices may brownout |
| USB-A to USB-C cable | **Will not work** — no PD, only 500mA |
| Apple 20W/30W charger | Works (supports 5V/3A) |
| Anker 65W GaN charger | Works (supports 5V/3A PDO) |

Always use a cable rated for 3A+ (not a charge-only thin cable).
