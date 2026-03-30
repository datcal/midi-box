# MIDI Box v2 — Bill of Materials

All parts selected for JLCPCB SMT assembly availability. LCSC part numbers included where possible. Check stock before ordering — substitute with pin-compatible alternatives if out of stock.

---

## Compute Module

| Ref | Component | Qty | Package | LCSC / Source | Notes |
|-----|-----------|-----|---------|---------------|-------|
| U1 | Raspberry Pi CM4 (2GB+ RAM, WiFi) | 1 | SO-DIMM module | RPi reseller | CM4 Lite (no eMMC) recommended — boots from SD like Pi 4 |
| J1, J2 | Hirose DF40C-100DS-0.4V (CM4 connector) | 2 | SMD 100-pin | C506281 | One per CM4 board-to-board connector (2 needed) |
| C1–C4 | 100nF ceramic capacitor | 4 | 0402 | C1525 | CM4 decoupling (place near connector pins) |
| C5 | 10µF ceramic capacitor | 1 | 0805 | C19702 | CM4 bulk decoupling |

---

## USB Hub (8 Downstream Ports)

Two USB2514B ICs cascaded: IC1 is root hub (1 upstream from CM4 + 3 downstream + 1 to IC2). IC2 provides 4 more downstream. Total = 7 usable ports (expand to 8 with third IC or use USB2517 for 7-port single chip).

**Option A: 2× USB2514B (4-port hub IC) — cascaded**

| Ref | Component | Qty | Package | LCSC / Source | Notes |
|-----|-----------|-----|---------|---------------|-------|
| U2, U3 | USB2514B-I/M2 (Microchip) | 2 | QFN-36 | C136518 | 4-port USB 2.0 hub, cascaded |
| Y1, Y2 | 24 MHz crystal (18pF load) | 2 | 3215 SMD | C32346 | One per hub IC |
| C6–C13 | 100nF ceramic capacitor | 8 | 0402 | C1525 | Decoupling — 4 per hub IC |
| C14, C15 | 10µF ceramic capacitor | 2 | 0805 | C19702 | Bulk cap per hub IC |
| C16, C17 | 18pF ceramic capacitor | 4 | 0402 | C1808 | Crystal load caps (2 per crystal) |
| R1, R2 | 1.5kΩ resistor | 2 | 0402 | C4026 | USB upstream pull-up (1 per hub) |

**Option B: 1× USB2517 (7-port hub IC) — single chip**

| Ref | Component | Qty | Package | LCSC / Source | Notes |
|-----|-----------|-----|---------|---------------|-------|
| U2 | USB2517-JZX (Microchip) | 1 | QFN-48 | C2155909 | 7-port USB 2.0 hub, single IC |
| Y1 | 24 MHz crystal (18pF load) | 1 | 3215 SMD | C32346 | |
| C6–C9 | 100nF ceramic capacitor | 4 | 0402 | C1525 | Decoupling |
| C10 | 10µF ceramic capacitor | 1 | 0805 | C19702 | Bulk cap |
| C11, C12 | 18pF ceramic capacitor | 2 | 0402 | C1808 | Crystal load caps |
| R1 | 1.5kΩ resistor | 1 | 0402 | C4026 | Upstream pull-up |

> **Recommendation:** Option B (USB2517) if you want simplicity. Option A (2× USB2514B) if USB2517 is out of stock or you want 8 ports exactly.

---

## USB ESD Protection

| Ref | Component | Qty | Package | LCSC / Source | Notes |
|-----|-----------|-----|---------|---------------|-------|
| U4–U11 | USBLC6-2SC6 (ST) | 8 | SOT-23-6 | C7519 | One per USB downstream port — protects D+/D- |
| U12 | USBLC6-2SC6 (ST) | 1 | SOT-23-6 | C7519 | USB upstream (CM4 side) |

---

## USB-C Power Delivery (Input)

| Ref | Component | Qty | Package | LCSC / Source | Notes |
|-----|-----------|-----|---------|---------------|-------|
| U13 | STUSB4500QTR (ST) | 1 | QFN-24 | C2678061 | USB-PD sink controller — negotiates 5V/3A from PD source |
| J3 | USB-C 16-pin receptacle (power + CC) | 1 | SMD mid-mount | C2765186 | Power input connector |
| R3, R4 | 5.1kΩ resistor | 2 | 0402 | C25905 | CC1/CC2 pull-down (required for USB-C) |
| R5 | 10kΩ resistor | 1 | 0402 | C25744 | STUSB4500 ADDR pin |
| C18 | 4.7µF ceramic capacitor | 1 | 0805 | C1779 | STUSB4500 VDD decoupling |
| C19 | 100nF ceramic capacitor | 1 | 0402 | C1525 | STUSB4500 decoupling |
| C20 | 100µF electrolytic capacitor | 1 | 8×10mm | C72505 | VBUS bulk cap (input side) |

---

## USB-C DAW Port (CM4 USB Gadget)

| Ref | Component | Qty | Package | LCSC / Source | Notes |
|-----|-----------|-----|---------|---------------|-------|
| J4 | USB-C 16-pin receptacle | 1 | SMD mid-mount | C2765186 | Connects CM4 USB 2.0 OTG to Mac |
| R6, R7 | 5.1kΩ resistor | 2 | 0402 | C25905 | CC1/CC2 pull-down |

---

## MIDI OUT (4× DIN-5 Ports)

