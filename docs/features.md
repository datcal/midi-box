# Feature Backlog

## Planned — Next Version

### Analog Sync Output (3.5mm Clock Out)

**Why:** Korg Volcas, Pocket Operators, and other analog gear sync via pulse signals on 3.5mm jacks, not MIDI clock. Currently requires daisy-chaining from KeyStep sync out.

**What:**
- Generate analog sync pulses from a Pi GPIO pin
- Pulse rate derived from ClockManager BPM (1 pulse per step, configurable PPQ)
- 3.3V GPIO → 5V level shifter → 3.5mm mono jack
- Sync start/stop follows transport state
- Configurable in web UI (enable/disable, PPQ: 1, 2, 4, 24)

**Hardware:** 1x GPIO pin, 1x 3.3V→5V level shifter (or transistor), 1x 3.5mm mono jack on enclosure

---

### Analog Sync Input (3.5mm Clock In)

**Why:** Accept clock from Eurorack modular systems, drum machines, or other analog gear that output pulse-based sync signals.

**What:**
- Read analog sync pulses on a Pi GPIO pin (interrupt-driven)
- Detect BPM from pulse interval
- Register as a clock source in ClockManager (like external MIDI clock devices)
- 5V→3.3V voltage divider or level shifter for GPIO protection
- Selectable as clock source in web UI alongside MIDI devices and internal

**Hardware:** 1x GPIO pin (input), voltage divider (2 resistors) or level shifter, 1x 3.5mm mono jack on enclosure

---

## Ideas / Future

- CV/Gate output for Eurorack (would need DAC or PWM + filter)
- Multiple sync out jacks (independent rates per jack)
- DIN sync (older Roland/Korg standard) via same 3.5mm jacks
- PWM fan speed control via GPIO 18/13 + MOSFET (fans currently always-on; could ramp speed based on CPU temp)
