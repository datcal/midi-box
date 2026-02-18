# Gear Inventory & MIDI Capabilities

## 1. Arturia KeyLab 88 MK2

- **Role:** Primary 88-key controller
- **USB MIDI:** Yes (class-compliant)
- **5-Pin MIDI OUT:** Yes
- **5-Pin MIDI IN:** No
- **MIDI Channels:** All (configurable)
- **Features:** Aftertouch, pitch/mod wheels, 9 faders, 9 knobs, 16 pads, DAW integration
- **Connection to MIDI Box:** USB
- **Notes:** Main keyboard controller. Can split zones to send different channels to different synths.

## 2. Arturia KeyStep

- **Role:** Small controller + step sequencer + arpeggiator
- **USB MIDI:** Yes (class-compliant)
- **5-Pin MIDI IN:** Yes
- **5-Pin MIDI OUT:** Yes
- **MIDI Channels:** 1-16 (configurable)
- **Features:** 32-step sequencer, arpeggiator, MIDI/CV/Gate outputs
- **Connection to MIDI Box:** USB
- **Notes:** Great for sequencing the Volcas and MS-20. Can also output CV/Gate directly to MS-20 and Model D (separate from MIDI box).

## 3. Korg MS-20 Mini

- **Role:** Semi-modular analog synth
- **USB MIDI:** No
- **5-Pin MIDI IN:** Yes
- **5-Pin MIDI OUT:** No
- **MIDI Channels:** Receives on 1 channel (configurable via MIDI)
- **Features:** Note on/off, pitch bend. Limited MIDI implementation.
- **Connection to MIDI Box:** 5-Pin DIN OUT from box → MS-20 MIDI IN
- **Notes:** Only responds to note on/off and pitch bend. No CC control via MIDI. Use CV/Gate patch cables for more control.

## 4. Behringer Model D

- **Role:** Mono analog synth (Minimoog clone)
- **USB MIDI:** Yes (class-compliant)
- **5-Pin MIDI IN:** Yes
- **5-Pin MIDI OUT:** No
- **MIDI Channels:** Configurable
- **Features:** Note on/off, pitch bend, some CC (filter cutoff, etc.)
- **Connection to MIDI Box:** USB
- **Notes:** Has both USB and 5-pin MIDI IN. Using USB saves a DIN port on the box. Also has CV/Gate inputs.

## 5. Roland JP-08 (Boutique)

- **Role:** Digital polysynth (Jupiter-8 recreation)
- **USB MIDI:** Yes (class-compliant)
- **5-Pin MIDI IN/OUT:** Yes (via DK-01 dock or breakout cable)
- **MIDI Channels:** Configurable
- **Features:** Full MIDI CC implementation, program change, sysex for patch dumps
- **Connection to MIDI Box:** USB
- **Notes:** Very responsive to CC. Can automate many parameters from DAW or controller.

## 6. Arturia MicroBrute

- **Role:** Mono analog synth with patch bay
- **USB MIDI:** Yes (class-compliant)
- **5-Pin MIDI IN:** Yes
- **5-Pin MIDI OUT:** No
- **MIDI Channels:** Configurable
- **Features:** Note on/off, pitch bend, mod wheel, some CC
- **Connection to MIDI Box:** USB
- **Notes:** Has its own mini patch bay for CV modulation. MIDI is basic but functional.

## 7. Korg Volca (x3)

- **Role:** Compact synths/drum machines
- **USB MIDI:** No
- **5-Pin MIDI IN:** Yes
- **5-Pin MIDI OUT:** No (sync out only on some models)
- **MIDI Channels:** Configurable per unit
- **Features:** Note on/off, some CC (varies by model)
- **Connection to MIDI Box:** 5-Pin DIN OUT from box → each Volca MIDI IN
- **Notes:** Each Volca should be on its own MIDI channel. The sync out can chain Volcas together for tempo sync without using MIDI.

**Recommended channel assignment:**
| Volca | MIDI Channel |
|-------|-------------|
| Volca #1 | Channel 4 |
| Volca #2 | Channel 5 |
| Volca #3 | Channel 6 |

## 8. Roland SP-404 MK2

- **Role:** Sampler / performance tool / effects
- **USB MIDI:** Yes (class-compliant)
- **5-Pin MIDI IN:** Yes
- **5-Pin MIDI OUT:** Yes
- **MIDI Channels:** Configurable
- **Features:** Note on/off (pad triggers), program change, CC, MIDI clock
- **Connection to MIDI Box:** USB
- **Notes:** Can act as both a MIDI controller (pads → trigger synths) and a sound module (receive MIDI to trigger samples). Very versatile in a live setup.

---

## Connection Summary

### Via USB (6 devices)
```
USB Hub Port 1 ← Arturia KeyLab 88 MK2
USB Hub Port 2 ← Arturia KeyStep
USB Hub Port 3 ← Behringer Model D
USB Hub Port 4 ← Roland JP-08
USB Hub Port 5 ← Arturia MicroBrute
USB Hub Port 6 ← Roland SP-404 MK2
```

### Via 5-Pin DIN (4 devices)
```
MIDI Box DIN OUT 1 → Korg MS-20 Mini (MIDI IN)
MIDI Box DIN OUT 2 → Korg Volca #1 (MIDI IN)
MIDI Box DIN OUT 3 → Korg Volca #2 (MIDI IN)
MIDI Box DIN OUT 4 → Korg Volca #3 (MIDI IN)
```

### Spare Ports
```
MIDI Box DIN 5 → Spare (IN/OUT)
MIDI Box DIN 6 → Spare (IN/OUT)
```

---

## Suggested Default MIDI Channel Map

| Channel | Device | Role |
|---------|--------|------|
| 1 | MS-20 Mini | Lead / bass |
| 2 | Behringer Model D | Bass |
| 3 | Roland JP-08 | Pads / poly |
| 4 | Volca #1 | Depends on model |
| 5 | Volca #2 | Depends on model |
| 6 | Volca #3 | Depends on model |
| 7 | MicroBrute | Lead / acid |
| 10 | SP-404 MK2 | Samples / drums |
| 1-16 | KeyLab 88 MK2 | Controller (sends) |
| 1-16 | KeyStep | Sequencer (sends) |
