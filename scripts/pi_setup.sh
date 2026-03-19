#!/usr/bin/env bash
# =============================================================================
# MIDI Box — Raspberry Pi One-Command Installer
# =============================================================================
#
# Run ONCE on a fresh Raspberry Pi after first boot:
#
#   git clone <your-repo> ~/midi-box
#   cd ~/midi-box
#   sudo bash scripts/pi_setup.sh
#
# Or specify your WiFi country (ISO 3166-1 alpha-2):
#
#   sudo WIFI_COUNTRY=TR bash scripts/pi_setup.sh
#
# What this does:
#   1. Fixes WiFi (rfkill unblock, country code)
#   2. Updates system packages
#   3. Installs Python 3 + MIDI + networking dependencies
#   4. Creates Python venv + installs pip requirements
#   5. Installs systemd service (autostart on boot)
#   6. Configures WiFi Access Point (MIDI-BOX hotspot)
#   7. Reboots
#
# After reboot:
#   - WiFi network "MIDI-BOX" will be visible
#   - Web UI at http://192.168.4.1:8080
#   - Display / QR page at http://192.168.4.1:8080/display
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Config — override via env vars before running
# ---------------------------------------------------------------------------
WIFI_COUNTRY="${WIFI_COUNTRY:-US}"   # Your country code (TR, GB, DE, FR, etc.)
SERVICE_USER="${SERVICE_USER:-$(logname 2>/dev/null || echo pi)}"
HOME_WIFI_SSID="${HOME_WIFI_SSID:-}"   # Optional: home WiFi SSID for internet access
HOME_WIFI_PASS="${HOME_WIFI_PASS:-}"   # Optional: home WiFi password

# --update-only: skip WiFi AP, UART overlays, kiosk, and reboot prompt.
# Used when pi_setup.sh is called from update.sh for system-level upgrades.
UPDATE_ONLY=false
for arg in "$@"; do [[ "$arg" == "--update-only" ]] && UPDATE_ONLY=true; done

# Colours
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()   { echo -e "${GREEN}[✓]${NC} $*"; }
info()  { echo -e "${CYAN}[→]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗] ERROR:${NC} $*"; exit 1; }
step()  { echo; echo -e "${CYAN}━━━ $* ━━━${NC}"; }

# ---------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------
[[ "$(id -u)" -ne 0 ]] && error "Run as root:  sudo bash scripts/pi_setup.sh"

# Detect project root (the directory containing this script's parent)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SOFTWARE_DIR="$PROJECT_DIR/software"
CONFIG_DIR="$SOFTWARE_DIR/config"

[[ -d "$SOFTWARE_DIR" ]] || error "Cannot find software/ directory at: $SOFTWARE_DIR"
[[ -f "$SOFTWARE_DIR/requirements.txt" ]] || error "Cannot find requirements.txt at: $SOFTWARE_DIR/requirements.txt"

echo
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║       MIDI Box — Raspberry Pi Setup          ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo
info "Project dir : $PROJECT_DIR"
info "Software dir: $SOFTWARE_DIR"
info "Run as user : $SERVICE_USER"
info "WiFi country: $WIFI_COUNTRY"
echo

# ---------------------------------------------------------------------------
# 1. Fix WiFi rfkill  (this is the most common first-boot issue)
# ---------------------------------------------------------------------------
step "1/6  Fixing WiFi (rfkill + country code)"

# Unblock all radios
rfkill unblock all 2>/dev/null && log "rfkill: all radios unblocked" || warn "rfkill command not available"

# Set WiFi regulatory country — this is what Pi OS requires before WiFi works
if command -v raspi-config &>/dev/null; then
    raspi-config nonint do_wifi_country "$WIFI_COUNTRY" \
        && log "WiFi country set to $WIFI_COUNTRY via raspi-config" \
        || warn "raspi-config country set failed — trying iw..."
fi

# Fallback: set via iw reg
if command -v iw &>/dev/null; then
    iw reg set "$WIFI_COUNTRY" 2>/dev/null && log "WiFi regulatory domain set via iw" || true
fi

