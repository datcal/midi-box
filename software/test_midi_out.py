#!/usr/bin/env python3
"""
MIDI OUT hardware test script for Raspberry Pi native UARTs.
Tests GPIO 14 / /dev/ttyAMA0 by default.

Usage:
    python3 test_midi_out.py              # interactive menu
    python3 test_midi_out.py --port /dev/ttyAMA3   # use a different port
"""

import argparse
import sys
import time

import serial


MIDI_BAUD = 31250
DEFAULT_PORT = "/dev/ttyAMA0"
LED_GPIO = 26


def open_port(path):
    try:
        s = serial.Serial(path, MIDI_BAUD, timeout=0)
        print(f"  Opened {path} at {MIDI_BAUD} baud")
        return s
    except serial.SerialException as e:
        print(f"  ERROR: cannot open {path}: {e}")
        sys.exit(1)


def test_single_note(s, channel=1):
    """Send one middle-C note for 1 second."""
    ch = channel - 1
    print(f"\n  Sending Note On  — ch {channel}, note 60, vel 127")
    s.write(bytes([0x90 | ch, 60, 127]))
    time.sleep(1)
    print(f"  Sending Note Off — ch {channel}, note 60")
    s.write(bytes([0x80 | ch, 60, 0]))
    print("  Done. Did you hear a note?")


def test_all_channels(s):
    """Play a note on every channel (1-16), 0.4s each."""
    print("\n  Playing middle C on all 16 channels...")
    for ch in range(16):
        s.write(bytes([0x90 | ch, 60, 127]))
        time.sleep(0.3)
        s.write(bytes([0x80 | ch, 60, 0]))
        time.sleep(0.1)
        print(f"    ch {ch + 1:2d} ✓")
    print("  Done. Did you hear anything on any channel?")


def test_scale(s, channel=1):
    """Play a C major scale."""
    ch = channel - 1
    notes = [60, 62, 64, 65, 67, 69, 71, 72]
    print(f"\n  Playing C major scale on ch {channel}...")
    for note in notes:
        s.write(bytes([0x90 | ch, note, 100]))
        time.sleep(0.3)
        s.write(bytes([0x80 | ch, note, 0]))
        time.sleep(0.05)
    print("  Done.")


def test_velocity(s, channel=1):
    """Play same note at increasing velocities."""
    ch = channel - 1
    print(f"\n  Velocity ramp on ch {channel}, note 60...")
    for vel in [10, 30, 50, 70, 90, 110, 127]:
        print(f"    vel {vel:3d}")
        s.write(bytes([0x90 | ch, 60, vel]))
        time.sleep(0.4)
        s.write(bytes([0x80 | ch, 60, 0]))
        time.sleep(0.1)
    print("  Done.")


def test_loop(s, channel=1):
    """Repeat note on/off for logic analyzer capture. Ctrl+C to stop."""
    ch = channel - 1
    print(f"\n  Looping Note On/Off on ch {channel} — Ctrl+C to stop")
    print(f"  (connect logic analyzer to UART TX pin)")
    try:
        i = 0
        while True:
            s.write(bytes([0x90 | ch, 60, 127]))
            time.sleep(0.5)
            s.write(bytes([0x80 | ch, 60, 0]))
            time.sleep(0.5)
            i += 1
            if i % 5 == 0:
                print(f"    {i} notes sent...")
    except KeyboardInterrupt:
        # Send note off to silence any stuck note
        s.write(bytes([0x80 | ch, 60, 0]))
        print("\n  Stopped.")


def test_raw_bytes(s):
    """Send specific raw bytes for debugging."""
    print("\n  Sending raw MIDI bytes: 0x90 0x3C 0x7F (Note On ch1, C4, vel 127)")
    data = bytes([0x90, 0x3C, 0x7F])
    written = s.write(data)
    print(f"  Wrote {written} bytes")
    time.sleep(1)
    s.write(bytes([0x80, 0x3C, 0x00]))
    print("  Sent Note Off")


