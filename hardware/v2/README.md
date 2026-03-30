# MIDI Box v2 — Integrated PCB Design

## Overview

Single custom PCB that replaces all discrete modules from v1 (Pi 4 + 2× Waveshare USB hubs + perfboard MIDI circuits + jumper wires). Everything on one board, designed in KiCad, manufactured and assembled in China (JLCPCB / PCBWay).

## What Changed from v1

| Aspect | v1 (Current) | v2 (This Design) |
|--------|--------------|-------------------|
| Compute | Raspberry Pi 4 full board | **CM4 module** on carrier (this PCB) |
| USB Hub | 2× Waveshare 4-port hubs | **On-board USB2514B** hub ICs (8 ports) |
| Power Input | 5V 5A barrel jack | **USB-C with PD** (STUSB4500 negotiates 5V/3A+) |
| MIDI OUT | Perfboard + jumper wires | **SMD resistors on PCB** + through-hole DIN-5 |
| Wiring | Dupont jumpers, USB cables | **PCB traces** — zero internal cables |
| Enclosure | 3D printed box for loose modules | 3D printed or CNC case **around single PCB** |

## Design Goals

1. **Single board** — CM4 carrier + USB hub + MIDI OUT + power, all on one PCB
2. **USB-C PD power** — standard charger input, no proprietary barrel jack
3. **8× USB-A downstream** — enough for 6 MIDI devices + 2 spare
4. **4× DIN-5 MIDI OUT** — same Pi UART-driven circuits as v1
5. **DSI connector** — 5" touchscreen ribbon passthrough
6. **DAW mode USB-C** — second USB-C port for CM4 USB gadget (Pi → Mac)
7. **Manufacturable** — 4-layer PCB, JLCPCB SMT assembly for SMD parts, hand-solder through-hole connectors
8. **CM4 + CM5 compatible** — same SO-DIMM connector pinout (verify mechanicals)

## Subsystems

| Subsystem | Key Components | Doc |
|-----------|---------------|-----|
| Compute | CM4 + Hirose DF40C-100DS connectors | [schematics.md](schematics.md) |
| USB Hub | 2× USB2514B (cascaded, 8 downstream) | [schematics.md](schematics.md) |
| USB-PD Power | STUSB4500 + USB-C connector | [power.md](power.md) |
| MIDI OUT | 4× UART → 220Ω → DIN-5 | [schematics.md](schematics.md) |
| All Components | Full BOM with LCSC part numbers | [bom.md](bom.md) |
| PCB Manufacturing | Layer stackup, fab specs, assembly notes | [pcb-spec.md](pcb-spec.md) |

## Board Size Estimate

~120mm × 100mm (4-layer, 1.6mm thickness). Final size depends on USB-A connector placement — 8 connectors in a row need ~110mm edge length.

## Software Compatibility

**No software changes needed.** The CM4 exposes the same GPIO, UART, USB, and DSI interfaces as the Pi 4. Same device tree overlays, same `/dev/ttyAMA*` paths, same ALSA MIDI stack. The `devices.yaml` and `midi_box.yaml` configs work as-is.

Only change: CM4 Lite (no eMMC) boots from SD card like Pi 4. CM4 with eMMC needs `rpiboot` to flash — update `scripts/inject_sdcard.sh` if using eMMC variant.