# Make country persist across reboots via /etc/wpa_supplicant/wpa_supplicant.conf
WPA_CONF="/etc/wpa_supplicant/wpa_supplicant.conf"
if [[ -f "$WPA_CONF" ]]; then
    if ! grep -q "country=" "$WPA_CONF"; then
        sed -i "1a country=$WIFI_COUNTRY" "$WPA_CONF"
        log "Added country=$WIFI_COUNTRY to wpa_supplicant.conf"
    else
        sed -i "s/^country=.*/country=$WIFI_COUNTRY/" "$WPA_CONF"
        log "Updated country=$WIFI_COUNTRY in wpa_supplicant.conf"
    fi
else
    # Create minimal wpa_supplicant.conf (AP mode doesn't need networks block)
    cat > "$WPA_CONF" << EOF
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=$WIFI_COUNTRY
EOF
    log "Created wpa_supplicant.conf with country=$WIFI_COUNTRY"
fi

# ---------------------------------------------------------------------------
# 2. System update
# ---------------------------------------------------------------------------
step "2/6  Updating system packages"

apt-get update -qq
apt-get upgrade -y -qq
log "System packages up to date"

# ---------------------------------------------------------------------------
# 3. Install system dependencies
# ---------------------------------------------------------------------------
step "3/6  Installing Python + MIDI + networking + kiosk packages"

apt-get install -y -qq \
    python3 python3-pip python3-venv \
    python3-rtmidi \
    libasound2-dev \
    hostapd dnsmasq \
    avahi-daemon avahi-utils \
    chromium xorg openbox unclutter \
    git curl

log "System packages installed"

# ---------------------------------------------------------------------------
# 4. Python virtual environment + pip packages
# ---------------------------------------------------------------------------
step "4/6  Setting up Python environment"

VENV_DIR="$SOFTWARE_DIR/.venv"

if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
    log "Created venv at $VENV_DIR"
else
    log "Existing venv found at $VENV_DIR"
fi

"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$SOFTWARE_DIR/requirements.txt" -q
log "Python packages installed"

# ---------------------------------------------------------------------------
# 5. Systemd service
# ---------------------------------------------------------------------------
step "5/6  Installing systemd service"

# Resolve the real home dir for the service user
USER_HOME=$(getent passwd "$SERVICE_USER" | cut -d: -f6 2>/dev/null || echo "/home/$SERVICE_USER")

SERVICE_FILE="/etc/systemd/system/midi-box.service"
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=MIDI Box Router
Documentation=https://github.com/your-org/midi-box
After=network.target sound.target
Wants=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$SOFTWARE_DIR
ExecStart=$VENV_DIR/bin/python src/main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
StandardOutput=journal
StandardError=journal
SyslogIdentifier=midi-box

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable midi-box.service
log "Service installed and enabled: midi-box.service"
info "  Control: sudo systemctl {start|stop|restart|status} midi-box"
info "  Logs:    sudo journalctl -u midi-box -f"

# Sudoers: allow the service user to update hostapd config, restart it,
# and reboot the Pi without a password — needed for the web UI.
SUDOERS_FILE="/etc/sudoers.d/midi-box-wifi"
cat > "$SUDOERS_FILE" << EOF
# MIDI Box — allow web UI to update WiFi AP credentials without a password
$SERVICE_USER ALL=(ALL) NOPASSWD: /usr/bin/tee /etc/hostapd/hostapd.conf
$SERVICE_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart hostapd
$SERVICE_USER ALL=(ALL) NOPASSWD: /sbin/reboot
EOF
chmod 0440 "$SUDOERS_FILE"
log "Sudoers entry written: $SUDOERS_FILE"

# Sudoers: allow service user to run the update script and restart the service
# without a password — needed for the web UI software update feature.
SUDOERS_UPDATE="/etc/sudoers.d/midi-box-update"
cat > "$SUDOERS_UPDATE" << EOF
# MIDI Box — allow web UI to trigger software updates without a password
$SERVICE_USER ALL=(ALL) NOPASSWD: $(dirname "$0")/update.sh *
$SERVICE_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart midi-box.service
EOF
chmod 0440 "$SUDOERS_UPDATE"
log "Sudoers entry written: $SUDOERS_UPDATE"

# Sudoers: allow service user to run VirtualHere setup and start/stop the server
# without a password — needed for the web UI USB Share page.
SUDOERS_VH="/etc/sudoers.d/midi-box-virtualhere"
cat > "$SUDOERS_VH" << EOF
# MIDI Box — allow web UI to install and control VirtualHere USB server
$SERVICE_USER ALL=(ALL) NOPASSWD: $SCRIPT_DIR/setup_virtualhere.sh
$SERVICE_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl start vhusbd
$SERVICE_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop vhusbd
EOF
chmod 0440 "$SUDOERS_VH"
log "Sudoers entry written: $SUDOERS_VH"