Same active-drive circuit as v1 — Pi UART TX pins through 220Ω resistors to DIN-5 connectors. SMD resistors now.

| Ref | Component | Qty | Package | LCSC / Source | Notes |
|-----|-----------|-----|---------|---------------|-------|
| R8–R15 | 220Ω resistor | 8 | 0805 | C17557 | 2 per MIDI port (source + sink drive) |
| J5–J8 | 5-Pin DIN female connector (PCB mount) | 4 | Through-hole | — (Mouser/Digikey) | CUI SDS-50J or equivalent. Not available on LCSC — hand solder |

### MIDI OUT Port Assignments

| Port | UART | CM4 GPIO (TX) | Device |
|------|------|---------------|--------|
| J5 | UART0 | GPIO 14 | Korg MS-20 Mini |
| J6 | UART3 | GPIO 4 | Korg Volca #1 |
| J7 | UART4 | GPIO 8 | Korg Volca #2 |
| J8 | UART5 | GPIO 12 | Korg Volca #3 |

---

## USB Downstream Connectors

| Ref | Component | Qty | Package | LCSC / Source | Notes |
|-----|-----------|-----|---------|---------------|-------|
| J9–J16 | USB-A female connector (single, horizontal) | 8 | Through-hole | C46407 | Standard USB-A receptacle. Through-hole for mechanical strength |

---

## Display & Misc Connectors

| Ref | Component | Qty | Package | LCSC / Source | Notes |
|-----|-----------|-----|---------|---------------|-------|
| J17 | DSI 15-pin FPC connector (1mm pitch) | 1 | SMD | C262652 | 5" touchscreen ribbon passthrough |
| J18 | MicroSD card slot | 1 | SMD push-push | C585350 | CM4 Lite boot media |
| J19 | 2-pin JST-XH header (fan) | 2 | Through-hole | C158012 | 5V fan connectors (always-on) |
| J20 | 2-pin JST-XH header (fan) | — | — | — | (second fan, same part as J19) |

---

## Power Regulation & Distribution

| Ref | Component | Qty | Package | LCSC / Source | Notes |
|-----|-----------|-----|---------|---------------|-------|
| U14 | AP2112K-3.3 (3.3V LDO, 600mA) | 1 | SOT-23-5 | C51118 | 3.3V rail for STUSB4500 + hub IC logic |
| C21 | 10µF ceramic capacitor | 1 | 0805 | C19702 | LDO output cap |
| C22 | 100nF ceramic capacitor | 1 | 0402 | C1525 | LDO input cap |
| F1–F8 | 500mA polyfuse (resettable) | 8 | 1206 | C70069 | Per USB downstream port — overcurrent protection |
| D1 | SS34 Schottky diode (3A, 40V) | 1 | SMA | C8678 | Reverse polarity protection on VBUS |

---

## Status LEDs

| Ref | Component | Qty | Package | LCSC / Source | Notes |
|-----|-----------|-----|---------|---------------|-------|
| LED1 | Green LED (power) | 1 | 0805 | C2297 | Power indicator |
| LED2 | Blue LED (activity) | 1 | 0805 | C72041 | CM4 GPIO-driven activity |
| LED3–LED6 | Yellow LED (MIDI TX) | 4 | 0805 | C2296 | One per MIDI OUT port — optional, GPIO driven |
| R16 | 1kΩ resistor (LED current limit) | 6 | 0402 | C11702 | One per LED (~3mA at 3.3V) |

---

## Passive Totals Summary

| Part | Value | Package | Total Qty |
|------|-------|---------|-----------|
| Ceramic capacitor | 100nF | 0402 | ~16 |
| Ceramic capacitor | 10µF | 0805 | ~4 |
| Ceramic capacitor | 18pF | 0402 | 2–4 |
| Ceramic capacitor | 4.7µF | 0805 | 1 |
| Electrolytic capacitor | 100µF | 8×10mm | 1 |
| Resistor | 220Ω | 0805 | 8 |
| Resistor | 1kΩ | 0402 | 6 |
| Resistor | 1.5kΩ | 0402 | 1–2 |
| Resistor | 5.1kΩ | 0402 | 4 |
| Resistor | 10kΩ | 0402 | 1 |

---

## Sourcing Notes

- **SMD parts (resistors, caps, ICs, LEDs):** All from LCSC — JLCPCB's in-house parts supplier. Use "basic parts" where possible (cheaper assembly fee).
- **Through-hole connectors (DIN-5, USB-A):** JLCPCB supports mixed assembly but at extra cost. Consider hand-soldering these — they're easy and there are only 12 connectors.
- **CM4 module:** Buy directly from RPi approved resellers (Pimoroni, The Pi Hut, Adafruit). Not available on LCSC.
- **5" DSI touchscreen:** Same as v1 — separate purchase, connects via FPC ribbon.

---

## Cost Estimate (per unit, prototype qty 5)

| Item | Estimated Cost |
|------|---------------|
| PCB fabrication (4-layer, 5 pcs) | ~$15 |
| SMT assembly (SMD parts) | ~$30–50 |
| LCSC components (SMD) | ~$15–25 |
| Through-hole connectors (DIN-5, USB-A) | ~$10–15 |
| CM4 module (2GB WiFi) | ~$35–45 |
| USB-C PD charger (5V/3A+) | ~$10–15 |
| **Total per unit** | **~$115–150** |

> v1 cost with Pi 4 + 2× Waveshare hubs + perfboard: ~$140–170. v2 is comparable or cheaper, and far more reliable.
