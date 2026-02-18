#!/bin/bash
# =============================================================================
# MIDI Box - USB Gadget Configuration Script
# =============================================================================
# Creates a USB MIDI gadget device using libcomposite.
# When connected to a Mac via USB-C, the Pi appears as a multi-port MIDI device.
#
# Prerequisites:
#   /boot/firmware/config.txt must contain: dtoverlay=dwc2
#   /etc/modules must contain: dwc2 and libcomposite
#
# Run as root (sudo).
# =============================================================================

set -e

GADGET_DIR="/sys/kernel/config/usb_gadget/midi-box"
NUM_PORTS=10  # One per connected device

# Check if already configured
if [ -d "$GADGET_DIR" ]; then
    echo "USB gadget already configured at $GADGET_DIR"
    exit 0
fi

# Load required modules
modprobe libcomposite 2>/dev/null || true

# Check configfs is mounted
if [ ! -d "/sys/kernel/config/usb_gadget" ]; then
    mount -t configfs none /sys/kernel/config 2>/dev/null || true
fi

echo "Creating USB MIDI gadget..."

# Create gadget
mkdir -p "$GADGET_DIR"
cd "$GADGET_DIR"

# USB device descriptor
echo 0x1d6b > idVendor    # Linux Foundation
echo 0x0104 > idProduct   # Multifunction Composite Gadget
echo 0x0100 > bcdDevice   # Device version 1.0
echo 0x0200 > bcdUSB      # USB 2.0

# Device strings
mkdir -p strings/0x409
echo "MIDIBox"           > strings/0x409/manufacturer
echo "MIDI Box Router"   > strings/0x409/product
echo "MIDIBOX-001"       > strings/0x409/serialnumber

# MIDI function
mkdir -p functions/midi.usb0
echo "$NUM_PORTS" > functions/midi.usb0/in_ports   # Ports sending TO host (Mac)
echo "$NUM_PORTS" > functions/midi.usb0/out_ports  # Ports receiving FROM host (Mac)

# Configuration
mkdir -p configs/c.1/strings/0x409
echo "MIDI Configuration" > configs/c.1/strings/0x409/configuration
echo 500 > configs/c.1/MaxPower  # 500mA max

# Link function to configuration
ln -s functions/midi.usb0 configs/c.1/

# Enable gadget by binding to UDC (USB Device Controller)
UDC=$(ls /sys/class/udc | head -1)
if [ -z "$UDC" ]; then
    echo "ERROR: No USB Device Controller found."
    echo "Make sure dtoverlay=dwc2 is in /boot/firmware/config.txt"
    exit 1
fi

echo "$UDC" > UDC

echo "USB MIDI gadget configured successfully!"
echo "  - $NUM_PORTS input ports (to Mac)"
echo "  - $NUM_PORTS output ports (from Mac)"
echo "  - UDC: $UDC"
echo ""
echo "Connect Pi USB-C to Mac. Device should appear in Audio MIDI Setup."