def gpio_set(pin, value):
    """Set a GPIO pin high (1) or low (0) using pinctrl."""
    import subprocess
    subprocess.run(["pinctrl", "set", str(pin), "op", "dh" if value else "dl"],
                   capture_output=True)


def test_gpio_blink():
    """Blink an LED on GPIO 26 to verify the Pi's GPIO is working."""
    print(f"\n  Blinking GPIO {LED_GPIO} — 5 times, 0.5s on/off")
    for i in range(5):
        gpio_set(LED_GPIO, 1)
        print(f"    blink {i + 1} — ON")
        time.sleep(0.5)
        gpio_set(LED_GPIO, 0)
        time.sleep(0.5)
    gpio_set(LED_GPIO, 0)
    print("  Done. Did the LED blink?")


def test_gpio_and_midi(s, channel=1):
    """Blink GPIO 26 in sync with MIDI notes — proves both are firing."""
    ch = channel - 1
    print(f"\n  GPIO {LED_GPIO} blink + MIDI note in sync — Ctrl+C to stop")
    try:
        i = 0
        while True:
            gpio_set(LED_GPIO, 1)
            s.write(bytes([0x90 | ch, 60, 127]))
            time.sleep(0.5)
            gpio_set(LED_GPIO, 0)
            s.write(bytes([0x80 | ch, 60, 0]))
            time.sleep(0.5)
            i += 1
            if i % 5 == 0:
                print(f"    {i} cycles...")
    except KeyboardInterrupt:
        s.write(bytes([0x80 | ch, 60, 0]))
        gpio_set(LED_GPIO, 0)
        print("\n  Stopped.")


def panic(s):
    """All Notes Off on all channels."""
    print("\n  Sending All Notes Off (CC 123) on all channels...")
    for ch in range(16):
        s.write(bytes([0xB0 | ch, 123, 0]))
        time.sleep(0.01)
    print("  Done.")


def main():
    parser = argparse.ArgumentParser(description="Test MIDI OUT hardware")
    parser.add_argument("--port", default=DEFAULT_PORT, help=f"Serial port (default: {DEFAULT_PORT})")
    args = parser.parse_args()

    print(f"\n{'=' * 50}")
    print(f"  MIDI OUT Hardware Test")
    print(f"  Port: {args.port}")
    print(f"{'=' * 50}")

    s = open_port(args.port)
    channel = 1

    while True:
        print(f"\n  --- Test Menu (ch {channel}) ---")
        print("  1) Single note (middle C)")
        print("  2) All 16 channels")
        print("  3) C major scale")
        print("  4) Velocity ramp")
        print("  5) Loop for logic analyzer")
        print("  6) Raw bytes")
        print("  7) Panic (all notes off)")
        print(f"  8) Blink LED on GPIO {LED_GPIO} (no MIDI)")
        print(f"  9) Blink LED + MIDI note in sync")
        print(f"  c) Change channel (current: {channel})")
        print("  q) Quit")

        try:
            choice = input("\n  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if choice == "1":
            test_single_note(s, channel)
        elif choice == "2":
            test_all_channels(s)
        elif choice == "3":
            test_scale(s, channel)
        elif choice == "4":
            test_velocity(s, channel)
        elif choice == "5":
            test_loop(s, channel)
        elif choice == "6":
            test_raw_bytes(s)
        elif choice == "7":
            panic(s)
        elif choice == "c":
            try:
                ch = int(input("  Channel (1-16): ").strip())
                if 1 <= ch <= 16:
                    channel = ch
                    print(f"  Channel set to {channel}")
                else:
                    print("  Must be 1-16")
            except (ValueError, EOFError, KeyboardInterrupt):
                pass
        elif choice == "8":
            test_gpio_blink()
        elif choice == "9":
            test_gpio_and_midi(s, channel)
        elif choice == "q":
            break

    panic(s)
    s.close()
    print("\n  Port closed. Bye!\n")


if __name__ == "__main__":
    main()