# Install VirtualHere USB server
if [[ "$UPDATE_ONLY" == "false" ]]; then
    step "Running VirtualHere USB server setup"
    bash "$SCRIPT_DIR/setup_virtualhere.sh" || warn "VirtualHere setup failed — run manually later from the web UI USB Share page"
fi

if [[ "$UPDATE_ONLY" == "false" ]]; then

# ---------------------------------------------------------------------------
# 6. WiFi Access Point
# ---------------------------------------------------------------------------
step "6/8  Configuring WiFi Access Point"

bash "$CONFIG_DIR/setup_wifi_ap.sh"

# ---------------------------------------------------------------------------
# 7. UART overlays + touchscreen kiosk
# ---------------------------------------------------------------------------
# Connect to home WiFi via NetworkManager (optional — for SSH / internet access)
if [[ -n "$HOME_WIFI_SSID" ]]; then
    info "Connecting wlan0 to home WiFi: $HOME_WIFI_SSID"
    nmcli device wifi connect "$HOME_WIFI_SSID" password "$HOME_WIFI_PASS" ifname wlan0 \
        && log "Connected to $HOME_WIFI_SSID on wlan0" \
        || warn "Could not connect to $HOME_WIFI_SSID — configure manually: nmcli device wifi connect SSID password PASS"
else
    info "No HOME_WIFI_SSID set — skipping home WiFi. To add later:"
    info "  sudo nmcli device wifi connect \"YourNetwork\" password \"YourPass\""
fi

step "7/8  Setting up boot splash screen"

bash "$SCRIPT_DIR/setup_splash.sh"

step "8/8  Configuring UART overlays and touchscreen kiosk"

BOOT_CONFIG="/boot/firmware/config.txt"
[[ -f "$BOOT_CONFIG" ]] || BOOT_CONFIG="/boot/config.txt"  # fallback for older Pi OS

# Add UART overlays if not already present
if ! grep -q "disable-bt" "$BOOT_CONFIG"; then
    cat >> "$BOOT_CONFIG" << 'EOF'

# MIDI Box — UART overlays for 4x hardware MIDI OUT ports (replaces SC16IS752)
dtoverlay=disable-bt    # frees UART0 (GPIO 14) from Bluetooth → MS-20 Mini
dtoverlay=uart3         # GPIO 4  → /dev/ttyAMA2 → Volca #1
dtoverlay=uart4         # GPIO 8  → /dev/ttyAMA3 → Volca #2
dtoverlay=uart5         # GPIO 12 → /dev/ttyAMA4 → Volca #3

# Raspberry Pi 7" Official Touchscreen (DSI, auto-detected — no extra config needed)
EOF
    log "UART overlays added to $BOOT_CONFIG"
else
    log "UART overlays already present in $BOOT_CONFIG — skipping"
fi

# Disable Bluetooth service (UART0 is now used for MIDI)
systemctl disable bluetooth 2>/dev/null && log "Bluetooth disabled (UART0 reserved for MIDI)" || true

# Allow any user to start X — needed because the default Xwrapper "console" check
# relies on systemd-logind seat assignment, which can fail when the kernel console
# is redirected to a different tty (console=tty3 for splash screen).
# Safe on a dedicated kiosk device.
echo "allowed_users=anybody" > /etc/X11/Xwrapper.config
log "Xwrapper.config set to allowed_users=anybody"

# Kiosk: create ~/.xinitrc to launch Chromium fullscreen on the touchscreen
XINITRC="/home/$SERVICE_USER/.xinitrc"
cat > "$XINITRC" << 'EOF'
#!/bin/sh
# MIDI Box kiosk — fullscreen Chromium on the 7" touchscreen
xset -dpms          # disable display power management
xset s noblank      # disable screen blanking
xset s off          # disable screensaver
unclutter -idle 1 -root &   # hide mouse cursor after 1s idle

# Paint the root window the same dark colour as the boot splash so there is no
# jarring flash between Plymouth → X desktop → Chromium.
xsetroot -solid '#0d1117'

