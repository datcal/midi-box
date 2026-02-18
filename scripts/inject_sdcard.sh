#!/usr/bin/env bash
# =============================================================================
# MIDI Box — SD Card Injector  (run on your Mac, not on the Pi)
# =============================================================================
#
# After burning Raspberry Pi OS with the Imager, run this script to inject
# the MIDI Box first-boot setup directly onto the SD card.  When the Pi boots,
# it will automatically install everything and reboot into AP mode.
#
# Usage (macOS):
#   sudo bash scripts/inject_sdcard.sh [WIFI_COUNTRY]
#
# Examples:
#   sudo bash scripts/inject_sdcard.sh        # defaults to US
#   sudo bash scripts/inject_sdcard.sh TR     # Turkey
#   sudo bash scripts/inject_sdcard.sh GB     # United Kingdom
#
# Requirements:
#   - Raspberry Pi OS Lite or Desktop burned to SD card
#   - SD card inserted in Mac (both partitions will appear in /Volumes)
#   - This script must be run from the midi-box project root
#
# What gets injected:
#   - WiFi country code fix (prevents rfkill block)
#   - SSH enabled
#   - firstrun.sh that installs MIDI Box on first boot
#   - This entire project directory gets copied to /home/pi/midi-box
# =============================================================================

set -euo pipefail

WIFI_COUNTRY="${1:-US}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()   { echo -e "${GREEN}[✓]${NC} $*"; }
info()  { echo -e "${CYAN}[→]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗] ERROR:${NC} $*"; exit 1; }

# ---------------------------------------------------------------------------
# Only runs on macOS
# ---------------------------------------------------------------------------
[[ "$(uname)" == "Darwin" ]] || error "This script runs on macOS only. On the Pi, use pi_setup.sh instead."
[[ "$(id -u)" -eq 0 ]] || error "Run as root: sudo bash scripts/inject_sdcard.sh $WIFI_COUNTRY"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║    MIDI Box — SD Card Injector (macOS)       ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo
info "Project    : $PROJECT_DIR"
info "WiFi country: $WIFI_COUNTRY"
echo

# ---------------------------------------------------------------------------
# Locate the Pi SD card partitions
# ---------------------------------------------------------------------------

# Pi Imager creates two volumes: "bootfs" (FAT32) and "rootfs" (ext4)
# On macOS, only the FAT32 boot partition is automatically mounted.
BOOT_VOL=""
for candidate in /Volumes/bootfs /Volumes/boot /Volumes/BOOT; do
    if [[ -d "$candidate" ]]; then
        BOOT_VOL="$candidate"
        break
    fi
done

if [[ -z "$BOOT_VOL" ]]; then
    echo
    warn "Could not find the Pi boot partition automatically."
    echo -e "  Mounted volumes:"
    ls /Volumes/
    echo
    read -r -p "  Enter the boot partition path (e.g. /Volumes/bootfs): " BOOT_VOL
    [[ -d "$BOOT_VOL" ]] || error "Path not found: $BOOT_VOL"
fi

log "Found boot partition: $BOOT_VOL"

# Verify it looks like a Pi boot partition
[[ -f "$BOOT_VOL/config.txt" ]] || warn "config.txt not found — are you sure this is a Pi SD card?"

# ---------------------------------------------------------------------------
# 1. Enable SSH
# ---------------------------------------------------------------------------
info "Enabling SSH..."
touch "$BOOT_VOL/ssh"
log "SSH enabled (created $BOOT_VOL/ssh)"

# ---------------------------------------------------------------------------
# 2. Fix WiFi country in cmdline / config
# ---------------------------------------------------------------------------
info "Setting WiFi country to $WIFI_COUNTRY..."

# Raspberry Pi OS Bookworm uses userconf-pi and firstrun.sh mechanism
# We'll set country in wpa_supplicant.conf on the boot partition (legacy method)
# and also via the firstrun script below.
WPA_BOOT="$BOOT_VOL/wpa_supplicant.conf"
cat > "$WPA_BOOT" << EOF
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=$WIFI_COUNTRY
EOF
log "Created wpa_supplicant.conf with country=$WIFI_COUNTRY"

# ---------------------------------------------------------------------------
# 3. Copy project files onto boot partition (they'll be moved on first boot)
#    We can only write to the FAT32 boot partition from macOS.
#    The firstrun.sh script will move them to /home/pi/midi-box.
# ---------------------------------------------------------------------------
info "Copying MIDI Box project files to boot partition..."
DEST="$BOOT_VOL/midi-box"
rm -rf "$DEST"
mkdir -p "$DEST"