# Wait for the MIDI Box web server to be ready
until curl -sf http://localhost:8080/api/settings > /dev/null 2>&1; do sleep 1; done

exec chromium \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --no-first-run \
    --disable-restore-session-state \
    --disable-session-crashed-bubble \
    --touch-events=enabled \
    http://localhost:8080/display
EOF
chmod +x "$XINITRC"
chown "$SERVICE_USER:$SERVICE_USER" "$XINITRC"
log "Kiosk .xinitrc written for user $SERVICE_USER"

# Autologin on tty1: getty override so datcal logs in automatically on boot
GETTY_OVERRIDE_DIR="/etc/systemd/system/getty@tty1.service.d"
mkdir -p "$GETTY_OVERRIDE_DIR"
cat > "$GETTY_OVERRIDE_DIR/autologin.conf" << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $SERVICE_USER --noclear %I \$TERM
EOF
log "getty autologin configured for user $SERVICE_USER on tty1"

# Suppress login banner (motd, last-login line) — hushlogin makes the autologin silent
touch "/home/$SERVICE_USER/.hushlogin"
chown "$SERVICE_USER:$SERVICE_USER" "/home/$SERVICE_USER/.hushlogin"
log "Created .hushlogin for silent autologin"

# Trigger startx from bash_profile when on tty1 (idempotent).
# - 'clear' wipes the tty so no shell text flashes between Plymouth and X
# - '>/dev/null 2>&1' suppresses X server startup messages
#
# NOTE: Do NOT use sed to update this line — the '&' characters in the startx
# command are interpreted as sed back-references and corrupt the file.
# Instead, remove any old startx line with grep -v, then append the new one.
BASH_PROFILE="/home/$SERVICE_USER/.bash_profile"
STARTX_LINE='[[ -z $DISPLAY && $XDG_VTNR -eq 1 ]] && { clear; exec startx >/dev/null 2>&1; }'

# Remove any existing startx line (safe: grep -v writes to temp file first)
if grep -qF 'exec startx' "$BASH_PROFILE" 2>/dev/null; then
    grep -v 'exec startx' "$BASH_PROFILE" > "$BASH_PROFILE.tmp"
    mv "$BASH_PROFILE.tmp" "$BASH_PROFILE"
    log "Removed old startx line from $BASH_PROFILE"
fi
# Append the new silent version
echo "$STARTX_LINE" >> "$BASH_PROFILE"
chown "$SERVICE_USER:$SERVICE_USER" "$BASH_PROFILE"
log "startx trigger written to $BASH_PROFILE"

# Remove the old broken kiosk service if it exists
if [[ -f /etc/systemd/system/midi-box-kiosk.service ]]; then
    systemctl disable midi-box-kiosk.service 2>/dev/null || true
    rm -f /etc/systemd/system/midi-box-kiosk.service
    log "Removed old midi-box-kiosk.service"
fi

systemctl daemon-reload

# ---------------------------------------------------------------------------
# Done!
# ---------------------------------------------------------------------------
AP_SSID=$(grep 'AP_SSID=' "$CONFIG_DIR/setup_wifi_ap.sh" | head -1 | cut -d'"' -f2)
AP_PASS=$(grep 'AP_PASS=' "$CONFIG_DIR/setup_wifi_ap.sh" | head -1 | cut -d'"' -f2)
AP_IP=$(grep 'AP_IP=' "$CONFIG_DIR/setup_wifi_ap.sh" | head -1 | cut -d'"' -f2)

echo
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         Setup complete!                       ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo
echo -e "  WiFi network : ${CYAN}${AP_SSID:-MIDI-BOX}${NC}"
echo -e "  Password     : ${CYAN}${AP_PASS:-midibox123}${NC}"
echo -e "  Web UI       : ${CYAN}http://${AP_IP:-192.168.4.1}:8080${NC}"
echo -e "  Display/QR   : ${CYAN}http://${AP_IP:-192.168.4.1}:8080/display${NC}"
echo

read -r -p "  Reboot now? [Y/n] " REPLY
REPLY="${REPLY:-Y}"
if [[ "$REPLY" =~ ^[Yy]$ ]]; then
    log "Rebooting in 3 seconds..."
    sleep 3
    reboot
else
    warn "Remember to reboot for WiFi AP to take effect!"
    info "  sudo reboot"
fi

fi  # end of UPDATE_ONLY == false block