# Copy project (exclude .git, venv, __pycache__)
rsync -a --exclude='.git' --exclude='venv' --exclude='.venv' \
    --exclude='__pycache__' --exclude='*.pyc' \
    "$PROJECT_DIR/" "$DEST/"

log "Project files copied to $DEST"

# ---------------------------------------------------------------------------
# 4. Inject firstrun.sh
# ---------------------------------------------------------------------------
info "Injecting firstrun.sh..."

cat > "$BOOT_VOL/firstrun.sh" << FIRSTRUN
#!/bin/bash
# =============================================================================
# MIDI Box — First Boot Auto-Setup
# Generated by inject_sdcard.sh
# =============================================================================
set -e
LOGFILE=/var/log/midi-box-firstrun.log
exec > >(tee -a \$LOGFILE) 2>&1

echo "====== MIDI Box First Boot Setup ======"
date

# Fix rfkill immediately
rfkill unblock all 2>/dev/null || true

# Set WiFi country
WIFI_COUNTRY="$WIFI_COUNTRY"
if command -v raspi-config &>/dev/null; then
    raspi-config nonint do_wifi_country "\$WIFI_COUNTRY" || true
fi
iw reg set "\$WIFI_COUNTRY" 2>/dev/null || true

# Fix wpa_supplicant.conf country
WPA=/etc/wpa_supplicant/wpa_supplicant.conf
if [[ -f "\$WPA" ]]; then
    if grep -q "country=" "\$WPA"; then
        sed -i "s/^country=.*/country=\$WIFI_COUNTRY/" "\$WPA"
    else
        sed -i "1a country=\$WIFI_COUNTRY" "\$WPA"
    fi
fi

# Move project from boot partition to home
BOOT_COPY=/boot/firmware/midi-box
if [[ ! -d "\$BOOT_COPY" ]]; then
    BOOT_COPY=/boot/midi-box
fi

if [[ -d "\$BOOT_COPY" ]]; then
    echo "Moving project files to /home/pi/midi-box ..."
    cp -r "\$BOOT_COPY" /home/pi/midi-box
    chown -R pi:pi /home/pi/midi-box
    echo "Done."
fi

# Run the main installer
if [[ -f /home/pi/midi-box/scripts/pi_setup.sh ]]; then
    echo "Running pi_setup.sh ..."
    WIFI_COUNTRY="\$WIFI_COUNTRY" SERVICE_USER=pi bash /home/pi/midi-box/scripts/pi_setup.sh <<< "n"
    # Note: passing "n" to the reboot prompt — firstrun.sh reboots itself at the end
fi

echo "====== First Boot Setup Complete ======"
date

# Raspberry Pi OS will reboot after firstrun.sh exits
FIRSTRUN

chmod +x "$BOOT_VOL/firstrun.sh"
log "firstrun.sh created"

# ---------------------------------------------------------------------------
# 5. Wire firstrun.sh into the boot process
# ---------------------------------------------------------------------------
# Pi OS Bookworm: add firstrun.sh to cmdline.txt
CMDLINE="$BOOT_VOL/cmdline.txt"
if [[ -f "$CMDLINE" ]]; then
    if ! grep -q "firstrun" "$CMDLINE"; then
        # Append to existing cmdline (single line, no newline)
        CURRENT=$(cat "$CMDLINE")
        echo -n "$CURRENT systemd.run=/boot/firmware/firstrun.sh systemd.run_success_action=reboot systemd.unit=kernel-command-line.target" > "$CMDLINE"
        log "firstrun.sh wired into cmdline.txt"
    else
        log "cmdline.txt already has firstrun entry — skipping"
    fi
else
    warn "cmdline.txt not found at $CMDLINE — firstrun.sh won't auto-run"
    warn "After first boot, SSH in and run: sudo bash /home/pi/midi-box/scripts/pi_setup.sh"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║      SD card injection complete!             ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo
echo -e "  1. Eject the SD card:  ${CYAN}diskutil eject $BOOT_VOL${NC}"
echo -e "  2. Insert into Pi and power on"
echo -e "  3. First boot will take ~5 minutes (installing packages)"
echo -e "  4. Pi will reboot automatically"
echo -e "  5. After reboot, connect to WiFi: ${CYAN}MIDI-BOX${NC}"
echo -e "  6. Open: ${CYAN}http://192.168.4.1:8080${NC}"
echo
echo -e "  Progress log (after SSH in): ${CYAN}cat /var/log/midi-box-firstrun.log${NC}"
echo
warn "If firstrun.sh doesn't auto-run, SSH in as pi@raspberrypi.local and run:"
echo -e "  ${CYAN}sudo bash /home/pi/midi-box/scripts/pi_setup.sh${NC}"
echo
